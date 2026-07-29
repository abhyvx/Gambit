"""Fetch Stake.com GraphQL through a REAL browser (Playwright).

Stake sits behind Cloudflare's *managed challenge*, which a plain HTTP client
can't pass (no matter the headers / TLS fingerprint) because it requires
executing JavaScript. A real browser solves the challenge automatically and
earns a `cf_clearance` cookie. We keep one persistent browser alive
and run the GraphQL `fetch()` from inside the stake.com page, so every request
reuses the cleared, logged-in session.

Threading: Playwright's sync API must always be driven from the SAME thread.
FastAPI serves requests from a thread pool, so we pin ALL browser work to one
dedicated worker thread via a single-worker executor.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from bet_placer.config import data_path

logger = logging.getLogger(__name__)

# Persistent Chrome profile — log in / pass Cloudflare once, reused forever.
# Override with STAKE_PROFILE_DIR for portfolio sync (avoids odds-link lock fights).
PROFILE_DIR = Path(
    (os.environ.get("STAKE_PROFILE_DIR") or "").strip()
    or str(data_path("stake_profile"))
)
AUTH_PATH = data_path("stake_auth.json")
STAKE_URL = "https://stake.com/sports/soccer"
STAKE_LOGIN_URL = "https://stake.com/?tab=login&modal=auth"
GRAPHQL_PATH = "/_api/graphql"

USER_PROBE_QUERY = "query { user { id name } }"


# All Playwright calls run on this single thread.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stake-browser")
_state: dict[str, Any] = {
    "pw": None,
    "context": None,
    "page": None,
    "ready": False,
    "warming": False,
    "last_error": None,
    "launch_headless": None,
    "auth_token": "",
    "remote": False,
    "session_id": None,
    "login_url": None,
    "browser": None,  # CDP browser handle (remote only)
}
_init_lock = threading.Lock()
_init_cond = threading.Condition(_init_lock)
_init_failed_ts: float = 0.0
_profile_lock_handled = False
_recovery_used = False
_visible_cf_retry_used = False

INIT_FAIL_COOLDOWN_SECONDS = 90.0
_HEADLESS_CF_TIMEOUT_S = 20  # fast-fail headless; open one visible window if blocked


class StakeBrowserError(RuntimeError):
    pass


def _headless() -> bool:
    try:
        from bet_placer.config import data_path, get_settings
        return bool(get_settings().stake_browser_headless)
    except Exception:
        return True


def _token_capture_init_script() -> str:
    return """
        (() => {
          window.__betplacerAuthToken = window.__betplacerAuthToken || '';
          const captureHeaders = (headersLike) => {
            try {
              if (!headersLike) return;
              const pairs = [];
              if (Array.isArray(headersLike)) {
                pairs.push(...headersLike);
              } else if (headersLike instanceof Headers) {
                for (const pair of headersLike.entries()) pairs.push(pair);
              } else if (typeof headersLike === 'object') {
                for (const [k, v] of Object.entries(headersLike)) pairs.push([k, v]);
              }
              for (const [key, value] of pairs) {
                if (String(key).toLowerCase() === 'x-access-token' && value) {
                  window.__betplacerAuthToken = String(value);
                }
              }
            } catch (e) {}
          };

          const origFetch = window.fetch;
          window.fetch = async (...args) => {
            try {
              const init = args[1] || {};
              captureHeaders(init.headers);
            } catch (e) {}
            return origFetch(...args);
          };

          const origOpen = XMLHttpRequest.prototype.open;
          const origSetHeader = XMLHttpRequest.prototype.setRequestHeader;
          XMLHttpRequest.prototype.open = function(...args) {
            this.__betplacerHeaders = {};
            return origOpen.apply(this, args);
          };
          XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
            try {
              this.__betplacerHeaders = this.__betplacerHeaders || {};
              this.__betplacerHeaders[name] = value;
              captureHeaders(this.__betplacerHeaders);
            } catch (e) {}
            return origSetHeader.apply(this, [name, value]);
          };
        })();
        """


def _launch_context(pw, *, headless: bool | None = None):
    """Launch the persistent Chrome context (headful or headless per arg/config)."""
    if headless is None:
        headless = _headless()
    context = pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        viewport={"width": 1280, "height": 860},
    )
    context.add_init_script(_token_capture_init_script())
    return context


def is_installed() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def kill_orphan_profile_chrome(force: bool = False) -> int:
    """Kill stray Chrome on OUR profile dir — never the live verification window.

    When the managed session is warming or ready (user may be completing
    Cloudflare in the open window), this is a no-op unless force=True.
    """
    import subprocess

    if not force and (_state.get("ready") or _state.get("warming")):
        logger.debug("Skipping orphan Chrome kill — active Stake session")
        return 0

    killed = 0
    needle = f"--user-data-dir={PROFILE_DIR}"
    try:
        out = subprocess.run(["pgrep", "-f", needle], capture_output=True, text=True, timeout=5)
        pids = [p for p in out.stdout.split() if p.strip()]
        for pid in pids:
            try:
                subprocess.run(["kill", "-9", pid], timeout=5)
                killed += 1
            except Exception:
                pass
    except Exception as exc:
        logger.debug("orphan chrome scan failed: %s", exc)

    if not force and (_state.get("ready") or _state.get("warming")):
        return 0

    for lock in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            (PROFILE_DIR / lock).unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass
    if killed:
        logger.info("Cleared %d orphaned Stake-profile Chrome process(es)", killed)
    return killed


def wait_for_browser_ready(timeout_s: float = 180.0) -> bool:
    """Block until the managed browser finishes starting (e.g. user on Cloudflare)."""
    deadline = time.monotonic() + timeout_s
    with _init_cond:
        while time.monotonic() < deadline:
            if _state.get("ready") and _state.get("page"):
                return True
            if _init_failed_ts and (time.monotonic() - _init_failed_ts) < INIT_FAIL_COOLDOWN_SECONDS:
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            _init_cond.wait(timeout=min(5.0, remaining))
        return bool(_state.get("ready") and _state.get("page"))


def browser_status() -> dict[str, Any]:
    """Lightweight status for /api/health — never touches Playwright."""
    restore_auth_token()
    now = time.monotonic()
    failed = _init_failed_ts > 0 and (now - _init_failed_ts) < INIT_FAIL_COOLDOWN_SECONDS
    return {
        "installed": is_installed(),
        "ready": bool(_state.get("ready")),
        "warming": bool(_state.get("warming")),
        "failed": failed,
        "retry_in_s": round(max(0.0, INIT_FAIL_COOLDOWN_SECONDS - (now - _init_failed_ts)), 1) if failed else 0,
        "last_error": (_state.get("last_error") or "")[:200] or None,
        "profile_dir": str(PROFILE_DIR),
        "headless": _state.get("launch_headless") if _state.get("launch_headless") is not None else _headless(),
        "have_auth_token": bool(_state.get("auth_token")),
        "remote": bool(_state.get("remote")),
        "login_url": _state.get("login_url"),
        "session_id": _state.get("session_id"),
    }


def _clearance_probe_js() -> str:
    return (
        "async () => {"
        "  try {"
        "    const r = await fetch('" + GRAPHQL_PATH + "', {"
        "      method: 'POST',"
        "      headers: {'content-type': 'application/json', 'x-language': 'en'},"
        "      body: JSON.stringify({query: '{__typename}'})"
        "    });"
        "    const t = await r.text();"
        "    return {status: r.status, text: t.slice(0, 200)};"
        "  } catch (e) { return {status: -1, text: String(e)}; }"
        "}"
    )


def _wait_for_clearance(page, timeout_s: int = 240) -> None:
    """Poll the GraphQL endpoint from inside the page until Cloudflare clears."""
    deadline = time.time() + timeout_s
    last = ""
    while time.time() < deadline:
        try:
            res = page.evaluate(_clearance_probe_js())
            last = f"{res.get('status')}: {res.get('text', '')[:80]}"
            if res.get("status") == 200:
                return
        except Exception as exc:  # page mid-navigation during challenge
            last = str(exc)[:80]
        time.sleep(2.5)
    raise StakeBrowserError(
        f"Cloudflare challenge not cleared within {timeout_s}s (last: {last}). "
        "Complete the check in the open Chrome window — do not close it."
    )


def _is_profile_lock_error(exc: Exception) -> bool:
    low = str(exc).lower()
    return "profile is already open" in low or "already in use" in low


def _mark_init_failed(exc: Exception) -> None:
    global _init_failed_ts
    _state["last_error"] = str(exc)[:300]
    _init_failed_ts = time.monotonic()


def _clear_init_failed() -> None:
    global _init_failed_ts
    _init_failed_ts = 0.0
    _state["last_error"] = None


def _capture_auth_token(page) -> None:
    try:
        token = page.evaluate("() => window.__betplacerAuthToken || ''")
    except Exception:
        token = ""
    if not token:
        try:
            token = page.evaluate(
                """() => {
                  const keys = [];
                  try {
                    for (let i = 0; i < localStorage.length; i++) keys.push(localStorage.key(i));
                    for (let i = 0; i < sessionStorage.length; i++) keys.push('s:' + sessionStorage.key(i));
                  } catch (e) {}
                  const bag = [];
                  for (const k of keys) {
                    try {
                      const raw = k.startsWith('s:')
                        ? sessionStorage.getItem(k.slice(2))
                        : localStorage.getItem(k);
                      if (!raw) continue;
                      if (/accessToken|apiToken|authToken|token/i.test(k) || /accessToken|apiToken/.test(raw)) {
                        bag.push(raw);
                      }
                      const m = String(raw).match(/eyJ[a-zA-Z0-9_-]{20,}\\.[a-zA-Z0-9_-]+\\.[a-zA-Z0-9_-]+/);
                      if (m) bag.push(m[0]);
                    } catch (e) {}
                  }
                  return bag[0] || '';
                }"""
            )
        except Exception:
            token = ""
    if token:
        _state["auth_token"] = str(token)
        _persist_auth_token(str(token))


def _persist_auth_token(token: str) -> None:
    try:
        AUTH_PATH.parent.mkdir(parents=True, exist_ok=True)
        AUTH_PATH.write_text(
            json.dumps({"token": token, "updated_at": time.time()}),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.debug("stake auth persist failed: %s", exc)


def _load_persisted_auth_token() -> str:
    try:
        if not AUTH_PATH.is_file():
            return ""
        raw = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
        return str(raw.get("token") or "")
    except Exception:
        return ""


def restore_auth_token() -> bool:
    """Load saved token into memory (survives API restart)."""
    tok = _load_persisted_auth_token()
    if tok:
        _state["auth_token"] = tok
        return True
    return False



def _reset_on_thread() -> None:
    global _recovery_used, _profile_lock_handled
    _teardown(_state.get("pw"), _state.get("context"), _state.get("browser"))
    _recovery_used = False
    _profile_lock_handled = False


def _reset() -> None:
    # Must run on the Playwright worker thread.
    _reset_on_thread()


def _launch_remote_once() -> None:
    """Connect to Browserbase / STAKE_CDP_URL (cloud Chrome tab)."""
    from playwright.sync_api import sync_playwright

    from bet_placer.data.stake_remote import create_remote_session

    pw = None
    browser = None
    try:
        session = create_remote_session(timeout_s=7200, keep_alive=True)
        pw = sync_playwright().start()
        browser = pw.chromium.connect_over_cdp(session["connect_url"])
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        try:
            context.add_init_script(_token_capture_init_script())
        except Exception:
            pass
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(STAKE_URL, wait_until="domcontentloaded", timeout=90000)
        except Exception:
            pass
        _wait_for_clearance(page, timeout_s=180)
        _capture_auth_token(page)
        _state.update(
            pw=pw,
            browser=browser,
            context=context,
            page=page,
            ready=True,
            launch_headless=True,
            remote=True,
            session_id=session.get("session_id"),
            login_url=session.get("login_url"),
        )
        _clear_init_failed()
        logger.info(
            "Stake cloud browser ready (provider=%s session=%s)",
            session.get("provider"),
            session.get("session_id"),
        )
    except Exception:
        _teardown(pw, None, browser)
        raise


def _launch_browser_once(preferred_headless: bool | None = None) -> None:
    """Launch persistent Chromium on the worker thread (caller holds _init_lock)."""
    global _profile_lock_handled, _visible_cf_retry_used

    from bet_placer.data.stake_remote import remote_browser_configured

    # Prefer cloud Chrome when configured (works on Render).
    if remote_browser_configured():
        _launch_remote_once()
        return

    from playwright.sync_api import sync_playwright

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    def _try_launch(headless: bool, cf_timeout: int) -> None:
        pw = None
        context = None
        try:
            pw = sync_playwright().start()
            context = _launch_context(pw, headless=headless)
            page = context.pages[0] if context.pages else context.new_page()
            try:
                page.goto(STAKE_URL, wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass
            _wait_for_clearance(page, timeout_s=cf_timeout)
            _capture_auth_token(page)
            _state.update(
                pw=pw,
                context=context,
                page=page,
                ready=True,
                launch_headless=headless,
                remote=False,
                session_id=None,
                login_url=None,
            )
            _clear_init_failed()
        except Exception:
            _teardown(pw, context)
            raise

    try:
        use_headless = _headless() if preferred_headless is None else bool(preferred_headless)
        cf_timeout = _HEADLESS_CF_TIMEOUT_S if use_headless else 240
        _try_launch(use_headless, cf_timeout)
    except Exception as exc:
        msg = str(exc)
        if (
            use_headless
            and not _visible_cf_retry_used
            and ("cloudflare" in msg.lower() or "403" in msg or "just a moment" in msg.lower())
        ):
            _visible_cf_retry_used = True
            logger.info("Headless Stake blocked by Cloudflare — opening one visible Chrome window")
            try:
                _try_launch(headless=False, cf_timeout=300)
                return
            except Exception as vis_exc:
                exc = vis_exc
                msg = str(vis_exc)

        if _is_profile_lock_error(exc) and not _profile_lock_handled:
            _profile_lock_handled = True
            logger.info(
                "Stake profile in use — waiting for the open Chrome window "
                "(complete Cloudflare there; we will not close it)"
            )
            if wait_for_browser_ready(timeout_s=180.0):
                return
            _mark_init_failed(exc)
            raise StakeBrowserError(
                "Stake Chrome is still open — finish the Cloudflare check in that "
                "window, then refresh the app. We never close it while you verify."
            ) from exc
        _mark_init_failed(exc)
        if _is_profile_lock_error(exc):
            raise StakeBrowserError(
                "Stake browser profile is already open in another window. "
                "Close any other Bet Placer / Chrome Stake windows and retry."
            ) from exc
        raise


def _ensure_browser(launch_if_needed: bool = True, preferred_headless: bool | None = None) -> None:
    """Launch (once) a persistent Chromium and clear Cloudflare."""
    def _want_local_headful_upgrade() -> bool:
        # Remote cloud sessions have no local window — never tear them down for headful.
        if _state.get("remote"):
            return False
        return preferred_headless is False and _state.get("launch_headless") is True

    if _state["ready"] and _state["page"]:
        if _want_local_headful_upgrade():
            _reset_on_thread()
        else:
            return

    with _init_cond:
        if _state["ready"] and _state["page"]:
            if _want_local_headful_upgrade():
                _reset_on_thread()
            else:
                return

        if not launch_if_needed:
            if _state.get("warming"):
                raise StakeBrowserError("Stake browser is starting — try again in a moment.")
            if _init_failed_ts and (time.monotonic() - _init_failed_ts) < INIT_FAIL_COOLDOWN_SECONDS:
                raise StakeBrowserError(
                    _state.get("last_error")
                    or "Stake browser unavailable — open Stake odds to connect."
                )
            raise StakeBrowserError(
                "Stake browser not started yet — open the Stake odds tab to connect."
            )

        if _init_failed_ts and (time.monotonic() - _init_failed_ts) < INIT_FAIL_COOLDOWN_SECONDS:
            raise StakeBrowserError(_state.get("last_error") or "Stake browser recently failed")

        while _state.get("warming"):
            _init_cond.wait(timeout=5.0)
            if _state["ready"] and _state["page"]:
                return
            if _init_failed_ts and (time.monotonic() - _init_failed_ts) < INIT_FAIL_COOLDOWN_SECONDS:
                raise StakeBrowserError(_state.get("last_error") or "Stake browser recently failed")

        if _state["ready"] and _state["page"]:
            return

        # A failed launch leaves Playwright's asyncio loop running on this
        # worker thread; always tear down before trying sync_playwright() again.
        if _state.get("pw") or _state.get("context"):
            _reset_on_thread()

        _state["warming"] = True
        _init_cond.notify_all()

    try:
        _launch_browser_once(preferred_headless=preferred_headless)
    except Exception:
        raise
    finally:
        with _init_cond:
            _state["warming"] = False
            _init_cond.notify_all()


def _teardown(pw=None, context=None, browser=None) -> None:
    """Stop a half-built or stale Playwright session (must run on worker thread)."""
    try:
        if browser and _state.get("remote"):
            browser.close()
    except Exception:
        pass
    try:
        if context and not _state.get("remote"):
            context.close()
    except Exception:
        pass
    try:
        if pw:
            pw.stop()
    except Exception:
        pass
    # Keep persisted token across relaunches — only the live browser session dies.
    _state.update(
        pw=None,
        context=None,
        page=None,
        browser=None,
        ready=False,
        launch_headless=None,
        remote=False,
        session_id=None,
        login_url=None,
        auth_token=_load_persisted_auth_token() or "",
    )


def _relaunch_preference() -> bool | None:
    """Keep the visible login window when recovering a portfolio session."""
    return False if _state.get("launch_headless") is False else None


def _graphql_on_thread(
    query: str,
    variables: dict | None,
    launch_if_needed: bool,
    access_token: str | None = None,
) -> dict[str, Any]:
    global _recovery_used
    _ensure_browser(launch_if_needed=launch_if_needed)
    page = _state["page"]
    if access_token:
        try:
            page.evaluate("(t) => { window.__betplacerAuthToken = t; }", access_token)
            _state["auth_token"] = access_token
        except Exception:
            pass
    js = (
        "async ({query, variables}) => {"
        "  const pickToken = () => {"
        "    if (window.__betplacerAuthToken) return window.__betplacerAuthToken;"
        "    const values = [];"
        "    const collect = (obj) => {"
        "      if (!obj || typeof obj !== 'object') return;"
        "      for (const [k, v] of Object.entries(obj)) {"
        "        if (v == null) continue;"
        "        if (typeof v === 'string') {"
        "          values.push([String(k), v]);"
        "          try { collect(JSON.parse(v)); } catch (e) {}"
        "        } else if (typeof v === 'object') {"
        "          collect(v);"
        "        }"
        "      }"
        "    };"
        "    try {"
        "      for (let i = 0; i < localStorage.length; i++) {"
        "        const key = localStorage.key(i);"
        "        if (!key) continue;"
        "        const val = localStorage.getItem(key);"
        "        values.push([key, val || '']);"
        "        try { collect(JSON.parse(val || 'null')); } catch (e) {}"
        "      }"
        "    } catch (e) {}"
        "    try {"
        "      for (let i = 0; i < sessionStorage.length; i++) {"
        "        const key = sessionStorage.key(i);"
        "        if (!key) continue;"
        "        const val = sessionStorage.getItem(key);"
        "        values.push([key, val || '']);"
        "        try { collect(JSON.parse(val || 'null')); } catch (e) {}"
        "      }"
        "    } catch (e) {}"
        "    const priority = ['x-access-token', 'accessToken', 'access_token', 'apiToken', 'token'];"
        "    for (const name of priority) {"
        "      const hit = values.find(([k, v]) => k && k.toLowerCase().includes(name.toLowerCase()) && v && v.length > 20);"
        "      if (hit) return hit[1];"
        "    }"
        "    const fallback = values.find(([k, v]) => /token|access/i.test(String(k || '')) && v && v.length > 20);"
        "    return fallback ? fallback[1] : '';"
        "  };"
        "  const token = pickToken();"
        "  if (token) window.__betplacerAuthToken = token;"
        "  const headers = {'content-type': 'application/json', 'x-language': 'en'};"
        "  if (token) headers['x-access-token'] = token;"
        "  const r = await fetch('" + GRAPHQL_PATH + "', {"
        "    method: 'POST',"
        "    headers,"
        "    credentials: 'include',"
        "    body: JSON.stringify({query, variables})"
        "  });"
        "  return {status: r.status, text: await r.text(), hasToken: Boolean(token)};"
        "}"
    )

    def _evaluate() -> dict[str, Any]:
        return page.evaluate(js, {"query": query, "variables": variables or {}})

    try:
        res = _evaluate()
    except Exception as exc:
        if _recovery_used:
            raise StakeBrowserError("Stake browser session lost") from exc
        _recovery_used = True
        # Retry once without tearing down — closing Chrome mid-login breaks portfolio sync.
        time.sleep(1.5)
        try:
            res = _evaluate()
        except Exception:
            preferred = _relaunch_preference()
            _reset_on_thread()
            _ensure_browser(launch_if_needed=True, preferred_headless=preferred)
            page = _state["page"]
            res = page.evaluate(js, {"query": query, "variables": variables or {}})

    status = res.get("status")
    if res.get("hasToken"):
        _capture_auth_token(page)
    if status != 200:
        snippet = str(res.get("text") or "")[:200]
        if status in (401, 403):
            raise StakeBrowserError(
                f"Stake returned {status} — finish logging into Stake in the open browser window, then retry."
            )
        raise StakeBrowserError(f"Stake GraphQL via browser returned {status}: {snippet}")

    data = json.loads(res["text"])
    if errors := data.get("errors"):
        raise StakeBrowserError(f"Stake GraphQL error: {errors[0].get('message', errors)}")
    _recovery_used = False
    return data.get("data") or {}


def graphql(
    query: str,
    variables: dict | None = None,
    timeout: int = 60,
    launch_if_needed: bool = True,
    access_token: str | None = None,
) -> dict[str, Any]:
    """Run a GraphQL query through the persistent browser (thread-safe)."""
    if not is_installed():
        raise StakeBrowserError("Playwright not installed — run: playwright install chromium")
    fut = _executor.submit(_graphql_on_thread, query, variables, launch_if_needed, access_token)
    return fut.result(timeout=timeout + 160)


def warmup(timeout: int = 300) -> bool:
    """Pre-launch the browser and clear Cloudflare. Returns True on success."""
    if _state.get("ready"):
        return True
    with _init_lock:
        if _state.get("ready"):
            return True
        if _state.get("warming"):
            logger.debug("Stake browser warmup skipped — already in progress")
            return False
    try:
        _executor.submit(_ensure_browser, True).result(timeout=timeout)
        return bool(_state.get("ready"))
    except Exception as exc:
        logger.warning("Stake browser warmup failed: %s", exc)
        return False


def warmup_visible(timeout: int = 300) -> bool:
    """Launch a visible browser window for Cloudflare/login when needed."""
    restore_auth_token()
    with _init_lock:
        if _state.get("warming"):
            logger.debug("Visible Stake warmup skipped — already in progress")
            return False
    try:
        _executor.submit(_ensure_browser, True, False).result(timeout=timeout)
        return bool(_state.get("ready"))
    except Exception as exc:
        logger.warning("Visible Stake browser warmup failed: %s", exc)
        return False


def _open_login_on_thread() -> None:
    _ensure_browser(launch_if_needed=True, preferred_headless=False)
    page = _state.get("page")
    if not page:
        raise StakeBrowserError("No Stake page")
    try:
        page.goto(STAKE_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    except Exception:
        pass
    # Best-effort click Sign in if modal didn't open
    for sel in (
        'button:has-text("Sign in")',
        'button:has-text("Log in")',
        'a:has-text("Sign in")',
        '[data-testid="login-button"]',
    ):
        try:
            page.locator(sel).first.click(timeout=1500)
            break
        except Exception:
            continue
    _capture_auth_token(page)
    # Refresh Browserbase live-view link after navigation (page debugger URL changes).
    if _state.get("remote") and _state.get("session_id"):
        try:
            from bet_placer.data.stake_remote import session_login_url

            url = session_login_url(str(_state["session_id"]))
            if url:
                _state["login_url"] = url
        except Exception as exc:
            logger.debug("refresh login_url failed: %s", exc)


def open_login_window() -> bool:
    """Open Stake auth modal (local Chrome or cloud live-view session)."""
    restore_auth_token()
    try:
        _executor.submit(_open_login_on_thread).result(timeout=120)
        return bool(_state.get("ready"))
    except Exception as exc:
        logger.warning("open_login_window failed: %s", exc)
        return False


def _probe_user_on_thread() -> dict[str, Any]:
    """Return {logged_in, user} using GraphQL user probe."""
    _ensure_browser(launch_if_needed=False)
    page = _state.get("page")
    if page:
        _capture_auth_token(page)
    try:
        data = _graphql_on_thread(USER_PROBE_QUERY, None, launch_if_needed=False)
        user = (data or {}).get("user") if isinstance(data, dict) else None
        if user and user.get("id"):
            return {"logged_in": True, "user": user}
    except Exception as exc:
        return {"logged_in": False, "error": str(exc)[:160]}
    return {"logged_in": False, "user": None}


def probe_logged_in() -> dict[str, Any]:
    restore_auth_token()
    if not _state.get("ready"):
        return {"logged_in": False, "ready": False, "have_auth_token": bool(_state.get("auth_token"))}
    try:
        out = _executor.submit(_probe_user_on_thread).result(timeout=45)
        out["ready"] = True
        out["have_auth_token"] = bool(_state.get("auth_token"))
        return out
    except Exception as exc:
        return {
            "logged_in": False,
            "ready": bool(_state.get("ready")),
            "have_auth_token": bool(_state.get("auth_token")),
            "error": str(exc)[:160],
        }


def wait_until_logged_in(timeout: int = 300) -> dict[str, Any]:
    """Open login UI and poll until Stake account GraphQL works (user must sign in)."""
    restore_auth_token()
    if not warmup_visible(timeout=min(120, timeout)):
        return {"logged_in": False, "ready": False, "message": "Could not start the Stake browser yet. Try again in a moment."}
    # Profile may already be signed in — don't force the auth modal first.
    probe = probe_logged_in()
    if probe.get("logged_in"):
        probe["message"] = f"Connected as {(probe.get('user') or {}).get('name') or (probe.get('user') or {}).get('id')}"
        probe["login_url"] = _state.get("login_url")
        return probe

    open_login_window()
    login_url = _state.get("login_url")
    deadline = time.time() + max(30, timeout)
    logger.info("Waiting for Stake account login (up to %ss)…", timeout)
    while time.time() < deadline:
        time.sleep(2.5)
        probe = probe_logged_in()
        if probe.get("logged_in"):
            probe["message"] = (
                f"Connected as {(probe.get('user') or {}).get('name') or (probe.get('user') or {}).get('id')}"
            )
            probe["login_url"] = _state.get("login_url")
            return probe
    msg = (
        "Sign into Stake in the browser window we opened, then tap Connect again."
        if not login_url
        else "Open the Stake window link, sign in, then tap Connect again."
    )
    return {
        "logged_in": False,
        "ready": bool(_state.get("ready")),
        "have_auth_token": bool(_state.get("auth_token")),
        "login_url": login_url,
        "message": msg,
    }


def shutdown() -> None:
    try:
        _executor.submit(_reset_on_thread).result(timeout=30)
    except Exception:
        pass

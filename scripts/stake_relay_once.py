"""One-shot Stake relay for GitHub Actions or laptop cron.

Tries live scrape; if Cloudflare blocks, pushes last-good disk cache.
Never fails the workflow — ESPN/model keep serving.
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    # Reuse the durable push path
    sys.path.insert(0, os.path.dirname(__file__))
    from push_stake_cache import main as push_main

    os.environ.setdefault("STAKE_USE_BROWSER", "true")
    return push_main()


if __name__ == "__main__":
    raise SystemExit(main())

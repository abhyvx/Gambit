"""Self-check: Stake odds fallback always returns priced 1X2 when Stake is dark."""

from __future__ import annotations


def main() -> None:
    from bet_placer.engine.stake_odds import _book_payout_fallback, get_stake_match_odds

    cases = [
        ("Liverpool", "Chelsea"),
        ("Arsenal", "Man City"),
        ("Nowhere United", "Fake Athletic"),
    ]
    for home, away in cases:
        r = _book_payout_fallback(home, away, 300.0)
        assert r.get("available") is True, r
        cats = r.get("categories") or []
        outs = sum(len(m.get("outcomes") or []) for c in cats for m in (c.get("markets") or []))
        assert outs >= 2, (home, away, r.get("source"), outs)
        assert r.get("source") not in (None, "none"), r
        note = (r.get("note") or "").lower()
        assert "draftkings" not in note, note
        print(f"ok fallback {home} vs {away} source={r.get('source')} outcomes={outs}")

    full = get_stake_match_odds("Liverpool", "Chelsea", 300.0)
    assert full.get("available") is True, full
    reason = (full.get("reason") or full.get("note") or "").lower()
    assert "draftkings" not in reason, reason
    print(f"ok full path source={full.get('source')}")
    print("check_stake_odds_fallback: ok")


if __name__ == "__main__":
    main()

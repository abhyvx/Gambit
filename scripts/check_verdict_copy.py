"""ponytail: verdict headlines include pick + model-vs-book."""
from types import SimpleNamespace
from datetime import datetime, timezone
from bet_placer.engine.verdict import MatchVerdictEngine
from bet_placer.models.enums import MarketType
from bet_placer.models.types import AnalysisResult, ValueBet
from bet_placer.api.server import _annotate_pick

vb = ValueBet(
    match_id="1", match_label="A vs B", market=MarketType.MATCH_WINNER,
    selection="home", line=None, decimal_odds=1.9,
    implied_probability=1 / 1.9, true_probability=0.58,
    expected_value=0.102, expected_roi=0.102, kelly_stake_pct=4.0,
    confidence=0.7, risk_score=0.3, variance=0.2, rank_score=1.0,
    explanation="x", kickoff=datetime.now(timezone.utc),
)
m = SimpleNamespace(home_team="A", away_team="B", market_odds=[], id="1", league="EPL")
v = MatchVerdictEngine().evaluate(AnalysisResult(match=m, probabilities=[], value_bets=[vb], top_bets=[vb]))
assert "1.90" in v.headline and "model" in v.reasoning[0].lower()
assert "match_winner" not in v.headline.lower()
assert "\u2014" not in v.headline and "\u2013" not in v.headline
p = _annotate_pick({"decimal_odds": 2.0, "true_probability": 0.55})
assert p["model_pct"] == 55 and p["book_pct"] == 50
print("check_verdict_copy_ok")

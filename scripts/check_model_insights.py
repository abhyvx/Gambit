"""Assert model insights expose 3-sport corpus + craft curves (no match dumps)."""
from bet_placer.ml.model_insights import build_model_insights


def main() -> None:
    i = build_model_insights()
    assert "sports" in i and "curves" in i and "craft" in i
    for sport in ("soccer", "basketball", "cricket"):
        assert sport in i["sports"], sport
        assert int(i["sports"][sport].get("corpus") or 0) >= 0
    assert int(i.get("total_corpus") or 0) > 0, "expected non-zero corpus from boards/history"
    assert "craft_roi" in i["curves"]
    # Aggregates only — never ship sample match lists here
    blob = str(i)
    assert "sample_matches" not in blob
    print("ok", i["total_corpus"], {s: i["sports"][s]["corpus"] for s in i["sports"]},
          "epochs", i["craft"].get("n_epochs"))


if __name__ == "__main__":
    main()

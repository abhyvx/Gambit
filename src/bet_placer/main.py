#!/usr/bin/env python3
"""CLI entry point for the Value Betting Engine."""

from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from bet_placer.config import get_settings
from bet_placer.data.collectors import DemoCollector
from bet_placer.engine.probability import ProbabilityEngine, rank_all_bets
from bet_placer.engine.stake_pipeline import StakeAnalysisPipeline
from bet_placer.learning.feedback import FeedbackLoop
from bet_placer.models.stake_types import Verdict


console = Console()

VERDICT_STYLE = {
    Verdict.BET: "bold green",
    Verdict.SKIP: "bold red",
    Verdict.CAUTION: "bold yellow",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AI Sports Betting Analyst & Value Betting Engine",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run with built-in demo data instead of Stake",
    )
    parser.add_argument(
        "--stake",
        action="store_true",
        help="Scrape live Stake.com odds and analyze all available markets (default mode)",
    )
    parser.add_argument(
        "--sport",
        type=str,
        default="soccer",
        help="Sport slug for Stake (default: soccer)",
    )
    parser.add_argument(
        "--fixture-id",
        type=str,
        default=None,
        help="Analyze a specific Stake fixture by ID",
    )
    parser.add_argument(
        "--min-ev",
        type=float,
        default=None,
        help="Minimum EV threshold (overrides config)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Number of top bets to display",
    )
    parser.add_argument(
        "--match",
        type=str,
        default=None,
        help="Filter to a specific match (substring of team names)",
    )
    parser.add_argument(
        "--performance",
        action="store_true",
        help="Show historical model performance summary",
    )
    args = parser.parse_args(argv)

    if args.performance:
        fb = FeedbackLoop()
        summary = fb.get_performance_summary()
        console.print(Panel(str(summary), title="Learning Loop Performance"))
        return 0

    settings = get_settings()
    if args.min_ev is not None:
        settings.min_ev_threshold = args.min_ev

    use_stake = args.stake or not args.demo

    console.print(
        Panel(
            "[bold]Value Betting Engine[/bold]\n"
            "Objective: maximize Expected Value, not prediction accuracy.\n"
            + (
                "[cyan]Mode: Stake.com live odds + bettor consensus + web sentiment[/cyan]"
                if use_stake
                else "Mode: Demo data"
            ),
            title="Bet Placer",
            border_style="green",
        )
    )

    if use_stake:
        return _run_stake_mode(args)
    return _run_demo_mode(args)


def _run_stake_mode(args) -> int:
    pipeline = StakeAnalysisPipeline()
    try:
        results = pipeline.run(
            sport=args.sport,
            match_filter=args.match,
            fixture_id=args.fixture_id,
        )
    except Exception as e:
        console.print(f"[red]Stake analysis failed: {e}[/red]")
        return 1

    if not results:
        console.print("[red]No Stake fixtures found for your filter.[/red]")
        return 1

    from_live = results[0].get("from_live_stake", False)
    if from_live:
        console.print("[green]✓ Live data from Stake.com GraphQL[/green]")
    else:
        console.print(
            "[yellow]⚠ Stake.com unreachable — using cached/sample data. "
            "Check network or VPN if you're geo-blocked.[/yellow]"
        )

    analyses = []
    for item in results:
        _print_stake_match_report(item)
        analyses.append(item["analysis"])

    global_top = rank_all_bets(analyses, top_n=args.top)
    if global_top:
        console.print()
        _print_top_bets_table(global_top, title=f"Top {args.top} Value Bets on Stake (All Matches)")

    return 0


def _run_demo_mode(args) -> int:
    collector = DemoCollector()
    matches = collector.fetch_matches()

    if args.match:
        needle = args.match.lower()
        matches = [
            m
            for m in matches
            if needle in m.home_team.lower() or needle in m.away_team.lower()
        ]

    if not matches:
        console.print("[red]No matches found.[/red]")
        return 1

    engine = ProbabilityEngine()
    results = [engine.analyze_match(m) for m in matches]

    for result in results:
        _print_match_analysis(result)

    global_top = rank_all_bets(results, top_n=args.top)
    if global_top:
        console.print()
        _print_top_bets_table(global_top, title=f"Top {args.top} Value Bets (All Matches)")

    return 0


def _print_stake_match_report(item: dict) -> None:
    fixture = item["fixture"]
    match = item["match"]
    analysis = item["analysis"]
    bettor = item["bettor_consensus"]
    web = item["web_consensus"]
    verdict = item["verdict"]

    console.print()
    style = VERDICT_STYLE.get(verdict.verdict, "white")
    console.print(Panel(
        Text(verdict.headline, style=style),
        subtitle=f"Consensus: {verdict.consensus_alignment} | "
        f"{verdict.value_bets_found} value bets / {verdict.stake_markets_scanned} Stake outcomes scanned",
        border_style="blue",
    ))

    console.print(
        f"[bold]{match.home_team}[/bold] vs [bold]{match.away_team}[/bold] | "
        f"{fixture.league} | Stake volume: ${fixture.total_bet_value:,.0f} "
        f"({fixture.total_user_count} users)"
    )

    # Verdict reasoning
    for line in verdict.reasoning[:6]:
        console.print(f"  • {line}")
    if verdict.risk_flags:
        console.print(f"  [dim]Risk flags: {', '.join(verdict.risk_flags)}[/dim]")

    # Bettor consensus table
    if bettor.pick_distribution:
        bt = Table(title="Stake Bettor Consensus (live feed)", show_header=True)
        bt.add_column("Side")
        bt.add_column("Volume %", justify="right")
        bt.add_column("Bets", justify="right")
        for side, pct in sorted(bettor.pick_distribution.items(), key=lambda x: -x[1]):
            bt.add_row(side, f"{pct:.0%}", str(bettor.pick_count_distribution.get(side, 0)))
        if bettor.highroller_side:
            bt.add_row(
                f"[bold]Highrollers[/bold]",
                f"→ {bettor.highroller_side}",
                f"${bettor.highroller_volume_usd:,.0f}",
            )
        console.print(bt)

    # Web consensus
    if web.source_count > 0:
        console.print(
            f"[dim]Web consensus ({web.source_count} sources): {web.dominant_narrative}[/dim]"
        )
        if web.fade_public:
            console.print("[yellow]  Public sentiment extreme — model may fade consensus[/yellow]")

    # All Stake markets scanned
    _print_stake_markets_table(fixture)

    if analysis.top_bets:
        _print_top_bets_table(
            analysis.top_bets,
            title=f"Value Bets on Stake — {match.home_team} vs {match.away_team}",
        )
    elif verdict.verdict == Verdict.SKIP:
        console.print("[dim]No individual bets recommended for this match.[/dim]")


def _print_stake_markets_table(fixture) -> None:
    table = Table(title=f"All Stake Markets — {fixture.name}", show_header=True)
    table.add_column("Market")
    table.add_column("Selection")
    table.add_column("Odds", justify="right")
    table.add_column("Implied", justify="right")

    from bet_placer.markets.odds import decimal_to_implied

    for market in fixture.markets:
        for oc in market.outcomes:
            table.add_row(
                market.name,
                oc.name,
                f"{oc.odds:.2f}",
                f"{decimal_to_implied(oc.odds):.1%}",
            )
    console.print(table)


def _print_match_analysis(result) -> None:
    match = result.match
    console.print()
    console.print(
        Panel(
            f"[bold]{match.home_team}[/bold] vs [bold]{match.away_team}[/bold]\n"
            f"{match.league} | {match.kickoff.strftime('%Y-%m-%d %H:%M')} | "
            f"Context: {match.context.value}",
            border_style="blue",
        )
    )

    if result.top_bets:
        _print_top_bets_table(result.top_bets, title=f"Top Value Bets — {match.home_team} vs {match.away_team}")
    else:
        console.print("[dim]No bets above EV threshold for this match.[/dim]")

    prob_table = Table(title="Probability Estimates", show_header=True)
    prob_table.add_column("Market", style="cyan")
    prob_table.add_column("Selection")
    prob_table.add_column("True Prob", justify="right")
    prob_table.add_column("Confidence", justify="right")
    prob_table.add_column("Intuition Adj", justify="right")

    for p in result.probabilities:
        prob_table.add_row(
            p.market.value,
            f"{p.selection}" + (f" {p.line}" if p.line else ""),
            f"{p.probability:.1%}",
            f"{p.confidence:.0%}",
            f"{p.intuition_adjustment:+.1%}" if p.intuition_adjustment else "—",
        )
    console.print(prob_table)


def _print_top_bets_table(bets, title: str) -> None:
    table = Table(title=title, show_header=True, expand=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("Match", min_width=20)
    table.add_column("Market", style="cyan")
    table.add_column("Odds", justify="right")
    table.add_column("True", justify="right")
    table.add_column("Implied", justify="right")
    table.add_column("EV", justify="right", style="green")
    table.add_column("Kelly%", justify="right")
    table.add_column("Conf", justify="right")

    for i, bet in enumerate(bets, 1):
        ev_style = "bold green" if bet.expected_value > 0.05 else "green"
        table.add_row(
            str(i),
            bet.match_label,
            _format_market(bet),
            f"{bet.decimal_odds:.2f}",
            f"{bet.true_probability:.1%}",
            f"{bet.implied_probability:.1%}",
            Text(f"{bet.expected_value:+.1%}", style=ev_style),
            f"{bet.kelly_stake_pct:.1f}%",
            f"{bet.confidence:.0%}",
        )

    console.print(table)

    for i, bet in enumerate(bets[:3], 1):
        console.print()
        console.print(
            Panel(
                bet.explanation,
                title=f"#{i} Why: {_format_market(bet)} @ {bet.decimal_odds:.2f}",
                border_style="yellow",
            )
        )


def _format_market(bet) -> str:
    line = f" {bet.line}" if bet.line else ""
    return f"{bet.market.value}: {bet.selection}{line}"


if __name__ == "__main__":
    sys.exit(main())

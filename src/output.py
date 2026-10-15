"""Format and write the final output CSVs."""

import csv
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pandas as pd

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from src.baselines import add_baselines
from src.flagging import find_candidates, load_params
from src.gate import gate_candidates
from src.load import load_shipments
from src.weekly import build_weekly_costs


SAMPLE_PATH = Path(__file__).parent.parent / "data" / "sample_output_format_v2.csv"
FLAGGED_PATH = Path(__file__).parent.parent / "outputs" / "flagged_routes.csv"
GRID_PATH = Path(__file__).parent.parent / "outputs" / "all_weeks_grid.csv"


def _format_cost(value: float) -> str:
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{d:.2f}"


def _format_pct(value: float) -> str:
    d = Decimal(str(value * 100.0)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    sign = "+" if d >= 0 else "-"
    return f"{sign}{abs(d):.1f}%"


def _format_vs_own_history(value: float) -> str:
    return f"{_format_pct(value)} vs this route's past average"


def _format_vs_similar_routes(value: float) -> str:
    return f"{_format_pct(value)} vs similar-length routes this week"


def format_flagged_output(gated: pd.DataFrame) -> pd.DataFrame:
    """Format the gated candidates to match the sample output contract."""
    df = gated.sort_values(["week_of", "route"]).copy()

    df["cost_per_tonne_km"] = df["cost_per_tonne_km"].apply(_format_cost)
    df["vs_own_history"] = df["vs_own_history"].apply(_format_vs_own_history)
    df["vs_similar_routes"] = df["vs_similar_routes"].apply(_format_vs_similar_routes)

    # Ensure blank for unexplained; gate already does this but make it explicit.
    df["matched_note_id"] = df["matched_note_id"].fillna("").astype(str)
    df.loc[df["flagged"] == "Yes", "matched_note_id"] = ""

    # Select and order columns exactly like the sample.
    output = df[
        [
            "route",
            "week_of",
            "cost_per_tonne_km",
            "vs_own_history",
            "vs_similar_routes",
            "flagged",
            "matched_note_id",
            "reason",
        ]
    ].copy()

    output["week_of"] = pd.to_datetime(output["week_of"]).dt.strftime("%Y-%m-%d")
    return output


def write_flagged_routes(output: pd.DataFrame, path: Path | str | None = None) -> None:
    """Write the main output CSV in the exact sample format."""
    if path is None:
        path = FLAGGED_PATH
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(
        path,
        index=False,
        encoding="utf-8",
        lineterminator="\n",
        quoting=csv.QUOTE_MINIMAL,
    )


def build_all_weeks_grid(weekly: pd.DataFrame) -> pd.DataFrame:
    """Build a grid of all 728 route-weeks with raw numeric values."""
    df = weekly.sort_values(["route", "week_of"]).copy()
    df["week_of"] = df["week_of"].dt.strftime("%Y-%m-%d")
    df = df.rename(
        columns={
            "pct_vs_history": "vs_own_history",
            "pct_vs_peers": "vs_similar_routes",
        }
    )
    return df[
        [
            "route",
            "week_of",
            "cost_per_tonne_km",
            "vs_own_history",
            "vs_similar_routes",
        ]
    ]


def write_all_weeks_grid(grid: pd.DataFrame, path: Path | str | None = None) -> None:
    if path is None:
        path = GRID_PATH
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    grid.to_csv(
        path,
        index=False,
        encoding="utf-8",
        lineterminator="\n",
        quoting=csv.QUOTE_MINIMAL,
        float_format="%.9f",
    )


def main() -> None:
    params = load_params()
    t_own = params["flagging"]["t_own"]

    shipments = load_shipments()
    weekly = add_baselines(build_weekly_costs(shipments))

    candidates = find_candidates(weekly, t_own=t_own)
    gated = gate_candidates(candidates)

    flagged_output = format_flagged_output(gated)
    write_flagged_routes(flagged_output)
    print(f"Wrote {len(flagged_output)} flagged rows to {FLAGGED_PATH}")

    grid = build_all_weeks_grid(weekly)
    write_all_weeks_grid(grid)
    print(f"Wrote {len(grid)} route-week rows to {GRID_PATH}")


if __name__ == "__main__":
    main()

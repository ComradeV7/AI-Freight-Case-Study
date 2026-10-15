import sys
from pathlib import Path

# Allow `python src/flagging.py` by adding the project root to PYTHONPATH.
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import yaml

from src.baselines import add_baselines
from src.load import load_shipments
from src.weekly import build_weekly_costs


CONFIG_PATH = Path(__file__).parent.parent / "config" / "params.yaml"
OUTPUT_PATH = Path(__file__).parent.parent / "outputs" / "sensitivity.csv"


def load_params(path: Path | str | None = None) -> dict:
    """Load flagging parameters from config/params.yaml."""
    if path is None:
        path = CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def find_candidates(
    df: pd.DataFrame,
    t_own: float,
    use_peers: bool = False,
    t_peer: float = 0.15,
) -> pd.DataFrame:
    """Return route-weeks that are rising and exceed the configured threshold(s)."""
    rising = df["pct_vs_history"] > 0
    history_trigger = df["pct_vs_history"] >= t_own

    if use_peers:
        peer_trigger = df["pct_vs_peers"] >= t_peer
        condition = rising & (history_trigger | peer_trigger)
    else:
        condition = rising & history_trigger

    return df[condition].copy()


def _candidate_key(row: pd.Series) -> str:
    return f"{row['route']} {row['week_of'].strftime('%Y-%m-%d')}"


def _candidate_set(df: pd.DataFrame) -> set[str]:
    return {_candidate_key(row) for _, row in df.iterrows()}


def build_sensitivity_report(base_candidates: pd.DataFrame, weekly: pd.DataFrame) -> pd.DataFrame:
    """Compare candidate sets across thresholds and the peer-or variant."""
    base_set = _candidate_set(base_candidates)

    variants = [
        {"name": "T_own=5%", "t_own": 0.05, "use_peers": False},
        {"name": "T_own=8%", "t_own": 0.08, "use_peers": False},
        {"name": "T_own=10%", "t_own": 0.10, "use_peers": False},
        {"name": "T_own=15%", "t_own": 0.15, "use_peers": False},
        {"name": "T_own=8% OR peer>=15%", "t_own": 0.08, "use_peers": True},
    ]

    rows = []
    for variant in variants:
        candidates = find_candidates(weekly, **{k: v for k, v in variant.items() if k != "name"})
        candidate_set = _candidate_set(candidates)

        added = sorted(candidate_set - base_set)
        removed = sorted(base_set - candidate_set)

        rows.append(
            {
                "variant": variant["name"],
                "candidate_count": len(candidates),
                "added_count": len(added),
                "removed_count": len(removed),
                "added_rows": "; ".join(added),
                "removed_rows": "; ".join(removed),
                "n_fewer_than_8_prior": int((candidates["n_prior_weeks"] < 8).sum()),
            }
        )

    return pd.DataFrame(rows)


def print_candidates(candidates: pd.DataFrame) -> None:
    """Pretty-print candidate rows."""
    display = candidates.sort_values(["route", "week_of"])[
        ["route", "week_of", "cost_per_tonne_km", "pct_vs_history", "pct_vs_peers", "n_prior_weeks"]
    ].copy()
    display["week_of"] = display["week_of"].dt.strftime("%Y-%m-%d")
    display["pct_vs_history"] = (display["pct_vs_history"] * 100).round(2).astype(str) + "%"
    display["pct_vs_peers"] = (display["pct_vs_peers"] * 100).round(2).astype(str) + "%"
    display["cost_per_tonne_km"] = display["cost_per_tonne_km"].round(2)
    print(f"\nCandidates at T_own=8% (n={len(display)}):\n")
    print(display.to_string(index=False))


def main() -> None:
    params = load_params()
    t_own = params["flagging"]["t_own"]

    shipments = load_shipments()
    weekly = build_weekly_costs(shipments)
    weekly = add_baselines(weekly)

    base_candidates = find_candidates(weekly, t_own=t_own)
    print_candidates(base_candidates)

    report = build_sensitivity_report(base_candidates, weekly)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(OUTPUT_PATH, index=False)
    print(f"\nSensitivity report written to {OUTPUT_PATH}")
    print(report.to_string(index=False))


if __name__ == "__main__":
    main()

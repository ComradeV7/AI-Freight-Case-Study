import pandas as pd


def build_weekly_costs(shipments: pd.DataFrame) -> pd.DataFrame:
    """Aggregate shipments to one row per route-week."""
    df = shipments.copy()
    df["tonne_km"] = df["quantity_tonnes"] * df["distance_km"]

    weekly = (
        df.groupby(["route", "route_type", "week_of"], as_index=False)
        .agg(
            total_cost=("freight_cost_inr", "sum"),
            total_tonne_km=("tonne_km", "sum"),
        )
    )

    weekly["cost_per_tonne_km"] = weekly["total_cost"] / weekly["total_tonne_km"]
    return weekly

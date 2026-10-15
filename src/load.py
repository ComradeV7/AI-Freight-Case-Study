import pandas as pd
from pathlib import Path


DATA_DIR = Path(__file__).parent.parent / "data"

REQUIRED_SHIPMENT_COLUMNS = {
    "shipment_id",
    "origin",
    "destination",
    "route_type",
    "material",
    "quantity_tonnes",
    "distance_km",
    "freight_cost_inr",
    "shipment_date",
}

REQUIRED_NOTE_COLUMNS = {"note_id", "date", "applies_to", "note"}


def load_shipments(path: Path | str | None = None) -> pd.DataFrame:
    """Load shipment records, build route, add week_of, and validate."""
    if path is None:
        path = DATA_DIR / "shipment_records.csv"

    df = pd.read_csv(path, parse_dates=["shipment_date"])

    df["route"] = df["origin"] + "-" + df["destination"]
    df["week_of"] = df["shipment_date"] - pd.to_timedelta(
        df["shipment_date"].dt.dayofweek, unit="D"
    )

    validate_shipments(df)
    return df


def load_notes(path: Path | str | None = None) -> pd.DataFrame:
    """Load context notes and validate their schema."""
    if path is None:
        path = DATA_DIR / "context_notes.csv"
    df = pd.read_csv(path, parse_dates=["date"])
    validate_notes(df)
    return df


def validate_notes(df: pd.DataFrame) -> None:
    """Schema/data-quality checks for the notes CSV (no hardcoded row counts)."""
    missing = REQUIRED_NOTE_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"notes CSV missing required columns: {sorted(missing)}")
    if df["note_id"].isnull().any():
        raise ValueError("notes CSV has null note_id values")
    if df["note_id"].duplicated().any():
        dups = df.loc[df["note_id"].duplicated(False), "note_id"].unique()
        raise ValueError(f"note_id is not unique; duplicates: {dups.tolist()}")


def validate_shipments(df: pd.DataFrame) -> None:
    """Run schema and data-quality checks and raise on failure.

    Only structural validity is asserted here; exact row counts belong to the
    test-suite (tests/test_load.py), never to the pipeline.
    """
    missing = REQUIRED_SHIPMENT_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"shipments CSV missing required columns: {sorted(missing)}")

    null_counts = df.isnull().sum()
    if null_counts.any():
        raise ValueError(f"Null values found:\n{null_counts[null_counts > 0]}")

    if not df["shipment_id"].is_unique:
        dups = df.loc[df["shipment_id"].duplicated(False), "shipment_id"].unique()
        raise ValueError(f"shipment_id is not unique; duplicates: {dups.tolist()}")

    for col in ["quantity_tonnes", "distance_km", "freight_cost_inr"]:
        if (df[col] <= 0).any():
            bad = df.loc[df[col] <= 0, col]
            raise ValueError(f"{col} has {len(bad)} non-positive value(s)")

    route_type_counts = df.groupby("route")["route_type"].nunique()
    inconsistent = route_type_counts[route_type_counts > 1]
    if not inconsistent.empty:
        raise ValueError(
            f"Routes with multiple route types: {inconsistent.index.tolist()}"
        )

    if not (df["week_of"].dt.dayofweek == 0).all():
        bad = df.loc[df["week_of"].dt.dayofweek != 0, "week_of"].unique()
        raise ValueError(f"week_of values that are not Monday: {bad.tolist()}")


def profile_data(df: pd.DataFrame) -> None:
    """Print a concise data profile."""
    print("=" * 50)
    print("Shipment data profile")
    print("=" * 50)
    print(f"Rows: {len(df)}")
    print(f"Columns: {list(df.columns)}")
    print(f"Routes ({df['route'].nunique()}): {sorted(df['route'].unique())}")
    print(
        "Routes by type: "
        f"{df.groupby('route_type')['route'].nunique().to_dict()}"
    )
    print(f"Distinct weeks: {df['week_of'].nunique()}")
    print(f"Shipment date range: {df['shipment_date'].min().date()} to {df['shipment_date'].max().date()}")
    print(f"Week-of range: {df['week_of'].min().date()} to {df['week_of'].max().date()}")
    print("=" * 50)


if __name__ == "__main__":
    shipments = load_shipments()
    notes = load_notes()
    profile_data(shipments)

import pytest
from src.load import load_shipments, load_notes


def test_shipments_row_count():
    df = load_shipments()
    assert len(df) == 2940


def test_route_count():
    df = load_shipments()
    assert df["route"].nunique() == 7


def test_week_count():
    df = load_shipments()
    assert df["week_of"].nunique() == 104


def test_every_route_present_every_week():
    df = load_shipments()
    route_weeks = df.groupby(["route", "week_of"]).size().reset_index()
    expected = df["route"].nunique() * df["week_of"].nunique()
    assert len(route_weeks) == expected


def test_route_type_counts():
    df = load_shipments()
    counts = df.groupby("route_type")["route"].nunique().to_dict()
    assert counts == {"Short": 2, "Medium": 3, "Long": 2}


def test_no_nulls():
    df = load_shipments()
    assert not df.isnull().any().any()


def test_shipment_id_unique():
    df = load_shipments()
    assert df["shipment_id"].is_unique


def test_positive_quantity_distance_cost():
    df = load_shipments()
    assert (df["quantity_tonnes"] > 0).all()
    assert (df["distance_km"] > 0).all()
    assert (df["freight_cost_inr"] > 0).all()


def test_each_route_has_one_route_type():
    df = load_shipments()
    assert (df.groupby("route")["route_type"].nunique() == 1).all()


def test_every_week_of_is_monday():
    df = load_shipments()
    assert (df["week_of"].dt.dayofweek == 0).all()


def test_notes_load():
    notes = load_notes()
    assert len(notes) == 10
    assert set(notes.columns) >= {"note_id", "date", "applies_to", "note"}

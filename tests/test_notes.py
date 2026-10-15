import pytest

from src.notes import load_notes_csv, load_notes_registry, validate_registry


def test_registry_has_all_csv_notes():
    registry = load_notes_registry()
    notes_csv = load_notes_csv()
    assert set(notes_csv["note_id"]) == set(registry.keys())


def test_validate_registry_passes():
    registry = load_notes_registry()
    notes_csv = load_notes_csv()
    validate_registry(registry, notes_csv)


def test_source_text_matches_csv():
    registry = load_notes_registry()
    notes_csv = load_notes_csv()
    for _, row in notes_csv.iterrows():
        assert registry[row["note_id"]]["source_text"] == row["note"]


def test_registry_values():
    registry = load_notes_registry()
    assert registry["N001"]["scope"] == ["Chennai-Bangalore"]
    assert registry["N001"]["effective_from"] == "2025-02-24"
    assert registry["N001"]["effective_to"] == "2025-03-08"
    assert registry["N001"]["polarity"] == "causes_rise"

    assert registry["N003"]["scope"] == "ALL"
    assert registry["N003"]["polarity"] == "causes_rise"

    assert registry["N004"]["polarity"] == "not_applicable"
    assert registry["N007"]["polarity"] == "informational"
    assert registry["N009"]["polarity"] == "informational"


def test_non_rise_notes_use_single_day_window():
    registry = load_notes_registry()
    notes_csv = load_notes_csv()
    for _, row in notes_csv.iterrows():
        note_id = row["note_id"]
        if registry[note_id]["polarity"] != "causes_rise":
            assert registry[note_id]["effective_from"] == row["date"]
            assert registry[note_id]["effective_to"] == row["date"]

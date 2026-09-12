from ingest import taxonomy
from tests.conftest import load_script


def test_cuisine_for_matches_alias_in_name():
    assert taxonomy.cuisine_for("Seoul Bulgogi House", []) == "korean"


def test_cuisine_for_falls_back_to_categories():
    assert taxonomy.cuisine_for("Joe's", ["thai_restaurant"]) == "thai"


def test_is_chain():
    assert taxonomy.is_chain("Starbucks Coffee")
    assert not taxonomy.is_chain("Blue Sparrow")


def test_is_chain_matches_hyphenated_name():
    assert taxonomy.is_chain("Chick-fil-A")


def test_taxonomy_references_resolve_to_defined_cuisines():
    cuisines = taxonomy.load()["cuisines"]
    keys = set(cuisines)
    dangling = [(cuisine, field, ref)
                for cuisine, spec in cuisines.items()
                for field in ("complementary", "substitutes")
                for ref in spec[field]
                if ref not in keys]
    assert dangling == []


def test_normalize_rows_marks_open_and_geocodes():
    w = load_script("03_wprdc_food")
    rows = [{"id": "1", "facility_name": "Seoul Bulgogi", "status": "1", "description": "Restaurant without Liquor",
             "x": "-79.99", "y": "40.44", "address": "x", "bus_cl_date": None},
            {"id": "2", "facility_name": "Closed Diner", "status": "0", "description": "Restaurant",
             "x": "-79.99", "y": "40.44", "address": "y", "bus_cl_date": "2020-01-01"},
            {"id": "3", "facility_name": "No Geo", "status": "1", "description": "Restaurant",
             "x": "", "y": "", "address": "z", "bus_cl_date": None}]
    df = w.normalize_rows(rows)
    assert len(df) == 2
    assert df.loc[df.provider_id == "1", "is_open"].item() is True
    assert df.loc[df.provider_id == "2", "is_open"].item() is False
    assert df.loc[df.provider_id == "1", "cuisine_key"].item() == "korean"

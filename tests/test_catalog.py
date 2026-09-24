import logging
import os
import sqlite3
import sys
import tempfile
import unittest
from dataclasses import asdict, fields
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import catalog
from catalog import (
    Catalog,
    budget_band,
    build_catalog,
    catalog_path,
    nearest_rank,
    parse_cost,
    parse_cuisines,
    parse_rating,
    parse_yes_no,
    repair_name,
)
from models import Restaurant


def row(**overrides):
    base = {
        "url": "https://www.zomato.com/bangalore/jalsa?context=abc",
        "address": "942 Main Road",
        "name": "Jalsa",
        "online_order": "Yes",
        "book_table": "No",
        "rate": "4.1/5",
        "votes": "775",
        "location": "Banashankari",
        "rest_type": "Casual Dining",
        "dish_liked": "Pasta",
        "cuisines": "North Indian, Mughlai",
        "approx_cost(for two people)": "800",
        "listed_in(type)": "Buffet",
        "listed_in(city)": "Banashankari",
        "phone": "080 000000",
        "reviews_list": "secret review text",
        "menu_item": "secret menu text",
    }
    base.update(overrides)
    return base


class ParserTests(unittest.TestCase):
    def test_rating_accepts_canonical_form(self):
        self.assertEqual(parse_rating("4.1/5"), 4.1)
        self.assertEqual(parse_rating("4/5"), 4.0)
        self.assertEqual(parse_rating("5/5"), 5.0)
        self.assertEqual(parse_rating("0/5"), 0.0)
        self.assertEqual(parse_rating("  4.1/5  "), 4.1)

    def test_rating_rejects_unusable_values(self):
        for value in ("NEW", "new", "-", "", None, "4.1", "4.1/10", "4.10/5", "10/5", "-1/5", "4.1 /5", "4.1/ 5", "4.1 / 5"):
            self.assertIsNone(parse_rating(value), value)

    def test_cost_parses_digits_and_drops_empty(self):
        self.assertEqual(parse_cost("800"), 800)
        self.assertEqual(parse_cost("1,200"), 1200)
        self.assertEqual(parse_cost("₹800"), 800)
        self.assertEqual(parse_cost("800 for two"), 800)
        self.assertEqual(parse_cost("0"), 0)
        for value in ("", None, "-", "?"):
            self.assertIsNone(parse_cost(value), value)

    def test_cuisines_split_trim_and_drop_empty_tokens(self):
        self.assertEqual(parse_cuisines("North Indian, Mughlai, Chinese"), ["North Indian", "Mughlai", "Chinese"])
        self.assertEqual(parse_cuisines("Italian,"), ["Italian"])
        self.assertEqual(parse_cuisines(" Italian "), ["Italian"])
        self.assertEqual(parse_cuisines("Italian,,Chinese"), ["Italian", "Chinese"])
        self.assertEqual(parse_cuisines("Cafe, Cafe"), ["Cafe"])
        self.assertEqual(parse_cuisines(None), [])
        self.assertEqual(parse_cuisines(""), [])

    def test_yes_no_is_case_insensitive(self):
        self.assertTrue(parse_yes_no("Yes"))
        self.assertTrue(parse_yes_no("yes"))
        self.assertFalse(parse_yes_no("No"))
        self.assertFalse(parse_yes_no(None))
        self.assertFalse(parse_yes_no("maybe"))

    def test_name_repairs_only_a_straight_utf8_decode(self):
        self.assertEqual(repair_name("CafÃ©"), "Café")
        self.assertEqual(repair_name("Jalsa"), "Jalsa")
        self.assertEqual(repair_name("still garbled \u20ac"), "still garbled \u20ac")


class CatalogBuildTests(unittest.TestCase):
    def test_drops_rows_without_usable_rating_cost_or_name(self):
        records, _, _, _ = build_catalog([
            row(name="   "),
            row(url="https://example.com/a", rate="NEW"),
            row(url="https://example.com/b", rate="4.1 /5"),
            row(url="https://example.com/c", **{"approx_cost(for two people)": "?"}),
            row(url="https://example.com/d", rate="4/5", **{"approx_cost(for two people)": "0"}),
        ])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].rating, 4.0)
        self.assertEqual(records[0].cost_for_two, 0)

    def test_dedup_keeps_higher_votes_then_rating_then_earliest(self):
        records, _, _, _ = build_catalog([
            row(name="Early", votes="40", rate="4.2/5"),
            row(name="More votes", votes="100", rate="3.9/5"),
            row(url="https://example.com/tie", name="Lower", votes="10", rate="3.9/5"),
            row(url="https://example.com/tie", name="Higher rating", votes="10", rate="4.2/5"),
            row(url="https://example.com/same", name="First", votes="8", rate="4.0/5"),
            row(url="https://example.com/same?other=1", name="Later", votes="8", rate="4.0/5"),
        ])
        by_name = {record.name: record for record in records}
        self.assertEqual(set(by_name), {"More votes", "Higher rating", "First"})
        self.assertEqual(by_name["More votes"].votes, 100)

    def test_same_name_different_paths_are_kept(self):
        records, _, _, _ = build_catalog([
            row(url="https://example.com/one", location="BTM"),
            row(url="https://example.com/two", location="HSR"),
        ])
        self.assertEqual(len(records), 2)
        self.assertEqual({record.location for record in records}, {"BTM", "HSR"})

    def test_missing_url_dedupes_on_normalized_name_and_location(self):
        records, _, _, _ = build_catalog([
            row(url="", name="Cafe", location="HSR", votes="3"),
            row(url=None, name="  cafe  ", location="hsr", votes="9"),
        ])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].votes, 9)

    def test_comma_location_is_not_split(self):
        records, meta, _, _ = build_catalog([
            row(url="https://example.com/itpl", location="ITPL Main Road, Whitefield"),
        ])
        self.assertEqual(records[0].location, "ITPL Main Road, Whitefield")
        self.assertEqual(meta["locations"], ["ITPL Main Road, Whitefield"])

    def test_forbidden_fields_never_land_on_a_record(self):
        records, _, _, _ = build_catalog([row()])
        payload = asdict(records[0])
        self.assertEqual(
            [field.name for field in fields(Restaurant)],
            [
                "id", "name", "location", "area", "cuisines", "rating", "votes",
                "cost_for_two", "rest_type", "listed_in_type", "online_order",
                "book_table", "dish_liked",
            ],
        )
        blob = str(payload)
        for secret in ("secret review text", "secret menu text", "080 000000", "942 Main Road"):
            self.assertNotIn(secret, blob)
        for key in ("phone", "address", "reviews_list", "menu_item"):
            self.assertNotIn(key, payload)

    def test_empty_cuisines_and_flags_do_not_drop_the_row(self):
        records, _, _, _ = build_catalog([
            row(
                cuisines="",
                online_order="maybe",
                book_table=None,
                rest_type=None,
                dish_liked=None,
                **{"listed_in(type)": "Something Else"},
            ),
        ])
        self.assertEqual(records[0].cuisines, [])
        self.assertFalse(records[0].online_order)
        self.assertFalse(records[0].book_table)
        self.assertEqual(records[0].rest_type, "")
        self.assertIsNone(records[0].dish_liked)
        self.assertEqual(records[0].listed_in_type, "Something Else")

    def test_budget_edges_use_nearest_rank(self):
        costs = [100, 200, 300, 400, 500, 600]
        self.assertEqual(nearest_rank(costs, 33), 200)
        self.assertEqual(nearest_rank(costs, 66), 400)
        records, meta, p33, p66 = build_catalog([
            row(url=f"https://example.com/{cost}", **{"approx_cost(for two people)": str(cost)})
            for cost in costs
        ])
        built = Catalog()
        built.load(reader=lambda: [
            row(url=f"https://example.com/{cost}", **{"approx_cost(for two people)": str(cost)})
            for cost in costs
        ])
        self.assertEqual((p33, p66), (200, 400))
        self.assertEqual(built.band_for(200), "low")
        self.assertEqual(budget_band(201, p33, p66), "medium")
        self.assertEqual(built.band_for(400), "medium")
        self.assertEqual(budget_band(401, p33, p66), "high")
        labels = [band["label"] for band in meta["budget_bands"]]
        self.assertEqual(labels, [
            "Low (up to ₹200 for two)",
            "Medium (above ₹200 up to ₹400 for two)",
            "High (above ₹400 for two)",
        ])
        self.assertNotIn(",", labels[0])
        self.assertEqual(len(records), 6)

    def test_equal_costs_put_every_restaurant_in_low(self):
        built = Catalog()
        built.load(reader=lambda: [
            row(url=f"https://example.com/{index}", **{"approx_cost(for two people)": "500"})
            for index in range(3)
        ])
        meta = built.get_meta()
        self.assertEqual(meta["p33"], meta["p66"])
        self.assertTrue(all(built.band_for(record.cost_for_two) == "low" for record in built.get_restaurants()))

    def test_one_restaurant_is_low(self):
        records, _, p33, p66 = build_catalog([row()])
        self.assertEqual(len(records), 1)
        self.assertEqual(budget_band(records[0].cost_for_two, p33, p66), "low")

    def test_zero_restaurants_is_a_ready_empty_catalog(self):
        built = Catalog()
        built.load(reader=lambda: [row(rate="NEW")])
        self.assertTrue(built.is_ready())
        self.assertEqual(built.get_restaurants(), ())
        meta = built.get_meta()
        self.assertEqual(meta["locations"], [])
        self.assertEqual(meta["cuisines"], [])
        self.assertIsNone(meta["p33"])

    def test_location_meta_collapses_case_and_keeps_the_most_frequent_spelling(self):
        _, meta, _, _ = build_catalog([
            row(url="https://example.com/1", location=" Banashankari "),
            row(url="https://example.com/2", location="Banashankari"),
            row(url="https://example.com/3", location="banashankari"),
        ])
        self.assertEqual(meta["locations"], ["Banashankari"])

    def test_any_cuisine_token_is_removed_from_the_index(self):
        with self.assertLogs("catalog", level=logging.WARNING) as logs:
            _, meta, _, _ = build_catalog([row(cuisines="Italian, Any, Cafe")])
        self.assertEqual(meta["cuisines"], ["Cafe", "Italian"])
        self.assertTrue(any("Any" in message for message in logs.output))

    def test_second_load_is_a_no_op(self):
        calls = {"count": 0}

        def reader():
            calls["count"] += 1
            return [row()]

        built = Catalog()
        built.load(reader=reader)
        built.load(reader=reader)
        self.assertEqual(calls["count"], 1)
        self.assertEqual(len(built.get_restaurants()), 1)

    def test_unreachable_source_sets_failed_and_does_not_raise(self):
        def reader():
            raise RuntimeError("offline")

        built = Catalog()
        with self.assertLogs("catalog", level=logging.ERROR):
            built.load(reader=reader)
        self.assertEqual(built.status(), "failed")
        self.assertFalse(built.is_ready())
        with self.assertRaises(RuntimeError):
            built.get_restaurants()
        with self.assertRaises(RuntimeError):
            built.get_meta()

    def test_import_does_not_fetch_or_mark_ready(self):
        self.assertEqual(catalog.status(), "loading")
        self.assertFalse(catalog.is_ready())

    def test_catalog_path_defaults_to_the_sqlite_file(self):
        previous = os.environ.pop("CATALOG_PATH", None)
        try:
            self.assertEqual(catalog_path().name, "catalog.sqlite")
            self.assertEqual(catalog_path().parent.name, "data")
        finally:
            if previous is not None:
                os.environ["CATALOG_PATH"] = previous

    def test_load_reads_catalog_path_and_missing_file_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "catalog.sqlite")
            connection = sqlite3.connect(path)
            connection.executescript(
                """
                CREATE TABLE restaurants (
                    id TEXT PRIMARY KEY, name TEXT, location TEXT, area TEXT,
                    rating REAL, votes INTEGER, cost_for_two INTEGER,
                    rest_type TEXT, listed_in_type TEXT,
                    online_order INTEGER, book_table INTEGER, dish_liked TEXT
                );
                CREATE TABLE restaurant_cuisines (
                    restaurant_id TEXT, position INTEGER, cuisine TEXT
                );
                """
            )
            connection.execute(
                "INSERT INTO restaurants VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("abc", "Jalsa", "Banashankari", "Banashankari", 4.1, 10, 300, "Casual Dining", "Dine-out", 1, 0, None),
            )
            connection.execute(
                "INSERT INTO restaurant_cuisines VALUES (?, ?, ?)",
                ("abc", 0, "Italian"),
            )
            connection.commit()
            connection.close()

            previous = os.environ.get("CATALOG_PATH")
            os.environ["CATALOG_PATH"] = path
            try:
                built = Catalog()
                built.load()
                record = built.get_restaurants()[0]
                self.assertEqual(record.name, "Jalsa")
                self.assertEqual(record.cuisines, ["Italian"])
                self.assertNotIn("phone", record.__dict__)

                os.environ["CATALOG_PATH"] = os.path.join(directory, "missing.sqlite")
                missing = Catalog()
                with self.assertLogs("catalog", level=logging.ERROR):
                    missing.load()
                self.assertEqual(missing.status(), "failed")
            finally:
                if previous is None:
                    os.environ.pop("CATALOG_PATH", None)
                else:
                    os.environ["CATALOG_PATH"] = previous


if __name__ == "__main__":
    unittest.main()

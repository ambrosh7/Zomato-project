import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from filter import FilterError, filter_preferences
from models import Preferences, Restaurant


def restaurant(**overrides) -> Restaurant:
    values = {
        "id": "a",
        "name": "Jalsa",
        "location": "Banashankari",
        "area": "Banashankari",
        "cuisines": ["Cafe", "Mexican", "Italian"],
        "rating": 4.1,
        "votes": 100,
        "cost_for_two": 300,
        "rest_type": "Casual Dining",
        "listed_in_type": "Dine-out",
        "online_order": True,
        "book_table": False,
        "dish_liked": "Pasta",
    }
    values.update(overrides)
    return Restaurant(**values)


def preferences(**overrides) -> Preferences:
    values = {
        "location": "Banashankari",
        "budget": "medium",
        "cuisine": "Italian",
        "min_rating": 3.5,
        "additional": None,
    }
    values.update(overrides)
    return Preferences(**values)


class FilterTests(unittest.TestCase):
    def test_same_input_returns_the_same_ids(self):
        records = [
            restaurant(id="b", rating=4.2, votes=40, cost_for_two=250),
            restaurant(id="a", rating=4.0, votes=400, cost_for_two=400),
        ]
        first = [item.id for item in filter_preferences(preferences(), records, p33=200, p66=400)]
        second = [item.id for item in filter_preferences(preferences(), records, p33=200, p66=400)]
        self.assertEqual(first, second)
        self.assertEqual(first, ["a", "b"])

    def test_high_votes_outrank_a_thin_high_rating(self):
        records = [
            restaurant(id="thin", rating=4.9, votes=3, cost_for_two=300),
            restaurant(id="proven", rating=4.3, votes=5000, cost_for_two=300),
        ]
        ranked = filter_preferences(preferences(cuisine="Any"), records, p33=200, p66=400)
        self.assertEqual([item.id for item in ranked], ["proven", "thin"])

    def test_any_cuisine_does_not_drop_rows(self):
        records = [
            restaurant(id="plain", cuisines=[]),
            restaurant(id="thai", cuisines=["Thai"]),
        ]
        ranked = filter_preferences(preferences(cuisine=" any "), records, p33=200, p66=400)
        self.assertEqual([item.id for item in ranked], ["plain", "thai"])

    def test_cuisine_token_equality_is_not_a_substring(self):
        records = [
            restaurant(id="match", cuisines=["Cafe", "Mexican", "Italian"]),
            restaurant(id="thai", cuisines=["Thai"]),
            restaurant(id="thali", cuisines=["Thali"]),
            restaurant(id="north", cuisines=["North Indian"]),
            restaurant(id="indian", cuisines=["Indian"]),
        ]
        italian = filter_preferences(preferences(cuisine="italian"), records, p33=200, p66=400)
        thai = filter_preferences(preferences(cuisine="Thai"), records, p33=200, p66=400)
        indian = filter_preferences(preferences(cuisine="Indian"), records, p33=200, p66=400)
        self.assertEqual([item.id for item in italian], ["match"])
        self.assertEqual([item.id for item in thai], ["thai"])
        self.assertEqual([item.id for item in indian], ["indian"])
        with self.assertRaises(FilterError) as unknown:
            filter_preferences(preferences(cuisine="Sushi"), records, p33=200, p66=400)
        self.assertEqual(unknown.exception.field, "cuisine")

    def test_empty_result_is_distinct_from_unknown_location(self):
        records = [restaurant(rating=4.0)]
        self.assertEqual(filter_preferences(preferences(min_rating=5.0), records, p33=200, p66=400), [])
        for city in ("Delhi", "Bangalore", "Bengaluru", "Indira Nagar"):
            with self.assertRaises(FilterError) as error:
                filter_preferences(preferences(location=city), records, p33=200, p66=400)
            self.assertEqual(error.exception.field, "location")

    def test_additional_text_does_not_change_the_candidate_set(self):
        records = [restaurant(id="only")]
        without = filter_preferences(preferences(), records, p33=200, p66=400)
        with_text = filter_preferences(
            preferences(additional="family-friendly, cheapest, " + ("x" * 250)),
            records,
            p33=200,
            p66=400,
        )
        self.assertEqual([item.id for item in without], [item.id for item in with_text])
        self.assertEqual(len(with_text[0].__dict__), len(restaurant().__dict__))

    def test_budget_boundaries_and_case(self):
        records = [
            restaurant(id="edge", cost_for_two=200),
            restaurant(id="mid", cost_for_two=400),
            restaurant(id="high", cost_for_two=401),
        ]
        low = filter_preferences(preferences(budget="Low", cuisine="Any"), records, p33=200, p66=400)
        medium = filter_preferences(preferences(budget="MEDIUM", cuisine="Any"), records, p33=200, p66=400)
        high = filter_preferences(preferences(budget="high", cuisine="Any"), records, p33=200, p66=400)
        self.assertEqual([item.id for item in low], ["edge"])
        self.assertEqual([item.id for item in medium], ["mid"])
        self.assertEqual([item.id for item in high], ["high"])

    def test_comma_location_is_one_known_name(self):
        records = [restaurant(id="itpl", location="ITPL Main Road, Whitefield", area="Whitefield")]
        found = filter_preferences(
            preferences(location="  ITPL   Main Road, Whitefield  ", cuisine="Any"),
            records,
            p33=200,
            p66=400,
        )
        self.assertEqual([item.id for item in found], ["itpl"])
        with self.assertRaises(FilterError):
            filter_preferences(preferences(location="ITPL Main Road", cuisine="Any"), records, p33=200, p66=400)

    def test_neighborhood_match_wins_over_area(self):
        records = [
            restaurant(id="neighborhood", location="Whitefield", area="East"),
            restaurant(id="broader", location="Marathahalli", area="Whitefield"),
        ]
        found = filter_preferences(preferences(location="Whitefield", cuisine="Any"), records, p33=200, p66=400)
        self.assertEqual([item.id for item in found], ["neighborhood"])

    def test_area_match_when_value_is_not_a_neighborhood(self):
        records = [
            restaurant(id="one", location="Indiranagar", area="East Bangalore"),
            restaurant(id="two", location="Koramangala", area="East Bangalore"),
            restaurant(id="other", location="Banashankari", area="South Bangalore"),
        ]
        found = filter_preferences(preferences(location="East Bangalore", cuisine="Any"), records, p33=200, p66=400)
        self.assertEqual([item.id for item in found], ["one", "two"])

    def test_city_name_is_unknown_even_if_it_is_an_area(self):
        records = [restaurant(location="Indiranagar", area="Bangalore")]
        with self.assertRaises(FilterError) as error:
            filter_preferences(preferences(location="Bangalore", cuisine="Any"), records, p33=200, p66=400)
        self.assertEqual(error.exception.field, "location")

    def test_blank_location_and_overlong_additional_are_validation_errors(self):
        records = [restaurant()]
        with self.assertRaises(FilterError) as blank:
            filter_preferences(preferences(location="   "), records, p33=200, p66=400)
        self.assertEqual(blank.exception.field, "location")
        with self.assertRaises(FilterError) as extra:
            filter_preferences(preferences(additional="x" * 281), records, p33=200, p66=400)
        self.assertEqual(extra.exception.field, "additional")
        kept = filter_preferences(preferences(additional="x" * 280, cuisine="Any"), records, p33=200, p66=400)
        self.assertEqual(len(kept), 1)

    def test_equal_rating_is_kept_and_zero_votes_can_survive(self):
        records = [
            restaurant(id="equal", rating=3.5, votes=0),
            restaurant(id="below", rating=3.4, votes=100),
            restaurant(id="negative", rating=3.5, votes=-4),
        ]
        found = filter_preferences(preferences(cuisine="Any", min_rating=3.5), records, p33=200, p66=400)
        self.assertEqual([item.id for item in found], ["equal", "negative"])

    def test_twenty_first_row_is_dropped_on_an_id_tie(self):
        records = [
            restaurant(id=f"{index:02d}", rating=4.0, votes=10, cost_for_two=300)
            for index in range(21)
        ]
        found = filter_preferences(preferences(cuisine="Any"), records, p33=200, p66=400)
        self.assertEqual([item.id for item in found], [f"{index:02d}" for index in range(20)])

    def test_unusable_row_is_dropped_without_widening(self):
        records = [
            restaurant(id="blank", name="  "),
            restaurant(id="kept"),
        ]
        found = filter_preferences(preferences(), records, p33=200, p66=400)
        self.assertEqual([item.id for item in found], ["kept"])


if __name__ == "__main__":
    unittest.main()

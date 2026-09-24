import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient

from api import create_app
from models import Recommendation, Restaurant
from ranker import RankResult


def restaurant(**overrides) -> Restaurant:
    values = {
        "id": "keep",
        "name": "Onesta",
        "location": "Banashankari",
        "area": "Banashankari",
        "cuisines": ["Pizza", "Cafe", "Italian"],
        "rating": 4.6,
        "votes": 2556,
        "cost_for_two": 400,
        "rest_type": "Casual Dining",
        "listed_in_type": "Dine-out",
        "online_order": True,
        "book_table": False,
        "dish_liked": "Pasta",
    }
    values.update(overrides)
    return Restaurant(**values)


class FakeServices:
    def __init__(self, status="ready", records=None) -> None:
        self._status = status
        self._records = tuple(records or [restaurant()])
        self.calls = 0
        self.rank_error = None
        self.ranked = None
        self.loads = 0

    def status(self) -> str:
        return self._status

    def meta(self) -> dict:
        return {
            "locations": ["Banashankari"],
            "cuisines": ["Italian"],
            "p33": 300,
            "p66": 500,
            "budget_bands": [
                {"id": "low", "label": "Low (up to ₹300 for two)"},
                {"id": "medium", "label": "Medium (above ₹300 up to ₹500 for two)"},
                {"id": "high", "label": "High (above ₹500 for two)"},
            ],
        }

    def restaurants(self):
        return self._records

    def rank(self, preferences, candidates, p33, p66):
        self.calls += 1
        if self.rank_error is not None:
            raise self.rank_error
        if self.ranked is not None:
            return self.ranked
        record = candidates[0]
        return RankResult(
            "llm",
            "A short list.",
            [
                Recommendation(
                    rank=1,
                    name=record.name,
                    cuisines=["Changed"],
                    rating=1.0,
                    votes=1,
                    estimated_cost=1,
                    cost_label="₹1 for two",
                    location="Delhi",
                    explanation="Fits Italian.",
                    id=record.id,
                )
            ],
        )

    def load(self) -> None:
        self.loads += 1


def client(services: FakeServices) -> TestClient:
    return TestClient(create_app(services, load_on_startup=False))


def body(**overrides):
    payload = {
        "location": "Banashankari",
        "budget": "medium",
        "cuisine": "Italian",
        "min_rating": 3.5,
    }
    payload.update(overrides)
    return payload


class ApiTests(unittest.TestCase):
    def test_unknown_location_including_delhi_is_400(self):
        api = client(FakeServices())
        for location in ("Delhi", "Bangalore", "Nowhere"):
            response = api.post("/api/recommendations", json=body(location=location))
            self.assertEqual(response.status_code, 400, location)
            self.assertEqual(response.json()["field"], "location")
            self.assertNotIn("no_matches", response.text)

    def test_catalog_not_ready_is_503_and_health_reports_status(self):
        for status in ("loading", "failed"):
            services = FakeServices(status=status)
            api = client(services)
            self.assertEqual(api.get("/health").json(), {"status": status})
            self.assertEqual(api.get("/api/meta").status_code, 503)
            response = api.post("/api/recommendations", json=body())
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["status"], status)
            self.assertEqual(services.calls, 0)

    def test_empty_filter_does_not_call_the_ranker(self):
        services = FakeServices()
        api = client(services)
        response = api.post("/api/recommendations", json=body(min_rating=5))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "no_matches",
                "message": "No restaurants matched these filters.",
                "suggestions": [
                    "Lower the minimum rating",
                    "Choose Any cuisine",
                    "Widen the budget",
                ],
            },
        )
        self.assertEqual(services.calls, 0)

    def test_success_uses_catalog_facts_when_ranker_changes_numbers(self):
        services = FakeServices()
        response = client(services).post("/api/recommendations", json=body(budget="Medium", min_rating="3.5"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["source"], "llm")
        self.assertEqual(len(payload["results"]), 1)
        card = payload["results"][0]
        self.assertEqual(card["rating"], 4.6)
        self.assertEqual(card["votes"], 2556)
        self.assertEqual(card["estimated_cost"], 400)
        self.assertEqual(card["cost_label"], "₹400 for two")
        self.assertEqual(card["location"], "Banashankari")
        self.assertEqual(card["name"], "Onesta")
        self.assertEqual(card["explanation"], "Fits Italian.")
        self.assertNotIn("id", card)

    def test_ranker_failure_is_fallback_with_catalog_facts(self):
        services = FakeServices()
        services.rank_error = RuntimeError("model down")
        response = client(services).post("/api/recommendations", json=body())
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["source"], "fallback")
        self.assertEqual(payload["results"][0]["rating"], 4.6)
        self.assertEqual(payload["results"][0]["cost_label"], "₹400 for two")
        self.assertNotIn("explanation", payload["results"][0])

    def test_cost_label_has_no_thousands_separator(self):
        services = FakeServices(records=[restaurant(cost_for_two=1200)])
        response = client(services).post("/api/recommendations", json=body(budget="high"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["cost_label"], "₹1200 for two")

    def test_invalid_fields_name_the_field(self):
        api = client(FakeServices())
        cases = [
            (body(cuisine="Sushi"), "cuisine"),
            (body(budget="cheap"), "budget"),
            (body(min_rating=5.5), "min_rating"),
            (body(min_rating=-0.1), "min_rating"),
            (body(additional="x" * 281), "additional"),
            ({"budget": "medium", "cuisine": "Italian", "min_rating": 3.5}, "location"),
        ]
        for payload, field in cases:
            response = api.post("/api/recommendations", json=payload)
            self.assertEqual(response.status_code, 400, field)
            self.assertEqual(response.json()["field"], field)
        raw = api.post("/api/recommendations", content="not-json", headers={"Content-Type": "application/json"})
        self.assertEqual(raw.status_code, 400)
        self.assertEqual(api.get("/api/recommendations").status_code, 405)

    def test_recommendations_do_not_start_another_load(self):
        services = FakeServices(status="loading")
        api = client(services)
        api.post("/api/recommendations", json=body())
        self.assertEqual(services.loads, 0)


if __name__ == "__main__":
    unittest.main()

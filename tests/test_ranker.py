import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from models import Preferences, Restaurant
from prompt import SYSTEM_INSTRUCTION, build_prompt, candidate_payload
from ranker import (
    COMPLETION_CAP,
    GPT_OSS_LIMITS,
    MIN_COMPLETION,
    GroqSettings,
    Ranker,
    RankerError,
    RetryableRankerError,
    UsageLimiter,
    estimate_prompt_tokens,
)


def restaurant(**overrides) -> Restaurant:
    values = {
        "id": "catalog-a",
        "name": "Onesta",
        "location": "Banashankari",
        "area": "Banashankari",
        "cuisines": ["Pizza", "Cafe", "Italian"],
        "rating": 4.1,
        "votes": 2556,
        "cost_for_two": 600,
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
        "additional": "quick service",
    }
    values.update(overrides)
    return Preferences(**values)


def payload_keys(value) -> set[str]:
    found = set()
    if isinstance(value, dict):
        found.update(value)
        for item in value.values():
            found.update(payload_keys(item))
    elif isinstance(value, list):
        for item in value:
            found.update(payload_keys(item))
    return found


class PromptTests(unittest.TestCase):
    def test_prompt_json_excludes_forbidden_fields(self):
        record = restaurant(
            id="secret",
            dish_liked="0123456789" * 12,
        )
        record.__dict__["phone"] = "080000000"
        record.__dict__["url"] = "https://example.invalid/place"
        record.__dict__["address"] = "1 Main Road"
        record.__dict__["reviews"] = "great"
        record.__dict__["menu"] = "pasta"
        prompt = build_prompt(preferences(), [record], p33=300, p66=500)
        body = json.loads(prompt.user)
        keys = payload_keys(body["candidates"])
        self.assertEqual(
            keys,
            {
                "id",
                "name",
                "location",
                "cuisines",
                "rating",
                "votes",
                "cost_for_two",
                "rest_type",
                "listed_in_type",
                "online_order",
                "book_table",
                "dish_liked",
            },
        )
        self.assertTrue({"phone", "url", "address", "reviews", "menu", "reviews_list", "menu_item"}.isdisjoint(payload_keys(body)))
        self.assertIn("JSON only", SYSTEM_INSTRUCTION)
        self.assertIn("family-friendly", SYSTEM_INSTRUCTION)
        self.assertIn("at most 5", SYSTEM_INSTRUCTION)
        self.assertIn("provided JSON only", SYSTEM_INSTRUCTION)

    def test_dish_liked_truncates_on_a_character_boundary(self):
        exact = "é" * 120
        longer = exact + "🍕"
        self.assertEqual(candidate_payload(restaurant(dish_liked=exact))["dish_liked"], exact)
        truncated = candidate_payload(restaurant(dish_liked=longer))["dish_liked"]
        self.assertEqual(len(truncated), 120)
        self.assertEqual(truncated, exact)
        self.assertFalse(truncated.endswith("🍕"))


class RankerTests(unittest.TestCase):
    def test_invented_id_is_dropped_and_catalog_facts_win(self):
        records = [
            restaurant(id="keep", name="Onesta", rating=4.1, cost_for_two=600),
            restaurant(id="also", name="Other", rating=4.4, cost_for_two=1200),
        ]

        def complete(_prompt):
            return json.dumps({
                "summary": "  A short list.  ",
                "recommendations": [
                    {"id": "invented", "rank": 1, "explanation": "Not in the catalog.", "rating": 9.9, "estimated_cost": 1},
                    {"id": "keep", "rank": 2, "explanation": "Fits Italian.", "rating": 1.0, "cost_for_two": 10, "name": "Fake"},
                ],
            })

        result = Ranker(complete).rank(preferences(), records, p33=300, p66=500)
        self.assertEqual(result.source, "llm")
        self.assertEqual(result.summary, "A short list.")
        self.assertEqual(len(result.results), 1)
        card = result.results[0]
        self.assertEqual(card.name, "Onesta")
        self.assertEqual(card.rating, 4.1)
        self.assertEqual(card.estimated_cost, 600)
        self.assertEqual(card.cost_label, "₹600 for two")
        self.assertEqual(card.location, "Banashankari")
        self.assertEqual(card.explanation, "Fits Italian.")

    def test_all_invented_ids_use_filter_order(self):
        records = [restaurant(id="real", name="Onesta")]

        def complete(_prompt):
            return json.dumps({
                "summary": "Invented.",
                "recommendations": [{"id": "not-real", "rank": 1, "explanation": "No."}],
            })

        result = Ranker(complete).rank(preferences(), records, p33=300, p66=500)
        self.assertEqual(result.source, "fallback")
        self.assertIsNone(result.summary)
        self.assertEqual(result.results[0].name, "Onesta")
        self.assertIsNone(result.results[0].explanation)

    def test_invalid_json_and_timeout_use_filter_order(self):
        records = [restaurant(id="a", name="First"), restaurant(id="b", name="Second", votes=10)]
        fenced = Ranker(lambda _prompt: "```json\n{\"summary\": null, \"recommendations\": []}\n```")
        fenced_result = fenced.rank(preferences(), records, p33=300, p66=500)
        self.assertEqual(fenced_result.source, "fallback")
        self.assertIsNone(fenced_result.summary)
        self.assertEqual([item.name for item in fenced_result.results], ["First", "Second"])
        self.assertTrue(all(item.explanation is None for item in fenced_result.results))

        def timed_out(_prompt):
            raise TimeoutError("slow")

        timed = Ranker(timed_out).rank(preferences(), records, p33=300, p66=500)
        self.assertEqual([item.name for item in timed.results], ["First", "Second"])
        self.assertEqual(timed.source, "fallback")

    def test_fewer_than_five_candidates_never_grows(self):
        records = [restaurant(id="only")]

        def complete(_prompt):
            return json.dumps({
                "summary": None,
                "recommendations": [
                    {"id": "only", "rank": 1, "explanation": "Only match."},
                    {"id": "pad-1", "rank": 2, "explanation": "Invented."},
                    {"id": "pad-2", "rank": 3, "explanation": "Invented."},
                ],
            })

        result = Ranker(complete).rank(preferences(), records, p33=300, p66=500)
        self.assertEqual(len(result.results), 1)
        self.assertEqual(result.results[0].explanation, "Only match.")

    def test_same_rank_follows_filter_order_and_caps_at_five(self):
        records = [restaurant(id=f"id-{index}", name=f"Place {index}") for index in range(6)]

        def complete(_prompt):
            return json.dumps({
                "summary": "   ",
                "recommendations": [
                    {"id": "id-5", "rank": 1, "explanation": "Later."},
                    {"id": "id-1", "rank": 1, "explanation": "Earlier."},
                    {"id": "id-1", "rank": 9, "explanation": "Duplicate."},
                    {"id": "missing", "rank": 1, "explanation": "No."},
                    {"id": "id-0", "rank": 2, "explanation": "  "},
                    {"id": "id-2", "rank": 3, "explanation": "Third."},
                    {"id": "id-3", "rank": 4, "explanation": "Fourth."},
                    {"id": "id-4", "rank": 5, "explanation": "Fifth, dropped by cap."},
                ],
            })

        result = Ranker(complete).rank(preferences(), records, p33=300, p66=500)
        self.assertEqual(result.source, "llm")
        self.assertIsNone(result.summary)
        self.assertEqual([item.name for item in result.results], ["Place 1", "Place 5", "Place 0", "Place 2", "Place 3"])
        self.assertEqual([item.rank for item in result.results], [1, 2, 3, 4, 5])
        self.assertIsNone(result.results[2].explanation)

    def test_bad_rank_invalidates_the_whole_response(self):
        records = [restaurant(id="keep")]

        def complete(_prompt):
            return json.dumps({
                "summary": None,
                "recommendations": [{"id": "keep", "rank": 0, "explanation": "Bad rank."}],
            })

        result = Ranker(complete).rank(preferences(), records, p33=300, p66=500)
        self.assertEqual(result.source, "fallback")
        self.assertIsNone(result.results[0].explanation)

    def test_missing_key_and_disallowed_model_do_not_call_groq(self):
        calls = {"count": 0}

        def transport(*_args):
            calls["count"] += 1
            return 200, "{}"

        missing = Ranker(transport=transport, settings=None)
        result = missing.rank(preferences(), [restaurant()], p33=300, p66=500)
        self.assertEqual(result.source, "fallback")

        disallowed = Ranker(
            transport=transport,
            settings=GroqSettings("test-key", "other-model", "https://api.groq.com/openai/v1"),
        )
        blocked = disallowed.rank(preferences(), [restaurant()], p33=300, p66=500)
        self.assertEqual(blocked.source, "fallback")
        self.assertEqual(calls["count"], 0)

    def test_http_retry_rules(self):
        prompt = build_prompt(preferences(), [restaurant()], p33=300, p66=500)
        settings = GroqSettings("test-key", "openai/gpt-oss-120b", "https://api.groq.com/openai/v1")

        def scripted(statuses):
            attempts = {"count": 0}

            def transport(_url, _body, _headers, timeout):
                self.assertEqual(timeout, 20)
                attempts["count"] += 1
                status = statuses[attempts["count"] - 1]
                if status == 200:
                    return 200, json.dumps({"choices": [{"message": {"content": "{\"summary\": null, \"recommendations\": []}", "reasoning": "ignore me"}}]})
                return status, "no"
            return transport, attempts

        server_error, attempts = scripted([500, 200])
        content = Ranker(transport=server_error, settings=settings).complete(prompt)
        self.assertEqual(attempts["count"], 2)
        self.assertIn("recommendations", content)
        self.assertNotIn("ignore me", content)

        limited, attempts = scripted([429, 429])
        with self.assertRaises(RetryableRankerError):
            Ranker(transport=limited, settings=settings).complete(prompt)
        self.assertEqual(attempts["count"], 2)

        client_error, attempts = scripted([400])
        with self.assertRaises(RankerError):
            Ranker(transport=client_error, settings=settings).complete(prompt)
        self.assertEqual(attempts["count"], 1)


class QuotaTests(unittest.TestCase):
    def limiter(self, clock=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "usage.json"
        return UsageLimiter(path, clock=clock or (lambda: 1_000_000.0))

    def test_limits_match_gpt_oss_120b(self):
        self.assertEqual(GPT_OSS_LIMITS["requests_per_minute"], 30)
        self.assertEqual(GPT_OSS_LIMITS["requests_per_day"], 1000)
        self.assertEqual(GPT_OSS_LIMITS["tokens_per_minute"], 8000)
        self.assertEqual(GPT_OSS_LIMITS["tokens_per_day"], 200_000)

    def test_refuses_before_a_call_that_would_exceed_a_window(self):
        now = {"t": 1_000_000.0}
        limiter = self.limiter(clock=lambda: now["t"])
        prompt = build_prompt(preferences(), [restaurant()], p33=300, p66=500)
        for _ in range(30):
            self.assertIsNotNone(limiter.reserve(1))
        self.assertIsNone(limiter.completion_cap(prompt))
        now["t"] += 61
        self.assertIsNotNone(limiter.completion_cap(prompt))

        for index in range(970):
            if index and index % 30 == 0:
                now["t"] += 61
            self.assertIsNotNone(limiter.reserve(1))
        self.assertIsNone(limiter.reserve(1))

        day_now = {"t": 2_000_000.0}
        day = self.limiter(clock=lambda: day_now["t"])
        for _ in range(25):
            self.assertIsNotNone(day.reserve(8000))
            day_now["t"] += 61
        self.assertIsNone(day.completion_cap(prompt))

        minute = self.limiter()
        self.assertIsNotNone(minute.reserve(8000))
        self.assertIsNone(minute.completion_cap(prompt))

    def test_shortlist_shrinks_to_fit_and_exhausted_quota_falls_back(self):
        limiter = self.limiter()
        records = [
            restaurant(id="one", dish_liked="pasta " * 40),
            restaurant(id="two", dish_liked="dosa " * 40),
        ]
        one = estimate_prompt_tokens(build_prompt(preferences(), records[:1], p33=300, p66=500))
        used = 8000 - (one + MIN_COMPLETION)
        self.assertIsNotNone(limiter.reserve(used))
        fitted = limiter.fit_candidates(preferences(), records, p33=300, p66=500)
        self.assertEqual([item.id for item in fitted], ["one"])

        blocked = self.limiter()
        self.assertIsNotNone(blocked.reserve(8000))
        calls = {"count": 0}

        def transport(*_args):
            calls["count"] += 1
            return 200, "{}"

        result = Ranker(
            transport=transport,
            settings=GroqSettings("test-key", "openai/gpt-oss-120b", "https://api.groq.com/openai/v1"),
            limiter=blocked,
        ).rank(preferences(), records, p33=300, p66=500)
        self.assertEqual(result.source, "fallback")
        self.assertEqual(calls["count"], 0)
        self.assertIsNone(result.results[0].explanation)

    def test_retry_does_not_spend_a_request_past_the_minute_cap(self):
        limiter = self.limiter()
        for _ in range(29):
            limiter.reserve(1)
        attempts = {"count": 0}

        def transport(_url, body, _headers, _timeout):
            attempts["count"] += 1
            payload = json.loads(body.decode())
            self.assertLessEqual(payload["max_completion_tokens"], COMPLETION_CAP)
            return 500, "down"

        prompt = build_prompt(preferences(), [restaurant()], p33=300, p66=500)
        with self.assertRaises(RankerError):
            Ranker(
                transport=transport,
                settings=GroqSettings("test-key", "openai/gpt-oss-120b", "https://api.groq.com/openai/v1"),
                limiter=limiter,
            ).complete(prompt)
        self.assertEqual(attempts["count"], 1)

    def test_actual_usage_replaces_the_reserved_estimate(self):
        limiter = self.limiter()
        event = limiter.reserve(7000)
        limiter.settle(event, 100)
        self.assertIsNotNone(limiter.reserve(7000))


if __name__ == "__main__":
    unittest.main()

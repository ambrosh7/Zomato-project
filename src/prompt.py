import json
from collections.abc import Sequence

from models import Preferences, Restaurant

DISH_LIKED_LIMIT = 120
CANDIDATE_FIELDS = (
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
)

SYSTEM_INSTRUCTION = (
    "You rank restaurants from the provided JSON only. "
    "Every recommended id must appear in the candidate list. "
    "Return at most 5 restaurants. "
    "If fewer than 5 candidates exist, return only those. "
    "Do not add restaurants, change ratings, or change prices. "
    "Write a short explanation that cites the user's cuisine, budget, rating, location, "
    "and any supported extra preference. "
    "If a free-text preference cannot be verified from the supplied fields, say that it cannot be verified. "
    "For example, family-friendly is not a dataset field and must not be claimed as a fact. "
    "Do not mention a preference that was omitted. "
    "Quick service may be cited only when rest_type, listed_in_type, dish_liked, online_order, "
    "or book_table supports it, such as Quick Bites or online_order true. "
    "Respond with JSON only using this shape: "
    '{"summary": string or null, "recommendations": [{"id": string, "rank": integer, "explanation": string}]}.'
)


class Prompt:
    def __init__(self, system: str, user: str) -> None:
        self.system = system
        self.user = user


def build_prompt(
    preferences: Preferences,
    candidates: Sequence[Restaurant],
    *,
    p33: int,
    p66: int,
) -> Prompt:
    payload = {
        "preferences": {
            "location": preferences.location,
            "budget": preferences.budget.strip().casefold(),
            "budget_range_inr": budget_range(preferences.budget, p33, p66, candidates),
            "cuisine": preferences.cuisine,
            "min_rating": preferences.min_rating,
            "additional": _additional(preferences.additional),
        },
        "candidates": [candidate_payload(record) for record in candidates],
    }
    return Prompt(SYSTEM_INSTRUCTION, json.dumps(payload, ensure_ascii=False))


def candidate_payload(record: Restaurant) -> dict:
    payload = {
        "id": record.id,
        "name": record.name,
        "location": record.location,
        "cuisines": list(record.cuisines),
        "rating": record.rating,
        "votes": record.votes,
        "cost_for_two": record.cost_for_two,
        "rest_type": record.rest_type,
        "listed_in_type": record.listed_in_type,
        "online_order": record.online_order,
        "book_table": record.book_table,
        "dish_liked": truncate_dish_liked(record.dish_liked),
    }
    extra = set(payload) - set(CANDIDATE_FIELDS)
    if extra:
        raise RuntimeError(f"prompt included forbidden fields: {sorted(extra)}")
    return payload


def truncate_dish_liked(value: str | None) -> str | None:
    if value is None:
        return None
    return value[:DISH_LIKED_LIMIT]


def budget_range(
    budget: str,
    p33: int,
    p66: int,
    candidates: Sequence[Restaurant],
) -> list[int]:
    band = budget.strip().casefold()
    if band == "low":
        return [0, p33]
    if band == "high":
        ceiling = max((record.cost_for_two for record in candidates), default=p66 + 1)
        return [p66 + 1, max(ceiling, p66 + 1)]
    return [p33 + 1, p66]


def _additional(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value

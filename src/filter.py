import math
from collections.abc import Sequence

from catalog import budget_band, get_meta, get_restaurants, normalize_key
from models import Preferences, Restaurant

SHORTLIST_LIMIT = 20
MAX_ADDITIONAL = 280
BANDS = frozenset({"low", "medium", "high"})
ANY_CUISINE = "any"
CITY_LOCATIONS = frozenset({"delhi", "bangalore", "bengaluru"})


class FilterError(ValueError):
    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(message)


def filter_preferences(
    preferences: Preferences,
    records: Sequence[Restaurant] | None = None,
    p33: int | None = None,
    p66: int | None = None,
) -> list[Restaurant]:
    if records is None:
        records = get_restaurants()
        meta = get_meta()
        if p33 is None:
            p33 = meta["p33"]
        if p66 is None:
            p66 = meta["p66"]
    if p33 is None or p66 is None:
        raise FilterError("budget", "budget bands are not available")

    location_key, location_field = _location_match(preferences.location, records)
    cuisine_key = _cuisine_key(preferences.cuisine, records)
    minimum = _minimum_rating(preferences.min_rating)
    band = _budget(preferences.budget)
    _check_additional(preferences.additional)

    matched = [
        record
        for record in records
        if _usable(record)
        and normalize_key(getattr(record, location_field)) == location_key
        and (cuisine_key is None or _has_cuisine(record, cuisine_key))
        and record.rating >= minimum
        and budget_band(record.cost_for_two, p33, p66) == band
    ]
    matched.sort(key=_sort_key)
    return matched[:SHORTLIST_LIMIT]


def _location_match(value: object, records: Sequence[Restaurant]) -> tuple[str, str]:
    if not isinstance(value, str) or not value.strip():
        raise FilterError("location", "location is required")
    key = normalize_key(value)
    if key in CITY_LOCATIONS:
        raise FilterError("location", "unknown location")
    neighborhoods = {
        normalize_key(record.location)
        for record in records
        if record.location and record.location.strip()
    }
    if key in neighborhoods:
        return key, "location"
    areas = {
        normalize_key(record.area)
        for record in records
        if record.area and record.area.strip()
    }
    if key in areas:
        return key, "area"
    raise FilterError("location", "unknown location")


def _cuisine_key(value: object, records: Sequence[Restaurant]) -> str | None:
    if not isinstance(value, str) or not value.strip():
        raise FilterError("cuisine", "cuisine is required")
    key = normalize_key(value)
    if key == ANY_CUISINE:
        return None
    known = {
        normalize_key(token)
        for record in records
        for token in record.cuisines
        if normalize_key(token) != ANY_CUISINE
    }
    if key not in known:
        raise FilterError("cuisine", "unknown cuisine")
    return key


def _minimum_rating(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FilterError("min_rating", "min_rating must be a number from 0 to 5")
    rating = float(value)
    if rating < 0 or rating > 5:
        raise FilterError("min_rating", "min_rating must be a number from 0 to 5")
    return rating


def _budget(value: object) -> str:
    if not isinstance(value, str):
        raise FilterError("budget", "budget must be low, medium, or high")
    band = value.strip().casefold()
    if band not in BANDS:
        raise FilterError("budget", "budget must be low, medium, or high")
    return band


def _check_additional(value: object) -> None:
    if value is None:
        return
    if not isinstance(value, str) or len(value) > MAX_ADDITIONAL:
        raise FilterError("additional", "additional must be at most 280 characters")


def _usable(record: Restaurant) -> bool:
    name = bool(record.name and record.name.strip())
    rating = isinstance(record.rating, (int, float)) and not isinstance(record.rating, bool)
    cost = isinstance(record.cost_for_two, int) and not isinstance(record.cost_for_two, bool)
    return name and rating and cost


def _has_cuisine(record: Restaurant, key: str) -> bool:
    return any(normalize_key(token) == key for token in record.cuisines)


def _vote_count(record: Restaurant) -> int:
    votes = record.votes
    if isinstance(votes, bool) or not isinstance(votes, int) or votes < 0:
        return 0
    return votes


def _score(record: Restaurant) -> float:
    return record.rating * math.log10(_vote_count(record) + 1)


def _sort_key(record: Restaurant) -> tuple:
    return (-_score(record), -_vote_count(record), -record.rating, record.id)

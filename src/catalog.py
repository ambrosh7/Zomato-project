"""In-memory restaurant catalog. Importing this module does not download data."""

from __future__ import annotations

import csv
import hashlib
import logging
import math
import os
import re
import sqlite3
import sys
import threading
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from urllib.parse import urlsplit

from models import Restaurant

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG_PATH = ROOT / "data" / "catalog.sqlite"

DATASET_ID = "ManikaSaini/zomato-restaurant-recommendation"
DATASET_FILE = "zomato.csv"

KEPT_COLUMNS = (
    "url",
    "address",
    "name",
    "online_order",
    "book_table",
    "rate",
    "votes",
    "location",
    "rest_type",
    "dish_liked",
    "cuisines",
    "approx_cost(for two people)",
    "listed_in(type)",
    "listed_in(city)",
)

FORBIDDEN_COLUMNS = frozenset({"phone", "reviews_list", "menu_item"})
RATE_RE = re.compile(r"^\d(\.\d)?/5$")
ANY_TOKEN = "any"

Row = dict[str, str | None]
Reader = Callable[[], Iterable[Row]]


def parse_rating(value: object) -> float | None:
    text = _text(value)
    if text is None or RATE_RE.fullmatch(text) is None:
        return None
    return float(text.split("/", 1)[0])


def parse_cost(value: object) -> int | None:
    text = _text(value)
    if text is None:
        return None
    digits = "".join(char for char in text if char.isdigit())
    if not digits:
        return None
    return int(digits)


def parse_cuisines(value: object) -> list[str]:
    text = _text(value)
    if text is None:
        return []
    seen: set[str] = set()
    tokens: list[str] = []
    for part in text.split(","):
        token = part.strip()
        if not token or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def parse_yes_no(value: object) -> bool:
    text = _text(value)
    return text is not None and text.lower() == "yes"


def parse_votes(value: object) -> int:
    text = _text(value)
    if text is None or not text.isdigit():
        return 0
    return int(text)


def repair_name(value: object) -> str:
    text = _text(value)
    if text is None:
        return ""
    try:
        repaired = text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    return repaired


def url_path(value: object) -> str | None:
    text = _text(value)
    if text is None:
        return None
    path = urlsplit(text).path.strip()
    return path or None


def normalize_key(value: str) -> str:
    return " ".join(value.strip().lower().split())


def nearest_rank(values: list[int], percent: int) -> int:
    if not values:
        raise ValueError("nearest_rank requires at least one value")
    if percent <= 0 or percent > 100:
        raise ValueError("percent must be from 1 to 100")
    ordered = sorted(values)
    rank = math.ceil(percent * len(ordered) / 100)
    return ordered[rank - 1]


def budget_band(cost: int, p33: int, p66: int) -> str:
    if cost <= p33:
        return "low"
    if cost <= p66:
        return "medium"
    return "high"


def band_labels(p33: int | None, p66: int | None) -> dict[str, str]:
    if p33 is None or p66 is None:
        return {"low": "Low", "medium": "Medium", "high": "High"}
    return {
        "low": f"Low (up to ₹{p33} for two)",
        "medium": f"Medium (above ₹{p33} up to ₹{p66} for two)",
        "high": f"High (above ₹{p66} for two)",
    }


class Catalog:
    def __init__(self) -> None:
        self._status = "loading"
        self._records: tuple[Restaurant, ...] = ()
        self._meta = _empty_meta()
        self._p33: int | None = None
        self._p66: int | None = None
        self._lock = threading.Lock()

    def status(self) -> str:
        return self._status

    def is_ready(self) -> bool:
        return self._status == "ready"

    def get_restaurants(self) -> tuple[Restaurant, ...]:
        if not self.is_ready():
            raise RuntimeError("catalog is not ready")
        return self._records

    def get_meta(self) -> dict:
        if not self.is_ready():
            raise RuntimeError("catalog is not ready")
        return self._meta

    def band_for(self, cost: int) -> str | None:
        if self._p33 is None or self._p66 is None:
            return None
        return budget_band(cost, self._p33, self._p66)

    def load(self, reader: Reader | None = None) -> None:
        if self._status == "ready":
            return
        with self._lock:
            if self._status == "ready":
                return
            self._status = "loading"
            self._records = ()
            self._meta = _empty_meta()
            self._p33 = None
            self._p66 = None
            try:
                if reader is None:
                    records = read_sqlite_catalog(catalog_path())
                    p33, p66 = _percentiles(records)
                    meta = _meta_for(records, p33, p66)
                else:
                    records, meta, p33, p66 = build_catalog(reader())
            except Exception:
                logger.exception("catalog load failed")
                self._status = "failed"
                return
            self._records = records
            self._meta = meta
            self._p33 = p33
            self._p66 = p66
            self._status = "ready"


def status() -> str:
    return _catalog.status()


def is_ready() -> bool:
    return _catalog.is_ready()


def get_restaurants() -> tuple[Restaurant, ...]:
    return _catalog.get_restaurants()


def get_meta() -> dict:
    return _catalog.get_meta()


def load(reader: Reader | None = None) -> None:
    _catalog.load(reader)


def catalog_path() -> Path:
    raw = os.environ.get("CATALOG_PATH", "").strip() or _env_value("CATALOG_PATH") or "data/catalog.sqlite"
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path


def read_sqlite_catalog(path: Path) -> tuple[Restaurant, ...]:
    if not path.is_file():
        raise FileNotFoundError(f"catalog file not found: {path}")
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute(
            """
            SELECT id, name, location, area, rating, votes, cost_for_two,
                   rest_type, listed_in_type, online_order, book_table, dish_liked
            FROM restaurants
            ORDER BY rowid
            """
        ).fetchall()
        cuisine_rows = connection.execute(
            "SELECT restaurant_id, cuisine FROM restaurant_cuisines ORDER BY restaurant_id, position"
        ).fetchall()
    finally:
        connection.close()

    cuisines: dict[str, list[str]] = {}
    for restaurant_id, cuisine in cuisine_rows:
        cuisines.setdefault(restaurant_id, []).append(cuisine)
    return tuple(
        Restaurant(
            id=row[0],
            name=row[1],
            location=row[2] or "",
            area=row[3] or "",
            cuisines=cuisines.get(row[0], []),
            rating=float(row[4]),
            votes=int(row[5]),
            cost_for_two=int(row[6]),
            rest_type=row[7] or "",
            listed_in_type=row[8] or "",
            online_order=bool(row[9]),
            book_table=bool(row[10]),
            dish_liked=row[11] or None,
        )
        for row in rows
    )


def _env_value(name: str) -> str:
    path = ROOT / ".env"
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        if key.strip() == name:
            return value.strip().strip("'\"")
    return ""


def build_catalog(rows: Iterable[Row]) -> tuple[tuple[Restaurant, ...], dict, int | None, int | None]:
    winners: dict[str, tuple[int, Restaurant]] = {}
    for index, row in enumerate(rows):
        parsed = _parse_row(row)
        if parsed is None:
            continue
        key, record = parsed
        current = winners.get(key)
        if current is None or _prefer(record, index, current[1], current[0]):
            winners[key] = (index, record)

    ordered = [item[1] for item in sorted(winners.values(), key=lambda item: item[0])]
    records = tuple(ordered)
    p33, p66 = _percentiles(records)
    return records, _meta_for(records, p33, p66), p33, p66


def read_dataset_rows() -> Iterator[Row]:
    from huggingface_hub import hf_hub_download

    path = hf_hub_download(
        repo_id=DATASET_ID,
        filename=DATASET_FILE,
        repo_type="dataset",
    )
    yield from _read_kept_columns(path)


def _raise_csv_field_limit() -> None:
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def _read_kept_columns(path: str) -> Iterator[Row]:
    _raise_csv_field_limit()
    with open(path, newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if not header:
            raise RuntimeError("dataset file has no header")
        header[0] = header[0].lstrip("\ufeff")
        missing = [name for name in KEPT_COLUMNS if name not in header]
        if missing:
            raise RuntimeError(f"schema mismatch, missing columns: {missing}")
        if FORBIDDEN_COLUMNS.intersection(KEPT_COLUMNS):
            raise RuntimeError("refusing to load phone, reviews, or menu columns")
        indexes = {name: header.index(name) for name in KEPT_COLUMNS}
        for raw in reader:
            yield {
                name: raw[index] if index < len(raw) else ""
                for name, index in indexes.items()
            }


def _parse_row(row: Row) -> tuple[str, Restaurant] | None:
    name = repair_name(row.get("name"))
    if not name:
        return None
    rating = parse_rating(row.get("rate"))
    cost = parse_cost(row.get("approx_cost(for two people)"))
    if rating is None or cost is None:
        return None

    location = _text(row.get("location")) or ""
    area = _text(row.get("listed_in(city)")) or ""
    path = url_path(row.get("url"))
    if path:
        key = "path:" + path
    else:
        key = "name:" + normalize_key(name) + "\n" + normalize_key(location)
    dish = _text(row.get("dish_liked"))
    record = Restaurant(
        id=hashlib.sha256(key.encode("utf-8")).hexdigest(),
        name=name,
        location=location,
        area=area,
        cuisines=parse_cuisines(row.get("cuisines")),
        rating=rating,
        votes=parse_votes(row.get("votes")),
        cost_for_two=cost,
        rest_type=_text(row.get("rest_type")) or "",
        listed_in_type=_text(row.get("listed_in(type)")) or "",
        online_order=parse_yes_no(row.get("online_order")),
        book_table=parse_yes_no(row.get("book_table")),
        dish_liked=dish,
    )
    return key, record


def _prefer(candidate: Restaurant, candidate_index: int, current: Restaurant, current_index: int) -> bool:
    if candidate.votes != current.votes:
        return candidate.votes > current.votes
    if candidate.rating != current.rating:
        return candidate.rating > current.rating
    return candidate_index < current_index


def _percentiles(records: tuple[Restaurant, ...] | list[Restaurant]) -> tuple[int | None, int | None]:
    if not records:
        return None, None
    costs = [record.cost_for_two for record in records]
    return nearest_rank(costs, 33), nearest_rank(costs, 66)


def _meta_for(records: tuple[Restaurant, ...] | list[Restaurant], p33: int | None, p66: int | None) -> dict:
    labels = band_labels(p33, p66)
    return {
        "locations": _display_values(record.location for record in records),
        "cuisines": _cuisine_index(records),
        "p33": p33,
        "p66": p66,
        "budget_bands": [
            {"id": "low", "label": labels["low"]},
            {"id": "medium", "label": labels["medium"]},
            {"id": "high", "label": labels["high"]},
        ],
    }


def _display_values(values: Iterable[str]) -> list[str]:
    counts: Counter[str] = Counter()
    first_seen: dict[str, int] = {}
    groups: dict[str, str] = {}
    for index, raw in enumerate(values):
        trimmed = raw.strip()
        if not trimmed:
            continue
        key = normalize_key(trimmed)
        counts[trimmed] += 1
        first_seen.setdefault(trimmed, index)
        current = groups.get(key)
        if current is None or _prefer_spelling(trimmed, current, counts, first_seen):
            groups[key] = trimmed
    return sorted(groups.values(), key=str.casefold)


def _prefer_spelling(candidate: str, current: str, counts: Counter[str], first_seen: dict[str, int]) -> bool:
    if counts[candidate] != counts[current]:
        return counts[candidate] > counts[current]
    return first_seen[candidate] < first_seen[current]


def _cuisine_index(records: Iterable[Restaurant]) -> list[str]:
    grouped: dict[str, list[tuple[int, str]]] = {}
    logged: set[str] = set()
    order = 0
    for record in records:
        for token in record.cuisines:
            key = normalize_key(token)
            if key == ANY_TOKEN:
                if token not in logged:
                    logger.warning("dropping cuisine token %r from the index; it collides with the Any sentinel", token)
                    logged.add(token)
                continue
            grouped.setdefault(key, []).append((order, token))
            order += 1
    chosen: list[str] = []
    for items in grouped.values():
        counts = Counter(token for _, token in items)
        first_seen: dict[str, int] = {}
        for index, token in items:
            first_seen.setdefault(token, index)
        spelling = min(counts, key=lambda token: (-counts[token], first_seen[token], token.casefold()))
        chosen.append(spelling)
    return sorted(chosen, key=str.casefold)


def _empty_meta() -> dict:
    return {
        "locations": [],
        "cuisines": [],
        "p33": None,
        "p66": None,
        "budget_bands": [
            {"id": "low", "label": "Low"},
            {"id": "medium", "label": "Medium"},
            {"id": "high", "label": "High"},
        ],
    }


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text


_catalog = Catalog()

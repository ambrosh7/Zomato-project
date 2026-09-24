"""One-off inspection of ManikaSaini/zomato-restaurant-recommendation.

Not part of the request path. Do not import this from the API.

Findings (full run exited 0; schema matches architecture §4.1):
- 51,717 rows in zomato.csv. Kept columns only. reviews_list and menu_item were scanned past, not stored. Three unused columns were left out (phone, reviews_list, menu_item).
- 93 location values and 30 listed_in(city) values. They are Bangalore neighborhoods and areas. Delhi is absent. Do not add other cities.
- Two location names contain a comma and must stay one value: "ITPL Main Road, Whitefield" and "Varthur Main Road, Whitefield".
- Nulls: rate 7,775; location 21; rest_type 227; dish_liked 28,078; cuisines 45; approx_cost(for two people) 346. url, address, name, votes, online_order, book_table, listed_in(type), and listed_in(city) have no nulls.
- Unusable rates: NEW 2,208; "-" 69; empty 7,775; other regex failures 20,377 (forms like "4.1 /5"). Phase 2 drops all of these and must not repair the space.
- votes values are integers. Do not parse a display string.
- Dedup is required: 51,717 URL paths, 12,453 unique after stripping the query, 39,264 extra rows.
"""

from __future__ import annotations

import csv
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from datasets import Dataset
from huggingface_hub import hf_hub_download

DATASET_ID = "ManikaSaini/zomato-restaurant-recommendation"
FILENAME = "zomato.csv"

# Architecture §4.1. reviews_list and menu_item are intentionally absent.
KEPT_COLUMNS = [
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
]

FORBIDDEN_COLUMNS = {"reviews_list", "menu_item"}
RATE_RE = re.compile(r"^\d(\.\d)?/5$")
SAMPLE_COLUMNS = [
    "name",
    "location",
    "cuisines",
    "rate",
    "votes",
    "approx_cost(for two people)",
    "listed_in(city)",
    "listed_in(type)",
]
COMMA_LOCATION = "ITPL Main Road, Whitefield"


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def raise_csv_field_limit() -> None:
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def assert_column_selection() -> None:
    overlap = FORBIDDEN_COLUMNS.intersection(KEPT_COLUMNS)
    if overlap:
        fail(f"refusing to load forbidden columns: {sorted(overlap)}")


def url_path(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    path = urlsplit(text).path.strip()
    return path or None


def is_blank(value: str) -> bool:
    return value.strip() == ""


def read_kept_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    raise_csv_field_limit()
    rows: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if not header:
            fail("dataset file has no header")
        header[0] = header[0].lstrip("\ufeff")
        missing = [name for name in KEPT_COLUMNS if name not in header]
        if missing:
            fail(f"schema mismatch, missing columns: {missing}. Do not guess a mapping.")
        if FORBIDDEN_COLUMNS.intersection(KEPT_COLUMNS):
            fail("refusing to store reviews_list or menu_item")
        indexes = {name: header.index(name) for name in KEPT_COLUMNS}
        for raw in reader:
            # Copy kept columns only. The oversized review cell is scanned, then dropped.
            rows.append({name: raw[index] if index < len(raw) else "" for name, index in indexes.items()})
    stored = set(rows[0]) if rows else set(KEPT_COLUMNS)
    if FORBIDDEN_COLUMNS.intersection(stored):
        fail("forbidden columns were stored in the working set")
    return header, rows


def main() -> None:
    assert_column_selection()
    if sys.version_info < (3, 11):
        fail("Python 3.11+ is required")

    path = Path(
        hf_hub_download(
            repo_id=DATASET_ID,
            filename=FILENAME,
            repo_type="dataset",
        )
    )
    header, rows = read_kept_rows(path)
    table = Dataset.from_list(rows)
    if FORBIDDEN_COLUMNS.intersection(table.column_names):
        fail("forbidden columns were stored in the dataset")

    print(f"dataset: {DATASET_ID}")
    print(f"file: {FILENAME}")
    print(f"rows: {table.num_rows}")
    print(f"columns: {list(table.column_names)}")
    print("null_counts:")
    for name in KEPT_COLUMNS:
        nulls = sum(1 for value in table[name] if is_blank(value))
        print(f"  {name}: {nulls}")

    print("samples:")
    for record in table.select(range(min(5, table.num_rows))):
        print({name: record[name] for name in SAMPLE_COLUMNS})

    locations = sorted({value.strip() for value in table["location"] if value.strip()})
    areas = sorted({value.strip() for value in table["listed_in(city)"] if value.strip()})
    print(f"distinct_location: {len(locations)}")
    print("locations:", " | ".join(locations))
    print(f"distinct_listed_in_city: {len(areas)}")
    print("listed_in_city:", " | ".join(areas))
    print(f"comma_location_present: {COMMA_LOCATION in locations}")
    if "Delhi" in locations or "Delhi" in areas:
        fail("Delhi is present; do not treat locations as Bangalore neighborhoods")
    if COMMA_LOCATION not in locations and any("," in name for name in locations):
        print("comma_locations:", " | ".join(name for name in locations if "," in name))

    unusable = Counter()
    for value in table["rate"]:
        text = value.strip()
        if text == "":
            unusable["empty"] += 1
        elif text.upper() == "NEW":
            unusable["NEW"] += 1
        elif text == "-":
            unusable["dash"] += 1
        elif RATE_RE.fullmatch(text) is None:
            unusable["regex_fail"] += 1
    print("unusable_rate:")
    for key in ("NEW", "dash", "empty", "regex_fail"):
        print(f"  {key}: {unusable[key]}")
    print(f"  total: {sum(unusable.values())}")

    votes = [value.strip() for value in table["votes"] if value.strip()]
    non_int = sum(1 for value in votes if re.fullmatch(r"-?\d+", value) is None)
    print(f"votes_non_integer_values: {non_int}")

    paths = [url_path(value) for value in table["url"]]
    present = [item for item in paths if item]
    unique_paths = len(set(present))
    duplicate_rows = len(present) - unique_paths
    print(f"url_paths: {len(present)}")
    print(f"unique_url_paths: {unique_paths}")
    print(f"duplicate_url_path_rows: {duplicate_rows}")
    print(f"missing_url: {len(paths) - len(present)}")
    if duplicate_rows <= 0:
        fail("duplicate URL-path rate is not high enough to require dedup")

    unused = [name for name in header if name not in KEPT_COLUMNS]
    print(f"columns_not_stored: {len(unused)}")
    print("inspection: ok")


if __name__ == "__main__":
    main()

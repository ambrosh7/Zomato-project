"""Write the cleaned catalog to SQLite for inspection. Not part of the request path."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from catalog import budget_band, build_catalog, catalog_path, read_dataset_rows

SCHEMA = """
CREATE TABLE restaurants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    location TEXT NOT NULL,
    area TEXT NOT NULL,
    cuisines TEXT NOT NULL,
    rating REAL NOT NULL,
    votes INTEGER NOT NULL,
    cost_for_two INTEGER NOT NULL,
    budget TEXT NOT NULL CHECK (budget IN ('low', 'medium', 'high')),
    rest_type TEXT NOT NULL,
    listed_in_type TEXT NOT NULL,
    online_order INTEGER NOT NULL CHECK (online_order IN (0, 1)),
    book_table INTEGER NOT NULL CHECK (book_table IN (0, 1)),
    dish_liked TEXT
);

CREATE TABLE restaurant_cuisines (
    restaurant_id TEXT NOT NULL REFERENCES restaurants(id),
    position INTEGER NOT NULL,
    cuisine TEXT NOT NULL,
    PRIMARY KEY (restaurant_id, position)
);

CREATE TABLE catalog_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX idx_restaurants_location ON restaurants(location);
CREATE INDEX idx_restaurants_budget ON restaurants(budget);
CREATE INDEX idx_restaurants_rating ON restaurants(rating);
CREATE INDEX idx_restaurant_cuisines_cuisine ON restaurant_cuisines(cuisine);
"""


def main() -> None:
    records, _meta, p33, p66 = build_catalog(read_dataset_rows())
    if p33 is None or p66 is None:
        raise SystemExit("catalog has no budget bands")

    db_path = catalog_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(SCHEMA)
        connection.executemany(
            """
            INSERT INTO restaurants (
                id, name, location, area, cuisines, rating, votes, cost_for_two,
                budget, rest_type, listed_in_type, online_order, book_table, dish_liked
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    record.id,
                    record.name,
                    record.location,
                    record.area,
                    ", ".join(record.cuisines),
                    record.rating,
                    record.votes,
                    record.cost_for_two,
                    budget_band(record.cost_for_two, p33, p66),
                    record.rest_type,
                    record.listed_in_type,
                    int(record.online_order),
                    int(record.book_table),
                    record.dish_liked,
                )
                for record in records
            ],
        )
        connection.executemany(
            "INSERT INTO restaurant_cuisines (restaurant_id, position, cuisine) VALUES (?, ?, ?)",
            [
                (record.id, position, cuisine)
                for record in records
                for position, cuisine in enumerate(record.cuisines)
            ],
        )
        connection.executemany(
            "INSERT INTO catalog_meta (key, value) VALUES (?, ?)",
            [
                ("restaurant_count", str(len(records))),
                ("p33", str(p33)),
                ("p66", str(p66)),
                ("low", f"up to ₹{p33} for two"),
                ("medium", f"above ₹{p33} up to ₹{p66} for two"),
                ("high", f"above ₹{p66} for two"),
                ("source", "cleaned catalog; phone, reviews, menu, and address are not stored"),
            ],
        )
        connection.commit()
    finally:
        connection.close()

    print(f"wrote {len(records)} restaurants to {db_path}")


if __name__ == "__main__":
    main()

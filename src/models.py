from dataclasses import dataclass


@dataclass
class Restaurant:
    id: str
    name: str
    location: str
    area: str
    cuisines: list[str]
    rating: float
    votes: int
    cost_for_two: int
    rest_type: str
    listed_in_type: str
    online_order: bool
    book_table: bool
    dish_liked: str | None


@dataclass
class Preferences:
    location: str
    budget: str
    cuisine: str
    min_rating: float
    additional: str | None = None


@dataclass
class Recommendation:
    rank: int
    name: str
    cuisines: list[str]
    rating: float
    votes: int
    estimated_cost: int
    cost_label: str
    location: str
    explanation: str | None = None
    id: str | None = None

"""HTTP API. One process serves the page and the recommendation routes."""

from __future__ import annotations

import json
import sys
import threading
from collections.abc import Sequence
from contextlib import asynccontextmanager
from pathlib import Path

import catalog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from filter import FilterError, filter_preferences
from models import Preferences, Restaurant
from ranker import RankResult, Ranker

MIN_PYTHON = (3, 11)
HOST = "127.0.0.1"
PORT = 8000
WEB_DIR = Path(__file__).resolve().parents[1] / "web"
NO_MATCH_SUGGESTIONS = (
    "Lower the minimum rating",
    "Choose Any cuisine",
    "Widen the budget",
)


def require_python() -> None:
    if sys.version_info < MIN_PYTHON:
        raise SystemExit("Python 3.11+ is required")


class Services:
    def status(self) -> str:
        return catalog.status()

    def meta(self) -> dict:
        return catalog.get_meta()

    def restaurants(self) -> tuple[Restaurant, ...]:
        return catalog.get_restaurants()

    def rank(self, preferences: Preferences, candidates: Sequence[Restaurant], p33: int, p66: int) -> RankResult:
        return Ranker().rank(preferences, candidates, p33=p33, p66=p66)

    def load(self) -> None:
        catalog.load()


def create_app(services: Services | None = None, *, load_on_startup: bool = True) -> FastAPI:
    bound = services or Services()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if load_on_startup and not getattr(app.state, "load_started", False):
            app.state.load_started = True
            threading.Thread(target=bound.load, name="catalog-load", daemon=True).start()
        yield

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.services = bound
    app.state.load_started = False

    @app.get("/health")
    def health() -> dict:
        return {"status": bound.status()}

    @app.get("/api/meta")
    def meta():
        blocked = _not_ready(bound)
        if blocked is not None:
            return blocked
        return bound.meta()

    @app.get("/api/recommendations")
    def recommendations_get():
        return JSONResponse({"error": "Method not allowed"}, status_code=405)

    @app.post("/api/recommendations")
    async def recommendations(request: Request):
        blocked = _not_ready(bound)
        if blocked is not None:
            return blocked
        payload, error = await _read_json(request)
        if error is not None:
            return error
        preferences, error = _preferences(payload)
        if error is not None:
            return error
        meta = bound.meta()
        try:
            shortlist = filter_preferences(
                preferences,
                bound.restaurants(),
                p33=meta["p33"],
                p66=meta["p66"],
            )
        except FilterError as exc:
            return JSONResponse({"field": exc.field}, status_code=400)
        if not shortlist:
            return {
                "status": "no_matches",
                "message": "No restaurants matched these filters.",
                "suggestions": list(NO_MATCH_SUGGESTIONS),
            }
        try:
            ranked = bound.rank(preferences, shortlist, meta["p33"], meta["p66"])
        except Exception:
            ranked = _fallback(shortlist)
        results = _public_results(ranked, shortlist)
        if not results:
            ranked = _fallback(shortlist)
            results = _public_results(ranked, shortlist)
        return {
            "status": "ok",
            "source": ranked.source,
            "summary": ranked.summary,
            "results": results,
        }

    WEB_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


def _not_ready(services: Services) -> JSONResponse | None:
    status = services.status()
    if status == "ready":
        return None
    return JSONResponse({"status": status}, status_code=503)


async def _read_json(request: Request) -> tuple[dict | None, JSONResponse | None]:
    raw = await request.body()
    if not raw.strip():
        return None, JSONResponse({"error": "Request body must be JSON"}, status_code=400)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None, JSONResponse({"error": "Request body must be JSON"}, status_code=400)
    if not isinstance(payload, dict):
        return None, JSONResponse({"error": "Request body must be a JSON object"}, status_code=400)
    return payload, None


def _preferences(payload: dict) -> tuple[Preferences | None, JSONResponse | None]:
    location = payload.get("location")
    if not isinstance(location, str) or not location.strip():
        return None, JSONResponse({"field": "location"}, status_code=400)
    budget = payload.get("budget")
    if not isinstance(budget, str) or budget.strip().casefold() not in {"low", "medium", "high"}:
        return None, JSONResponse({"field": "budget"}, status_code=400)
    cuisine = payload.get("cuisine")
    if not isinstance(cuisine, str) or not cuisine.strip():
        return None, JSONResponse({"field": "cuisine"}, status_code=400)
    rating, error = _min_rating(payload.get("min_rating", None) if "min_rating" in payload else None)
    if error is not None:
        return None, error
    additional = payload.get("additional", None)
    if additional is not None and not isinstance(additional, str):
        return None, JSONResponse({"field": "additional"}, status_code=400)
    if isinstance(additional, str) and len(additional) > 280:
        return None, JSONResponse({"field": "additional"}, status_code=400)
    if additional is not None and not additional.strip():
        additional = None
    return Preferences(location, budget, cuisine, rating, additional), None


def _min_rating(value: object) -> tuple[float | None, JSONResponse | None]:
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None, JSONResponse({"field": "min_rating"}, status_code=400)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= 5:
        return None, JSONResponse({"field": "min_rating"}, status_code=400)
    return float(value), None


def _public_results(ranked: RankResult, shortlist: Sequence[Restaurant]) -> list[dict]:
    by_id = {record.id: record for record in shortlist}
    by_name: dict[str, Restaurant] = {}
    for record in shortlist:
        by_name.setdefault(record.name, record)
    results = []
    for card in ranked.results[:5]:
        record = by_id.get(card.id) if card.id else None
        if record is None:
            record = by_name.get(card.name)
        if record is None:
            continue
        item = {
            "rank": len(results) + 1,
            "name": record.name,
            "cuisines": list(record.cuisines),
            "rating": record.rating,
            "votes": record.votes,
            "estimated_cost": record.cost_for_two,
            "cost_label": f"₹{record.cost_for_two} for two",
            "location": record.location,
        }
        if card.explanation and card.explanation.strip() and ranked.source == "llm":
            item["explanation"] = card.explanation.strip()
        results.append(item)
    return results


def _fallback(shortlist: Sequence[Restaurant]) -> RankResult:
    from models import Recommendation

    results = [
        Recommendation(
            rank=index,
            name=record.name,
            cuisines=list(record.cuisines),
            rating=record.rating,
            votes=record.votes,
            estimated_cost=record.cost_for_two,
            cost_label=f"₹{record.cost_for_two} for two",
            location=record.location,
            explanation=None,
            id=record.id,
        )
        for index, record in enumerate(shortlist[:5], start=1)
    ]
    return RankResult("fallback", None, results)


def main() -> None:
    require_python()
    app = create_app()
    import uvicorn

    print(f"http://{HOST}:{PORT}/health", flush=True)
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()

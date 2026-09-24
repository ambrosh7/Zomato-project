"""Groq ranker. Invalid model output never becomes user-facing facts."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from models import Preferences, Recommendation, Restaurant
from prompt import Prompt, build_prompt

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "restaurant-recommender/0.1"
TIMEOUT_SECONDS = 20
ALLOWED_MODELS = frozenset({"openai/gpt-oss-120b", "qwen/qwen3.6-27b"})
GPT_OSS_MODEL = "openai/gpt-oss-120b"
GPT_OSS_LIMITS = {
    "requests_per_minute": 30,
    "requests_per_day": 1000,
    "tokens_per_minute": 8000,
    "tokens_per_day": 200_000,
}
COMPLETION_CAP = 512
MIN_COMPLETION = 256
MINUTE_SECONDS = 60
DAY_SECONDS = 24 * 60 * 60
USAGE_PATH = ROOT / "data" / "groq-usage.json"
RESULT_LIMIT = 5
_UNSET = object()

Transport = Callable[[str, bytes, dict[str, str], float], tuple[int, str]]


class RankerError(Exception):
    pass


class RetryableRankerError(RankerError):
    pass


class RankResult:
    def __init__(self, source: str, summary: str | None, results: list[Recommendation]) -> None:
        self.source = source
        self.summary = summary
        self.results = results


class GroqSettings:
    def __init__(self, api_key: str, model: str, base_url: str) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")


class UsageEvent:
    def __init__(self, ts: float, requests: int, tokens: int) -> None:
        self.ts = ts
        self.requests = requests
        self.tokens = tokens


class UsageLimiter:
    """Sliding windows for openai/gpt-oss-120b. A refused call is not sent."""

    def __init__(self, path: Path | None = None, clock: Callable[[], float] | None = None) -> None:
        self._path = path
        self._clock = clock or time.time
        self._lock = threading.Lock()
        self._events = self._load()

    def fit_candidates(
        self,
        preferences: Preferences,
        candidates: Sequence[Restaurant],
        *,
        p33: int,
        p66: int,
    ) -> list[Restaurant]:
        chosen: list[Restaurant] = []
        for count in range(len(candidates), 0, -1):
            prompt = build_prompt(preferences, candidates[:count], p33=p33, p66=p66)
            if self.completion_cap(prompt) is not None:
                chosen = list(candidates[:count])
                break
        return chosen

    def completion_cap(self, prompt: Prompt) -> int | None:
        with self._lock:
            self._prune()
            prompt_tokens = estimate_prompt_tokens(prompt)
            room = min(self._token_room(MINUTE_SECONDS), self._token_room(DAY_SECONDS))
            request_ok = self._request_room(MINUTE_SECONDS) >= 1 and self._request_room(DAY_SECONDS) >= 1
            if not request_ok:
                return None
            cap = min(COMPLETION_CAP, room - prompt_tokens)
            if cap < MIN_COMPLETION:
                return None
            return cap

    def reserve(self, tokens: int) -> UsageEvent | None:
        with self._lock:
            self._prune()
            if self._request_room(MINUTE_SECONDS) < 1 or self._request_room(DAY_SECONDS) < 1:
                return None
            if self._token_room(MINUTE_SECONDS) < tokens or self._token_room(DAY_SECONDS) < tokens:
                return None
            event = UsageEvent(self._clock(), 1, tokens)
            self._events.append(event)
            self._save()
            return event

    def settle(self, event: UsageEvent, actual_tokens: int | None) -> None:
        if actual_tokens is None:
            return
        with self._lock:
            event.tokens = max(0, actual_tokens)
            self._save()

    def _token_room(self, window: int) -> int:
        used = sum(event.tokens for event in self._in_window(window))
        limit = GPT_OSS_LIMITS["tokens_per_minute"] if window == MINUTE_SECONDS else GPT_OSS_LIMITS["tokens_per_day"]
        return limit - used

    def _request_room(self, window: int) -> int:
        used = sum(event.requests for event in self._in_window(window))
        limit = GPT_OSS_LIMITS["requests_per_minute"] if window == MINUTE_SECONDS else GPT_OSS_LIMITS["requests_per_day"]
        return limit - used

    def _in_window(self, window: int) -> list[UsageEvent]:
        cutoff = self._clock() - window
        return [event for event in self._events if event.ts >= cutoff]

    def _prune(self) -> None:
        cutoff = self._clock() - DAY_SECONDS
        self._events = [event for event in self._events if event.ts >= cutoff]

    def _load(self) -> list[UsageEvent]:
        if self._path is None or not self._path.is_file():
            return []
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.error("ignoring unreadable Groq usage file")
            return []
        events = []
        for item in payload.get("events", []):
            try:
                events.append(UsageEvent(float(item["ts"]), int(item["requests"]), int(item["tokens"])))
            except (KeyError, TypeError, ValueError):
                continue
        return events

    def _save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": GPT_OSS_MODEL,
            "events": [
                {"ts": event.ts, "requests": event.requests, "tokens": event.tokens}
                for event in self._events
            ],
        }
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(self._path)


_shared_limiter: UsageLimiter | None = None
_shared_limiter_lock = threading.Lock()


def shared_usage_limiter() -> UsageLimiter:
    global _shared_limiter
    with _shared_limiter_lock:
        if _shared_limiter is None:
            _shared_limiter = UsageLimiter(USAGE_PATH)
        return _shared_limiter


def estimate_prompt_tokens(prompt: Prompt) -> int:
    # Overestimate so a call stays under Groq's tokenizer.
    text = prompt.system + prompt.user
    return max(1, (len(text.encode("utf-8")) + 2) // 3) + 32


class Ranker:
    def __init__(
        self,
        complete: Callable[[Prompt], str] | None = None,
        *,
        transport: Transport | None = None,
        settings=_UNSET,
        limiter=_UNSET,
    ) -> None:
        self._complete = complete
        self._transport = transport or _urllib_transport
        self._settings = settings
        self._limiter = limiter

    def complete(self, prompt: Prompt) -> str:
        if self._complete is not None:
            return self._complete(prompt)
        settings = self._configured()
        if settings is None:
            raise RankerError("Groq is not configured")
        limiter = self._active_limiter(settings.model)
        last_error: Exception | None = None
        for attempt in range(2):
            cap = COMPLETION_CAP
            reservation = None
            if limiter is not None:
                cap_or_none = limiter.completion_cap(prompt)
                if cap_or_none is None:
                    raise RankerError("openai/gpt-oss-120b quota would be exceeded")
                cap = cap_or_none
                reservation = limiter.reserve(estimate_prompt_tokens(prompt) + cap)
                if reservation is None:
                    raise RankerError("openai/gpt-oss-120b quota would be exceeded")
            try:
                content, actual = self._post(settings, prompt, cap)
            except RetryableRankerError as exc:
                last_error = exc
                if attempt == 1:
                    raise
                continue
            except RankerError:
                raise
            if limiter is not None and reservation is not None:
                limiter.settle(reservation, actual)
            return content
        raise last_error or RankerError("Groq request failed")

    def rank(
        self,
        preferences: Preferences,
        candidates: Sequence[Restaurant],
        *,
        p33: int,
        p66: int,
    ) -> RankResult:
        if not candidates:
            return _fallback([])
        chosen = list(candidates)
        if self._complete is None:
            settings = self._configured()
            if settings is None:
                return _fallback(candidates)
            limiter = self._active_limiter(settings.model)
            if limiter is not None:
                chosen = limiter.fit_candidates(preferences, candidates, p33=p33, p66=p66)
                if not chosen:
                    logger.error("openai/gpt-oss-120b quota would be exceeded; using filter order")
                    return _fallback(candidates)
        prompt = build_prompt(preferences, chosen, p33=p33, p66=p66)
        try:
            parsed = parse_model_json(self.complete(prompt))
        except (RankerError, TimeoutError, json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.error("ranker failed; using filter order: %s", exc)
            return _fallback(candidates)
        validated = validate_ranking(parsed, chosen)
        if validated is None:
            return _fallback(candidates)
        return validated

    def _configured(self) -> GroqSettings | None:
        if self._settings is _UNSET:
            return load_groq_settings()
        settings = self._settings
        if settings is None:
            logger.error("GROQ_API_KEY is missing; not calling Groq")
            return None
        if settings.model not in ALLOWED_MODELS:
            logger.error("GROQ_MODEL %r is not allowed; not calling Groq", settings.model)
            return None
        return settings

    def _active_limiter(self, model: str) -> UsageLimiter | None:
        if model != GPT_OSS_MODEL:
            return None
        if self._limiter is not _UNSET:
            return self._limiter
        if self._settings is not _UNSET:
            return None
        return shared_usage_limiter()

    def _post(self, settings: GroqSettings, prompt: Prompt, completion_cap: int) -> tuple[str, int | None]:
        body = json.dumps(
            {
                "model": settings.model,
                "messages": [
                    {"role": "system", "content": prompt.system},
                    {"role": "user", "content": prompt.user},
                ],
                "max_completion_tokens": completion_cap,
                "response_format": {"type": "json_object"},
                "reasoning_effort": "low",
            }
        ).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {settings.api_key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }
        url = f"{settings.base_url}/chat/completions"
        logger.info("calling Groq model=%s", settings.model)
        try:
            status, raw = self._transport(url, body, headers, TIMEOUT_SECONDS)
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            raise RetryableRankerError("Groq network failure") from exc
        if status == 429 or status >= 500:
            raise RetryableRankerError(f"Groq HTTP {status}")
        if status != 200:
            raise RankerError(f"Groq HTTP {status}")
        return _assistant_content(raw)


def load_groq_settings() -> GroqSettings | None:
    _load_env_files()
    key = os.environ.get("GROQ_API_KEY", "").strip()
    model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b").strip()
    base = os.environ.get("GROQ_API_BASE_URL", "https://api.groq.com/openai/v1").strip()
    if not key:
        logger.error("GROQ_API_KEY is missing; not calling Groq")
        return None
    if model not in ALLOWED_MODELS:
        logger.error("GROQ_MODEL %r is not allowed; not calling Groq", model)
        return None
    if not base:
        logger.error("GROQ_API_BASE_URL is missing; not calling Groq")
        return None
    return GroqSettings(key, model, base)


def parse_model_json(raw: str) -> dict:
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("model response is not a JSON object")
    if "summary" not in parsed or "recommendations" not in parsed:
        raise ValueError("model response is missing required keys")
    summary = parsed["summary"]
    if summary is not None and not isinstance(summary, str):
        raise ValueError("summary must be a string or null")
    recommendations = parsed["recommendations"]
    if not isinstance(recommendations, list):
        raise ValueError("recommendations must be a list")
    items = []
    for item in recommendations:
        if not isinstance(item, dict):
            raise ValueError("recommendation must be an object")
        rank = item.get("rank")
        explanation = item.get("explanation")
        restaurant_id = item.get("id")
        if not isinstance(restaurant_id, str) or not restaurant_id:
            raise ValueError("id must be a string")
        if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
            raise ValueError("rank must be an integer of at least 1")
        if not isinstance(explanation, str):
            raise ValueError("explanation must be a string")
        items.append({"id": restaurant_id, "rank": rank, "explanation": explanation})
    return {"summary": summary, "recommendations": items}


def validate_ranking(parsed: Mapping, candidates: Sequence[Restaurant]) -> RankResult | None:
    by_id = {record.id: record for record in candidates}
    order = {record.id: index for index, record in enumerate(candidates)}
    seen: set[str] = set()
    kept: list[dict] = []
    for item in parsed["recommendations"]:
        restaurant_id = item["id"]
        if restaurant_id not in by_id or restaurant_id in seen:
            continue
        seen.add(restaurant_id)
        kept.append(item)
    if not kept:
        return None
    kept.sort(key=lambda item: (item["rank"], order[item["id"]]))
    limit = min(RESULT_LIMIT, len(candidates))
    results = [
        _card(by_id[item["id"]], rank, _explanation(item["explanation"]))
        for rank, item in enumerate(kept[:limit], start=1)
    ]
    return RankResult("llm", _summary(parsed["summary"]), results)


def _fallback(candidates: Sequence[Restaurant]) -> RankResult:
    results = [
        _card(record, rank, None)
        for rank, record in enumerate(candidates[:RESULT_LIMIT], start=1)
    ]
    return RankResult("fallback", None, results)


def _card(record: Restaurant, rank: int, explanation: str | None) -> Recommendation:
    return Recommendation(
        rank=rank,
        name=record.name,
        cuisines=list(record.cuisines),
        rating=record.rating,
        votes=record.votes,
        estimated_cost=record.cost_for_two,
        cost_label=f"₹{record.cost_for_two} for two",
        location=record.location,
        explanation=explanation,
        id=record.id,
    )


def _summary(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value.strip()


def _explanation(value: str) -> str | None:
    text = value.strip()
    return text or None


def _assistant_content(raw: str) -> tuple[str, int | None]:
    try:
        payload = json.loads(raw)
        message = payload["choices"][0]["message"]
        content = message.get("content")
        usage = payload.get("usage") or {}
        total = usage.get("total_tokens")
        actual = int(total) if isinstance(total, int) and not isinstance(total, bool) else None
    except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValueError) as exc:
        raise RankerError("Groq response was not a chat completion") from exc
    if content is None:
        return "", actual
    if not isinstance(content, str):
        raise RankerError("Groq content was not text")
    return content, actual


def _urllib_transport(url: str, body: bytes, headers: dict[str, str], timeout: float) -> tuple[int, str]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return exc.code, detail


def _load_env_files() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        _load_env_files_fallback()
        return
    load_dotenv(ROOT / ".env", override=False)
    load_dotenv(ROOT / "tests" / ".env", override=False)


def _load_env_files_fallback() -> None:
    for path in (ROOT / ".env", ROOT / "tests" / ".env"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            name, value = text.split("=", 1)
            os.environ.setdefault(name.strip(), value.strip().strip("'\""))

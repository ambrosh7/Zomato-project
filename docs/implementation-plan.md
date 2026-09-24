# Implementation plan

Phase-wise plan for the service in [architecture.md](./architecture.md), built from [problemStatement.md](./problemStatement.md). Each phase is shippable on its own. Do not start a phase until the previous phase’s exit checks pass.

Stack: a Python API and a static page. No database, queue, login, or embeddings. The model only ranks a filtered shortlist. It must not invent restaurants, ratings, or prices.

## Model

The ranker uses Groq’s OpenAI-compatible chat API. Phase 3 does not call it. Phase 4 is the first phase that does.

| Setting | Value |
| --- | --- |
| Provider | Groq |
| `GROQ_API_BASE_URL` | `https://api.groq.com/openai/v1` |
| Default `GROQ_MODEL` | `openai/gpt-oss-120b`. Limits: 30 requests/min, 1,000 requests/day, 8,000 tokens/min, 200,000 tokens/day. Do not exceed them. Fall back instead of waiting out a daily quota. |
| Allowed alternate | `qwen/qwen3.6-27b` |
| `CATALOG_PATH` | `data/catalog.sqlite`. The app loads this file. It is not the raw Hugging Face CSV. |
| `GROQ_API_KEY` | Blank in `.env.example`. A local `.env` supplies it. Never commit the key. |

Do not substitute another host or model id unless this table changes. The alternate is selected only by setting `GROQ_MODEL`. JSON mode, timeout, and fallback stay the Phase 4 contract.

## How to use this plan

Work in order. A phase is done only when its exit checks pass. Later phases must not rewrite earlier contracts (record shape, filter order, API JSON) unless an exit check failed.

Out of scope for every phase:

- User accounts, saved history, or login
- Live Zomato scraping
- Sending `reviews_list`, `menu_item`, or `phone` to the model
- Recommendations for cities the snapshot does not contain, including Delhi

## Target layout

Create files only when the phase that owns them starts.

```text
Zomato/
  docs/
    problemStatement.md
    architecture.md
    implementation-plan.md
  src/
    models.py
    catalog.py
    filter.py
    prompt.py
    ranker.py
    api.py
  web/
    index.html
    app.js
    styles.css
  tests/
    test_catalog.py
    test_filter.py
    test_ranker.py
    test_api.py
  scripts/
    inspect_dataset.py
  .env.example
  requirements.txt
```

Suggested dependencies, added in the phase that first needs them:

- Phase 1: `datasets`. Use `pandas` only inside the inspection script if column projection needs it. Do not keep pandas on the request path.
- Phase 4: an HTTP client for Groq’s OpenAI-compatible chat API (`https://api.groq.com/openai/v1`), plus `python-dotenv`
- Phase 5: `fastapi`, `uvicorn`

---

## Phase 0 — Project skeleton

**Goal.** A runnable empty app with config, health, and a place for the catalog to load later.

**Maps to.** Project layout in architecture §9. No dataset download yet.

**Depends on.** Nothing.

**Create**

- `requirements.txt`
- `.env.example` with `CATALOG_PATH=data/catalog.sqlite`, empty `GROQ_API_KEY`, `GROQ_MODEL=openai/gpt-oss-120b`, and `GROQ_API_BASE_URL=https://api.groq.com/openai/v1`. The only other allowed model id is `qwen/qwen3.6-27b`
- `src/models.py` with dataclasses for `Restaurant`, `Preferences`, and `Recommendation` matching architecture §4.2 and the result object in §7
- `src/api.py` with `GET /health` returning `{ "status": "loading" }` until Phase 5 wires the catalog

**Tasks**

1. Pin Python 3.11+.
2. Ignore `.env`, `__pycache__`, and the Hugging Face cache in `.gitignore`.
3. Confirm the app starts and `/health` responds. Do not download the dataset yet.

**Exit checks**

- [ ] `GET /health` returns JSON `{"status":"loading"}`.
- [ ] No secrets are committed.
- [ ] `Restaurant` fields match architecture §4.2 exactly. No phone, review, menu, or address.

---

## Phase 1 — Inspect the dataset

**Goal.** Prove the raw schema and decide which rows will be dropped, before writing the catalog. This is the data-ingestion inspection from the problem statement, not the request path.

**Depends on.** Phase 0.

**Create**

- A one-off script, `scripts/inspect_dataset.py`, that is not imported by the API.

**Tasks**

1. Load `ManikaSaini/zomato-restaurant-recommendation` (`zomato.csv`). Select only the columns in architecture §4.1. Do not materialize `reviews_list` or `menu_item`.
2. The CSV reader’s default field limit will fail on those heavy columns even if they are not stored. Raise the limit, then copy only the kept columns into the working set.
3. Print row count, column names, and null counts for the kept columns.
4. Print 5 sample rows for `name`, `location`, `cuisines`, `rate`, `votes`, `approx_cost(for two people)`, `listed_in(city)`, `listed_in(type)`.
5. Count distinct `location` and `listed_in(city)` values. Confirm they are Bangalore neighborhoods, not cities such as Delhi. Note that `ITPL Main Road, Whitefield` is one location name and must not be split on the comma.
6. Count unusable `rate` values (`NEW`, `-`, empty, and anything that does not match `^\d(\.\d)?/5$`, including `4.1 /5`).
7. Count duplicate URL paths after stripping the query string.
8. Record the findings in a short comment at the top of the script only after the script exits 0. Do not write a successful schema comment after a partial download.

**Exit checks**

- [ ] Schema matches architecture §4.1, or the architecture is updated before coding continues.
- [ ] Heavy columns are never stored in the script’s working set.
- [ ] Duplicate URL-path rate is high enough that dedup is required.
- [ ] Delhi is absent, and that is written in the script comment.

**Do not.** Build the filter, the ranker, or the UI in this phase.

---

## Phase 2 — Catalog: clean, dedupe, index

**Goal.** A process-lifetime catalog of `Restaurant` records, plus location, cuisine, and budget-band lookups.

**Maps to.** Architecture §3.1 and §4.

**Depends on.** Phase 1.

**Create**

- `src/catalog.py`
- `tests/test_catalog.py`

**Tasks**

1. Implement parsers as pure functions:
   - Rating: after trim, accept only `^\d(\.\d)?/5$`. Return `None` otherwise. Do not repair internal spaces.
   - Cost: strip commas and non-digits. Return `None` if nothing remains. `0` is valid.
   - Cuisines: split on `,`, trim, drop empties, drop duplicate tokens, keep order.
   - Yes/No flags: `online_order` and `book_table` to bool. Anything other than yes is `false`. Do not drop the row.
   - URL path: strip scheme, host, and query. Hash that path for `id`. If the URL is missing, hash normalized name + location.
2. Drop rows with no name, no numeric rating, or no numeric cost.
3. Dedup by URL path. Keep the highest `votes`, then the higher rating, then the earliest dataset row.
4. Drop `phone`, `reviews_list`, `menu_item`, and `address` after dedup. They must not exist on `Restaurant`.
5. Compute budget bands once from cleaned `cost_for_two` with nearest-rank percentiles:
   - low: cost ≤ 33rd percentile
   - medium: 33rd percentile < cost ≤ 66th percentile
   - high: cost > 66th percentile
6. Build sorted unique lists of neighborhoods and cuisines. Collapse spellings that differ only by case or outer space, and display the most frequent spelling. Drop a cuisine token that normalizes to `any` from the index and log it.
7. Expose a singleton: `load()`, `is_ready()`, `status()` (`loading` | `ready` | `failed`), `get_restaurants()`, `get_meta()`.
8. Load failures set status to `failed` and log the error. They must not crash the import. A second `load()` after `ready` is a no-op. Zero restaurants after cleaning is `ready` with empty lists, not `failed`.

**Tests**

Use fixture rows. Do not call the network.

- Rating parser accepts `4.1/5` and rejects `NEW`, `-`, empty, `4.10/5`, and `4.1 /5`.
- Cost parser accepts `800` and `1,200`, and rejects a value with no digit.
- Dedup keeps the higher-vote row for the same URL path. Equal votes keep the higher rating. Equal votes and rating keep the earliest row.
- A cost equal to the 33rd percentile is `low`, not `medium`. A cost equal to the 66th percentile is `medium`, not `high`.
- A record never contains phone, reviews, menu text, or address.

**Exit checks**

- [ ] Catalog loads from Hugging Face and reports a restaurant count well below 51,717 after drops and dedup.
- [ ] Every kept record has a name, a location field, a cuisine list (possibly empty), a float rating, and an int cost.
- [ ] `get_meta()` returns locations, cuisines, and rupee ranges for the three bands, with no thousands separator.
- [ ] Tests above pass without calling the network.

---

## Phase 3 — Preference filter

**Goal.** A deterministic shortlist of at most 20 candidates. Do not call Groq in this phase.

**Maps to.** Architecture §3.2 and §5.2. This is the integration-layer filter from the problem statement. The Groq prompt and ranker are Phase 4.

**Depends on.** Phase 2.

**Create**

- `src/filter.py`
- `tests/test_filter.py`

**Tasks**

1. Accept `Preferences`: `location`, `budget` (`low` | `medium` | `high`, case-insensitive), `cuisine` (or `Any`), `min_rating`, optional `additional` (max 280 characters).
2. Apply filters in this order, and only this order:
   1. Known location. Exact normalized match on `location`. If the value is a `listed_in(city)` area and not a neighborhood, match `area`. If it is both, the neighborhood match wins.
   2. Cuisine token equals the requested cuisine, case-insensitive. Skip this step when cuisine is `Any`. Do not substring-match (`Thai` must not match `Thali`).
   3. `rating >= min_rating`.
   4. `cost_for_two` falls in the selected band.
3. Do not filter on `additional`. That text is for Groq in Phase 4.
4. Score survivors with `rating * log10(votes + 1)` and keep the top 20. Ties break by votes descending, then rating descending, then `id` ascending.
5. If none survive, return an empty list. Do not widen filters automatically.
6. Unknown location is a validation error, not an empty list. The caller turns that into HTTP 400 in Phase 5. Delhi, Bangalore, and Bengaluru are unknown. `ITPL Main Road, Whitefield` is one known location if it survived cleaning.

**Tests**

- Same input returns the same ids in the same order.
- A 4.9 rating with 3 votes ranks below a 4.3 rating with thousands of votes when both pass the filters.
- `Any` cuisine does not drop rows.
- `Italian` matches a token `Italian` inside `Cafe, Mexican, Italian`. `Thai` does not match `Thali`.
- Empty result for an impossible rating is distinct from an unknown location.
- `additional` text does not change the candidate set.

**Exit checks**

- [ ] A known Bangalore neighborhood, a real cuisine, budget `medium`, and minimum rating `3.5` returns 1 to 20 records.
- [ ] An unknown city returns a validation error, not a guessed list.
- [ ] Filter tests pass without a model and without the network.

---

## Phase 4 — Prompt, ranker, and validator

**Goal.** The model reranks the Phase 3 shortlist and writes explanations. Invalid model output never becomes user-facing facts.

**Maps to.** Architecture §3.3, §3.4, §3.5, and §6. This is the recommendation engine from the problem statement.

**Depends on.** Phase 3. Needs `GROQ_API_KEY` in the environment for the live check only. Unit tests must not call the network.

**Provider.** Groq, as specified in the Model section. Default model `openai/gpt-oss-120b`. `GROQ_MODEL=qwen/qwen3.6-27b` is the only alternate. Endpoint `POST {GROQ_API_BASE_URL}/chat/completions`.

**Create**

- `src/prompt.py`
- `src/ranker.py`
- `tests/test_ranker.py`
- `.env` locally (not committed)

**Tasks**

1. Prompt builder emits the JSON in architecture §6. Candidate objects include only `id`, `name`, `location`, `cuisines`, `rating`, `votes`, `cost_for_two`, `rest_type`, `listed_in_type`, `online_order`, `book_table`, and `dish_liked` truncated to 120 Unicode characters, not 120 bytes.
2. System instruction states: rank only provided ids, return at most 5, do not change ratings or prices, cite the user’s preferences, say when a free-text preference cannot be verified (for example “family-friendly”), and respond with JSON only.
3. `Ranker.complete(prompt) -> str` calls Groq and returns the assistant `content` string only. Use JSON mode (`response_format: {"type": "json_object"}`). Send a non-default `User-Agent` such as `restaurant-recommender/0.1` so the request is not rejected before it reaches the model. Set `reasoning_effort` to `low` and ignore any separate reasoning field. Cap completion tokens so one call cannot spend the minute budget. Timeout 20 seconds. One retry on network failure, HTTP 5xx, or HTTP 429, but only if that retry still fits `openai/gpt-oss-120b` limits (30 requests/min, 1,000 requests/day, 8,000 tokens/min, 200,000 tokens/day). No retry on bad JSON or other HTTP 4xx. A missing API key, a model id other than the two allowed ids, or a call that would exceed those limits does not call Groq. Shorten the shortlist from the low-confidence end if that is what makes the prompt fit. If it still does not fit, fall back.
4. Parser requires `{ "summary": string | null, "recommendations": [{ "id", "rank", "explanation" }] }`.
5. Validator:
   - Drop unknown ids.
   - Drop duplicate ids.
   - Overlay name, cuisines, rating, votes, cost, and location from the catalog. Ignore any facts the model added.
   - Keep at most 5, ordered by `rank`.
   - If the parsed list is empty, or the call times out, or JSON is invalid, fall back to the filter order, set `source` to `fallback`, and omit explanations.
6. If the candidate list is empty, do not call the model. That path stays in the API layer (Phase 5) as `no_matches`.

**Tests**

- Prompt JSON contains no phone, URL, address, review, or menu field.
- `dish_liked` longer than 120 characters is truncated on a character boundary.
- A response with an invented id drops that item and keeps valid ones.
- A response that changes a rating is overwritten by the catalog rating.
- Invalid JSON, including a markdown fence, yields fallback order and `source: fallback`.
- Timeout yields the same fallback.
- Fewer than 5 candidates never grows to 5.

**Exit checks**

- [ ] One live call with a real shortlist returns 1 to 5 catalog ids and non-empty explanations.
- [ ] Forcing invalid JSON (a test double) still returns catalog facts.
- [ ] Ranker tests pass with a fake `complete()`, not the live API.

---

## Phase 5 — HTTP API

**Goal.** The UI can load options and request recommendations without knowing about the catalog or the model.

**Maps to.** Architecture §7.

**Depends on.** Phases 2 and 4. The filter can be exercised through the API before the UI exists.

**Create**

- Finish `src/api.py`
- `tests/test_api.py`

**Tasks**

1. On startup, begin catalog load. `/health` returns `loading`, then `ready` or `failed`.
2. `GET /api/meta` returns locations, cuisines, and budget bands with labels:
   - `Low (up to ₹{p33} for two)`
   - `Medium (above ₹{p33} up to ₹{p66} for two)`
   - `High (above ₹{p66} for two)`
3. `POST /api/recommendations` validates:
   - location required and known, else 400 with the field name
   - budget is `low`, `medium`, or `high` after case folding
   - cuisine required (`Any` allowed)
   - `min_rating` is between 0 and 5
   - `additional` is optional and at most 280 characters
4. If the catalog is not `ready`, return 503.
5. If the filter returns no rows, return `no_matches` with the three suggestions from architecture §7, in that order. Do not call the ranker.
6. Otherwise call the ranker and return the success shape from architecture §7, including `source`, `summary`, and `cost_label` formatted as `₹{cost} for two`.
7. Serve `web/` as static files so one process hosts the page and the API. CORS is unnecessary if the page is same-origin.

**Tests**

- Unknown location, including `Delhi`, returns 400, not 200 with an empty list.
- Catalog `failed` or `loading` returns 503.
- An empty filter returns `no_matches` and the ranker is not called (inject a spy).
- A success response uses catalog cost and rating even if the ranker double returns different numbers.
- A ranker failure still returns 200 with `source: fallback` when candidates exist.

**Exit checks**

- [ ] `GET /api/meta` lists real neighborhoods from the loaded catalog.
- [ ] A sample POST for a known neighborhood returns `status: ok` and at most 5 results.
- [ ] A POST with `location: "Delhi"` returns 400.

---

## Phase 6 — Web UI

**Goal.** One page that collects the problem statement’s preferences and shows the required result fields.

**Maps to.** Architecture §5.1 and §8.

**Depends on.** Phase 5. Do not hard-code locations, cuisines, or rupee cutoffs.

**Create**

- `web/index.html`
- `web/app.js`
- `web/styles.css`

**Tasks**

1. On load, call `GET /api/meta`. If health is not `ready`, show an inline loading or failed message and do not submit.
2. Form fields:
   - Location: searchable select filled from `meta.locations`
   - Budget: three options whose labels include the rupee range
   - Cuisine: searchable select plus `Any`
   - Minimum rating: 0 to 5 in steps of 0.5, default 3.5
   - Additional preferences: optional textarea, maxlength 280
3. Submit calls `POST /api/recommendations`. Disable the button while the request is in flight.
4. Results state:
   - Summary paragraph when `summary` is present
   - Up to five cards: name, cuisines, rating, vote count, `cost_label`, explanation
   - If `source` is `fallback`, one notice that explanations are unavailable and the list is sorted by rating and votes. Do not invent explanation copy.
5. Empty state shows `message` and `suggestions` from the API.
6. 400 and 503 render inline. Clear previous cards so a stale list is not read as the new answer. Insert names and explanations as text, not HTML. No second page.

**Exit checks**

- [x] A user can pick a Bangalore neighborhood and see name, cuisine, rating, estimated cost, and an explanation.
- [x] Budget labels show rupees from `/api/meta`, not hard-coded cutoffs.
- [x] An impossible filter shows the three suggestions, not a blank page.
- [x] Fallback responses do not display fake explanations.

---

## Phase 7 — End-to-end checks

**Goal.** Prove the three paths the architecture calls done: a normal recommendation, no matches, and a forced model failure.

**Depends on.** Phase 6.

**Tasks**

1. Normal path: a neighborhood that has Italian (or another common cuisine), budget `medium`, minimum rating 3.5. Expect 1 to 5 cards, `source: llm`, catalog-matching rating and cost.
2. Empty path: minimum rating 5.0 and a rare cuisine in a small neighborhood, or any combination already known to return no rows. Expect `no_matches` and no model call in the server log.
3. Failure path: point `GROQ_API_BASE_URL` at an invalid host, or use a test flag that makes `complete()` raise. Expect `source: fallback`, facts still present, no explanation text invented by the page.
4. Confirm the prompt log, if any, does not contain phone numbers or review text. Prefer not logging the full prompt.
5. Confirm startup with the dataset host unreachable still serves `/health` as `failed` and recommendations as 503.

**Exit checks**

- [x] All three paths behave as specified in architecture §10 and §12.
- [x] A user can submit Bangalore preferences and see up to five restaurants whose name, cuisine, rating, and cost come from the catalog, plus an explanation that only refers to those restaurants.

This is the definition of done. Do not add accounts, embeddings, or a live scrape after this point unless the problem statement changes.

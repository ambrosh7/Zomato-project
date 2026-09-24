# Edge cases

Corner cases for [implementation-plan.md](./implementation-plan.md). Each case has one expected result. If a test and this file disagree, fix the test, not this file, unless [architecture.md](./architecture.md) has changed.

A case is covered only when the named test, or the Phase 7 check, asserts the expected result. Do not handle a case by calling the model to invent a restaurant, rating, or price.

## Rules that pin ambiguous boundaries

These are easy to implement two different ways. Use only these rules.

| Boundary | Rule |
| --- | --- |
| Rating | After trim, accept only `^\d(\.\d)?/5$`. One digit, optional one decimal digit, then `/5`. No internal spaces. Do not repair `4.1 /5`. |
| Cost | Strip commas and every non-digit. If no digit remains, drop the row. `0` is a valid cost. |
| Cuisine match | Compare the requested cuisine to each token after splitting on `,`. Case-insensitive equality. Not a substring of another token. |
| `Any` | Sentinel, not a stored cuisine. Match case-insensitively. Skip the cuisine filter. |
| Budget word | Accept `low`, `medium`, `high` case-insensitively. Store lowercase. |
| Budget cutoffs | Nearest-rank percentile on cleaned `cost_for_two`. `low` is `<= p33`. `medium` is `> p33` and `<= p66`. `high` is `> p66`. |
| Location | Lowercase and collapse internal whitespace. Neighborhood exact match first. If the value is only a `listed_in(city)` area, match `area`. No fuzzy match. Do not split location on commas. |
| Unknown vs empty | Unknown location or unknown cuisine is HTTP 400. A known location with zero survivors is `no_matches`, not 400. |
| Tie on confidence | Sort by score descending, then `votes` descending, then `rating` descending, then `id` ascending. Same input, same 20 ids. |
| Dedup tie | Highest `votes`, then highest `rating`, then earliest dataset row. |
| Model facts | Name, cuisines, rating, votes, cost, and location always come from the catalog. |
| Empty filter | Do not call the model. |
| Truncation | `dish_liked` is truncated to 120 Unicode characters, not 120 bytes. |
| CSV field size | Raise the reader limit so a huge `reviews_list` cell can be scanned, then drop it. Never store it. |

---

## Phase 0 — Skeleton

| Case | Expected |
| --- | --- |
| App starts before the dataset is wired | `GET /health` returns `{ "status": "loading" }`. It does not download Hugging Face. |
| `.env` exists locally | It is gitignored. `.env.example` has `CATALOG_PATH=data/catalog.sqlite`, empty `GROQ_API_KEY`, `GROQ_MODEL=openai/gpt-oss-120b`, and `GROQ_API_BASE_URL=https://api.groq.com/openai/v1`. The only other allowed model id is `qwen/qwen3.6-27b`. |
| `Restaurant` gains a phone, review, menu, or address field | Phase 0 exit fails. Those fields are not on the dataclass. |
| Python earlier than 3.11 | The app refuses to start. |

---

## Phase 1 — Dataset inspection

| Case | Expected |
| --- | --- |
| `reviews_list` or `menu_item` is selected into the working set | Fail the script. Those columns are not stored. |
| A review cell is larger than the CSV reader’s default 128KB limit | Raise the field limit, scan past the cell, and still do not store it. |
| A raw column is missing or renamed | Stop. Update the architecture before Phase 2. Do not guess a mapping. |
| Download fails, cache is corrupt, or disk fills | Script exits with an error. It does not write a successful schema comment. |
| `location` values are Bangalore neighborhoods, and Delhi is absent | Record that in the script comment. Do not add Delhi as a supported city. |
| A location value is `ITPL Main Road, Whitefield` | Count it as one location. Do not split on the comma. |
| Rate values include `NEW`, `-`, blank, `4.1 /5`, and other regex failures | Count them. Phase 2 will drop those rows and must not repair the space. |
| Same restaurant URL appears with different query strings | Count them as one URL path. Dedup is required. |
| `votes` is an integer, including a viewer display of `2,556` | Treat the column as an integer. Do not parse the viewer’s display string. |
| `pandas` is used for exploration | Allowed only inside `scripts/inspect_dataset.py`. Not imported by the API. |

---

## Phase 2 — Catalog cleaning and dedup

### Rating

| Input | Expected |
| --- | --- |
| `4.1/5` | `4.1`. Keep the row if cost and name exist. |
| `4/5`, `5/5`, `0/5` | `4.0`, `5.0`, `0.0`. |
| `  4.1/5  ` | Trim, then `4.1`. |
| `NEW`, `new`, `-`, `""`, `null` | Drop the row. |
| `4.1`, `4.1/10`, `4.10/5`, `10/5`, `-1/5` | Drop the row. The regex does not allow these. |
| `4.1 /5`, `4.1/ 5`, `4.1 / 5` | Drop the row. Do not repair internal spaces. |

### Cost

| Input | Expected |
| --- | --- |
| `800` | `800`. |
| `1,200` | `1200`. |
| `₹800`, `800 for two` | `800`. Non-digits are stripped. |
| `""`, `null`, `-`, `?` | Drop the row. No digit remains. |
| `0` | Keep. Cost is `0`. |

### Names, cuisines, flags

| Case | Expected |
| --- | --- |
| Name is null or whitespace | Drop the row. |
| Name has a straight UTF-8 mojibake sequence that decodes cleanly | Store the decoded name. |
| Name is still garbled after that decode | Store it unchanged. Do not invent a corrected name. |
| Cuisines `North Indian, Mughlai, Chinese` | `["North Indian", "Mughlai", "Chinese"]`. |
| `Italian,`, ` Italian `, `Italian,,Chinese` | `["Italian"]` or `["Italian", "Chinese"]`. Empty tokens dropped. |
| Cuisines null or `""` | Keep the row with `cuisines: []` if name, rating, and cost exist. |
| Duplicate tokens `Cafe, Cafe` | One `Cafe`, original order kept. |
| A token that normalizes to `any` | Drop that token from the cuisine index so the sentinel stays unique. Log it. |
| `online_order` / `book_table` is `Yes` or `No` | `true` / `false`. Case-insensitive. |
| Flag is null or any other string | `false`. Do not drop the row. |
| `rest_type`, `listed_in(type)`, or `dish_liked` is null | Store empty string or null. Do not drop the row. |
| Unexpected `listed_in(type)` | Keep the string. Do not restrict to the seven known types. |

### Identity and dedup

| Case | Expected |
| --- | --- |
| URL has a query string | Dedup key is the path only. Query is ignored. |
| Two rows, same path, votes 100 and 40 | Keep votes 100. |
| Same path, equal votes, ratings 4.2 and 3.9 | Keep 4.2. |
| Same path, equal votes, equal rating | Keep the earliest dataset row. |
| URL missing | Id is a hash of normalized name + location. |
| Two rows with no URL and the same name + location | Treat as one group. Apply the same tie rules. |
| Same display name, different URL paths | Keep both. Location on the card is what separates them. |
| `phone`, `reviews_list`, `menu_item` present on the raw row | Absent from `Restaurant` and from any object the ranker can see. |
| `address` after dedup | Not stored on `Restaurant`. Address is not the fallback dedup key. |

### Budget bands and meta

| Case | Expected |
| --- | --- |
| Cost equal to p33 | `low`, not `medium`. |
| Cost equal to p66 | `medium`, not `high`. |
| Cost one rupee above p33 and at or below p66 | `medium`. |
| Cost one rupee above p66 | `high`. |
| Every cleaned cost is the same | p33 equals p66. Every restaurant is `low`. `medium` and `high` match nothing. Do not move restaurants into those bands to avoid an empty range. |
| One restaurant left after cleaning | Same as the all-equal case. |
| Zero restaurants left after cleaning | Load status is `ready`, not `failed`. Meta lists are empty. Recommendations cannot return `ok`. |
| Location spellings differ only by case or outer space | One meta entry. Display the most frequent trimmed spelling. |
| Meta rupee labels | `Low (up to ₹{p33} for two)`, `Medium (above ₹{p33} up to ₹{p66} for two)`, `High (above ₹{p66} for two)`. No thousands separator. |

### Load failures

| Case | Expected |
| --- | --- |
| Hugging Face unreachable at startup | Status `failed`. Log the error. Do not crash the process on import. |
| Partial cache or interrupted download | Status `failed`. Do not serve a half-built catalog. |
| Second `load()` after `ready` | No-op. The catalog stays read-only. |
| Import of `catalog.py` | Does not download the dataset. Status stays `loading` until `load()` is called. |

---

## Phase 3 — Filter

### Location

| Input | Expected |
| --- | --- |
| Exact neighborhood, any case, extra internal spaces collapsed | Match `location`. |
| Value is a `listed_in(city)` area and not a neighborhood | Match `area`. |
| Value is both a neighborhood and an area | Neighborhood match wins. |
| `ITPL Main Road, Whitefield` | One known location if it survived cleaning. Do not split it into `ITPL Main Road` and `Whitefield`. |
| `Delhi`, `Bangalore`, `Bengaluru`, `Indira Nagar` | Validation error. No fuzzy match and no model call. |
| `""`, whitespace, null | Validation error. |
| Neighborhood with zero survivors after the other filters | Empty candidate list, not a validation error. |

### Cuisine, rating, budget, extra text

| Case | Expected |
| --- | --- |
| Cuisine `Italian` against tokens `["Pizza", "Cafe", "Italian"]` | Keep. |
| Cuisine `italian` | Keep. Case-insensitive. |
| Cuisine `Any` or `any` | Do not apply the cuisine filter. |
| Cuisine `Thai` against token `Thali` | Drop. Token equality, not substring. |
| Cuisine `Indian` against token `North Indian` | Drop. The token is not `Indian`. |
| Cuisine not in the index and not `Any` | Validation error. |
| Restaurant with `cuisines: []` and cuisine `Any` | Can survive the other filters. |
| Restaurant with `cuisines: []` and cuisine `Italian` | Drop. |
| Rating equal to `min_rating` | Keep. |
| Rating just below `min_rating` | Drop. |
| `min_rating` 0 | Rating filter keeps every numeric rating, including `0.0`. |
| `min_rating` 5 when nothing is rated 5 | Empty list, not an error. |
| Cost on the p33 boundary, budget `low` | Keep. |
| Same cost, budget `medium` | Drop. |
| `additional` is empty, whitespace, or a long sentence | Candidate ids do not change. It is not a filter. |
| `additional` longer than 280 characters | Validation error. Exactly 280 is allowed. |

### Ranking cut

| Case | Expected |
| --- | --- |
| 4.9 rating with 3 votes vs 4.3 with thousands of votes | The high-vote row ranks higher. Score is `rating * log10(votes + 1)`. |
| `votes` is 0 | Score is 0. The row can still be a candidate. |
| `votes` is missing or negative | Treat as 0. Do not drop the row for votes alone. |
| Two rows with the same score | Order by votes, then rating, then `id`. |
| 21 rows pass the filters | Return 20. The 21st is excluded even if its score ties the 20th, using the tie rule above. |
| 1 to 20 rows pass | Return all of them. Do not pad. |
| Same preferences twice | Identical id order. |

---

## Phase 4 — Prompt, ranker, validator

### What may enter the prompt

| Case | Expected |
| --- | --- |
| Candidate payload | Only `id`, `name`, `location`, `cuisines`, `rating`, `votes`, `cost_for_two`, `rest_type`, `listed_in_type`, `online_order`, `book_table`, `dish_liked`. |
| Phone, URL, address, reviews, menu | Not in the prompt. Not in logs of the prompt if logging is added. |
| `dish_liked` of 120 characters | Sent in full. |
| `dish_liked` of 121 characters, or a multi-byte character on the boundary | Cut to 120 characters. Do not split a character. |
| Zero candidates | Ranker is not called. This is enforced again in Phase 5. |
| Fewer than 5 candidates | Prompt says return only those. Response must not grow past the candidate count. |

### Model output

| Case | Expected |
| --- | --- |
| Valid JSON, every id in the candidate set, at most 5 | `source: llm`. Facts overlaid from the catalog. |
| Model changes rating, cost, name, or cuisine | Discard the model’s facts. Use the catalog. |
| Invented id mixed with valid ids | Drop the invented id. Keep the valid ones. |
| All ids invented, or the list is empty after drops | Fallback: filter order, `source: fallback`, no explanations. |
| Duplicate ids | Keep the first occurrence. |
| More than 5 items | Keep 5, ordered by `rank`. |
| `rank` missing, not an integer, or less than 1 | Whole response is invalid. Fallback. |
| Same `rank` on two valid ids | Keep both if still within 5. Order those two by filter order. |
| `explanation` is empty or whitespace | Keep the card facts. Omit the explanation. Do not write a substitute sentence. |
| `summary` is null, empty, or whitespace | Treat as null. UI shows no summary paragraph. |
| JSON wrapped in a markdown fence, or extra prose around JSON | Invalid. Fallback. Do not partially parse prose. |
| Extra unexpected keys | Ignore the keys. Do not fail if the required shape is present. |
| Response is a list, or `recommendations` is an object | Fallback. |
| Timeout, connection error, or HTTP 5xx | Retry once. If that fails, fallback. |
| HTTP 4xx other than 429 (bad key, bad request) | Do not retry. Fallback. |
| HTTP 429 | Retry once, then fallback. |
| Schema or JSON failure | No retry. Fallback. |
| `GROQ_API_KEY` missing | Do not call Groq. Fallback whenever candidates exist. Log the config error. Health can still be `ready`. |
| `openai/gpt-oss-120b` call would exceed 30 requests/min, 1,000 requests/day, 8,000 tokens/min, or 200,000 tokens/day | Do not send the request. Do not wait out a daily quota. Fallback. Count a retry as another request. |
| Prompt plus reserved completion exceeds the remaining token budget | Drop low-confidence candidates until it fits. If one candidate still does not fit, fallback. |
| Usage file from an earlier process in the same day | Keep counting. Restarting the app must not reset the daily quota. |
| User text says to ignore instructions and add a restaurant that is not in the list | Validator drops any unknown id. The injected restaurant is never returned. |
| Fewer than 5 candidates, and the model adds ids to fill five | Extra ids dropped. Result length stays within the candidate set. |

### Free-text preferences the model must not invent

These are prompt and evaluation cases. A unit test can only assert that the instruction is in the prompt. A live check belongs in Phase 7.

| Preference | Expected explanation behavior |
| --- | --- |
| `quick service`, and a candidate has `Quick Bites` or `online_order: true` | May cite that field. |
| `quick service`, and neither signal is present | Must not claim quick service as a fact. |
| `family-friendly` | No catalog field supports it. Must say it cannot be verified. Must not claim the restaurant is family-friendly. |
| `additional` omitted | Explanations cite location, cuisine, budget, and rating only. They do not mention a missing preference. |

---

## Phase 5 — API

| Case | Expected |
| --- | --- |
| Catalog `loading` or `failed` | 503 on `/api/meta` and `/api/recommendations`. `/health` reports that status. |
| Requests arrive while load is in progress | 503. They do not start a second load. |
| Body is not JSON, or the body is missing | 400. |
| `location` missing, unknown, or a city outside the catalog (`Delhi`, `Bangalore`) | 400 with the field name `location`. Body is not `no_matches`. |
| `budget` missing or not low/medium/high after case folding | 400 with field `budget`. |
| `cuisine` missing, or not in the index and not `Any` | 400 with field `cuisine`. |
| `min_rating` missing, not a number, below 0, or above 5 | 400 with field `min_rating`. |
| `min_rating` is the string `"3.5"` or the number `3.5` | Accept as 3.5. |
| `additional` omitted, null, or `""` | Accept. Treat as no extra preference. |
| `additional` is 281 characters, or not a string | 400 with field `additional`. |
| Extra unknown JSON keys | Ignore. |
| `GET /api/recommendations` | 405. |
| Filter returns no rows | 200, `status: no_matches`, the three suggestions in order. Ranker spy is not called. |
| Ranker returns a valid ranking | 200, `status: ok`, `source: llm`, at most 5 results. |
| Ranker falls back | 200, not 500. `source: fallback`. Facts present. `explanation` omitted on each result. |
| `cost_label` | Exactly `₹{cost_for_two} for two`. Cost 1200 is `₹1200 for two`, not `₹1,200`. |
| `votes` on the result | The catalog integer, including 0. |

`no_matches` suggestions are only these three, in this order:

1. Lower the minimum rating
2. Choose Any cuisine
3. Widen the budget

---

## Phase 6 — UI

| Case | Expected |
| --- | --- |
| Page load while `/health` is not `ready` | Inline message. Submit stays disabled. No request. |
| `/api/meta` fails | Inline error. Location and cuisine selects are not filled with placeholders such as Delhi. |
| Submit before meta returns | No request. The button is disabled. |
| Budget labels | Rupee text from meta. `app.js` has no hard-coded cutoff. |
| Double submit | One in-flight request. Button disabled until it finishes. |
| `status: ok`, `source: llm` | Up to five cards: name, cuisines, rating, votes, `cost_label`, explanation. Summary only if non-null. |
| `source: fallback` | One notice that explanations are unavailable and the list is sorted by rating and votes. No generated explanation text in the page. |
| `explanation` missing on an `llm` card | Show the facts. Do not render `undefined` or a made-up sentence. |
| `no_matches` | Show `message` and the three suggestions. No empty card list presented as success. |
| 400 or 503 | Inline error. The previous results are cleared so a stale list is not read as the new answer. |
| Restaurant name or explanation contains `<script>` or HTML | Insert as text, not HTML. |
| Very long explanation or name | Card wraps. Layout does not overflow the page into an unreadable line. |
| Cuisine list empty on a card | Show the other facts. Do not show a fake cuisine. |
| Catalog restarted with new bands | A full reload picks up new meta. The page does not cache rupee cutoffs across reloads. |

---

## Phase 7 — Paths that must be walked once

| Path | Setup | Expected |
| --- | --- | --- |
| Normal | Known neighborhood, a cuisine that exists there, budget `medium`, minimum rating 3.5 | 1 to 5 cards, `source: llm`, rating and cost match the catalog ids. |
| Empty | Known location, filter that matches nothing | `no_matches`. Server log shows no model call. |
| Model down | Invalid `GROQ_API_BASE_URL`, or a test flag that makes `complete()` raise | `source: fallback`, facts present, UI notice, no invented explanations. |
| City outside the snapshot | `location: "Delhi"` | 400. No cards. |
| Secret leakage | Inspect the prompt if it is logged | No phone number and no review text. |
| Cold start, no network | Process starts with the dataset host unreachable | `/health` is `failed`. Recommendation routes return 503. |

---

## Cases that are not bugs

Do not add code for these.

| Tempting case | Why it is out of scope |
| --- | --- |
| User wants Delhi, Bangalore as a city, or another city | The snapshot cannot support it. 400 is correct. |
| User wants a saved account or past searches | No identity in the requirements. |
| Free text asks for a restaurant not in the shortlist | The model must not add it. |
| Two outlets share a name | Both can appear. Location distinguishes them. |
| Medium and high are empty because every cost is equal | Correct under the percentile rules. |
| Explanations missing because the model is down | Fallback facts are the product behavior, not a blank error. |
| A spaced rating such as `4.1 /5` is dropped | Correct. Do not repair it to keep more rows. |

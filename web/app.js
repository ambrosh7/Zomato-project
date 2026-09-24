const form = document.querySelector("#finder");
const statusNode = document.querySelector("#status");
const locationInput = document.querySelector("#location");
const locationOptions = document.querySelector("#location-options");
const cuisineInput = document.querySelector("#cuisine");
const cuisineOptions = document.querySelector("#cuisine-options");
const budgetOptions = document.querySelector("#budget-options");
const ratingSelect = document.querySelector("#min-rating");
const ratingDown = document.querySelector("#rating-down");
const ratingUp = document.querySelector("#rating-up");
const additional = document.querySelector("#additional");
const additionalCount = document.querySelector("#additional-count");
const submitButton = document.querySelector("#submit");
const resultsNode = document.querySelector("#results");
const metaPill = document.querySelector("#meta-pill");
const metaPillLabel = document.querySelector("#meta-pill-label");
const catalogCount = document.querySelector("#catalog-count");

const locations = new Set();
const cuisines = new Set(["Any"]);
let ready = false;
let inFlight = false;
let selectedCuisine = "";

for (let rating = 0; rating <= 5.0001; rating += 0.5) {
  const option = document.createElement("option");
  option.value = rating.toFixed(1);
  option.textContent = rating.toFixed(1);
  if (rating === 3.5) option.selected = true;
  ratingSelect.append(option);
}

additional.addEventListener("input", () => {
  additionalCount.textContent = `${additional.value.length} / 280`;
});

ratingDown.addEventListener("click", () => stepRating(-0.5));
ratingUp.addEventListener("click", () => stepRating(0.5));

form.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!ready || inFlight) return;
  const location = locationInput.value.trim();
  const cuisine = cuisineInput.value.trim();
  if (!locations.has(location) || !cuisines.has(cuisine)) {
    showStatus("Choose a location and cuisine from the list.");
    return;
  }
  const budget = form.querySelector("input[name='budget']:checked");
  if (!budget) return;
  selectedCuisine = cuisine;
  requestRecommendations({
    location,
    budget: budget.value,
    cuisine,
    min_rating: Number(ratingSelect.value),
    additional: additional.value,
  });
});

boot();

async function boot() {
  setReady(false);
  setMetaState("loading", "Connecting catalog");
  showStatus("Loading restaurants…");
  const health = await waitUntilSettled();
  if (health !== "ready") {
    setMetaState("failed", health === "failed" ? "Catalog failed" : "Still loading");
    showStatus(health === "failed" ? "The catalog failed to load." : "Restaurants are still loading.");
    return;
  }
  try {
    const response = await fetch("/api/meta");
    if (!response.ok) {
      setMetaState("failed", "Meta unavailable");
      showStatus("Restaurant options are unavailable.");
      return;
    }
    const meta = await response.json();
    fillForm(meta);
    const n = Array.isArray(meta.locations) ? meta.locations.length : 0;
    catalogCount.textContent = `${n} neighborhoods`;
    setMetaState("ready", "API meta connected");
    hideStatus();
    setReady(true);
  } catch {
    setMetaState("failed", "Meta unavailable");
    showStatus("Restaurant options are unavailable.");
  }
}

async function waitUntilSettled() {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try {
      const response = await fetch("/health");
      if (response.ok) {
        const body = await response.json();
        if (body.status === "ready" || body.status === "failed") return body.status;
      }
    } catch {
      return "failed";
    }
    await delay(500);
  }
  return "loading";
}

function fillForm(meta) {
  locationOptions.replaceChildren();
  cuisineOptions.replaceChildren();
  budgetOptions.replaceChildren();
  locations.clear();
  cuisines.clear();
  cuisines.add("Any");

  for (const location of meta.locations || []) {
    locations.add(location);
    locationOptions.append(option(location));
  }
  cuisineOptions.append(option("Any"));
  for (const cuisine of meta.cuisines || []) {
    cuisines.add(cuisine);
    cuisineOptions.append(option(cuisine));
  }
  for (const band of meta.budget_bands || []) {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "budget";
    input.value = band.id;
    input.required = true;
    if (band.id === "medium") input.checked = true;

    const title = document.createElement("span");
    title.className = "choice-title";
    title.textContent = budgetTitle(band);

    const copy = document.createElement("span");
    copy.className = "choice-copy";
    copy.textContent = budgetCopy(band);

    label.append(input, title, copy);
    budgetOptions.append(label);
  }
}

function budgetTitle(band) {
  const label = String(band.label || band.id || "");
  const head = label.split("(")[0].trim();
  return head || String(band.id || "");
}

function budgetCopy(band) {
  const label = String(band.label || "");
  const match = label.match(/\((.+)\)/);
  if (match) return match[1];
  return label;
}

async function requestRecommendations(payload) {
  inFlight = true;
  submitButton.disabled = true;
  clearResults();
  hideStatus();
  try {
    const response = await fetch("/api/recommendations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await response.json();
    if (!response.ok) {
      showStatus(response.status === 503 ? "Restaurants are not ready yet." : "Check the highlighted preferences and try again.");
      return;
    }
    render(body);
  } catch {
    showStatus("The request did not finish. Try again.");
  } finally {
    inFlight = false;
    submitButton.disabled = !ready;
  }
}

function render(body) {
  clearResults();
  if (body.status === "no_matches") {
    const box = document.createElement("div");
    box.className = "empty";
    const kicker = document.createElement("div");
    kicker.className = "empty-kicker";
    kicker.textContent = "No matches";
    const message = document.createElement("p");
    message.textContent = body.message || "";
    const list = document.createElement("ol");
    for (const suggestion of body.suggestions || []) {
      const item = document.createElement("li");
      item.textContent = suggestion;
      list.append(item);
    }
    box.append(kicker, message, list);
    resultsNode.append(box);
    return;
  }
  if (body.source === "fallback") {
    const notice = document.createElement("p");
    notice.className = "notice";
    notice.textContent = "Explanations are unavailable and the list is sorted by rating and votes.";
    resultsNode.append(notice);
  }
  if (body.summary) {
    const summary = document.createElement("div");
    summary.className = "summary";
    const kicker = document.createElement("div");
    kicker.className = "summary-kicker";
    const icon = document.createElement("span");
    icon.className = "material-symbols-outlined";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = "neurology";
    const label = document.createElement("span");
    label.textContent = "Curator Synthesis · POST /api/recommendations";
    kicker.append(icon, label);
    const text = document.createElement("p");
    text.textContent = body.summary;
    summary.append(kicker, text);
    resultsNode.append(summary);
  }
  const cards = body.results || [];
  cards.forEach((card, index) => resultsNode.append(renderCard(card, index + 1)));
}

function renderCard(card, rank) {
  const article = document.createElement("article");
  article.className = "card";

  const top = document.createElement("div");
  top.className = "card-top";

  const badge = document.createElement("span");
  badge.className = rank === 1 ? "rank-badge is-top" : "rank-badge";
  badge.textContent = `Rank #${rank}`;

  const name = document.createElement("h2");
  name.textContent = card.name || "";

  top.append(badge, name);
  article.append(top);

  if (Array.isArray(card.cuisines) && card.cuisines.length) {
    const chips = document.createElement("div");
    chips.className = "chips";
    for (const cuisine of card.cuisines) {
      const chip = document.createElement("span");
      chip.className = cuisineMatches(cuisine) ? "chip is-match" : "chip";
      chip.textContent = cuisine;
      chips.append(chip);
    }
    article.append(chips);
  }

  const meta = document.createElement("div");
  meta.className = "card-meta";

  const rating = document.createElement("span");
  rating.className = "rating-token";
  const star = document.createElement("span");
  star.className = "material-symbols-outlined";
  star.setAttribute("aria-hidden", "true");
  star.textContent = "star";
  const ratingValue = document.createElement("span");
  ratingValue.textContent = String(card.rating ?? "");
  rating.append(star, ratingValue);

  const votes = document.createElement("span");
  votes.textContent = `(${card.votes ?? 0} votes)`;

  const cost = document.createElement("span");
  cost.className = "cost-token";
  cost.textContent = card.cost_label || "";

  meta.append(
    rating,
    sep(),
    votes,
    sep(),
    cost,
  );

  if (card.location) {
    meta.append(sep());
    const location = document.createElement("span");
    location.className = "card-location";
    location.textContent = card.location;
    meta.append(location);
  }

  article.append(meta);

  if (card.explanation) {
    const explanation = document.createElement("div");
    explanation.className = "explanation";
    const icon = document.createElement("span");
    icon.className = "material-symbols-outlined explanation-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = "verified";
    const text = document.createElement("p");
    text.textContent = card.explanation;
    explanation.append(icon, text);
    article.append(explanation);
  }

  return article;
}

function cuisineMatches(cuisine) {
  if (!selectedCuisine || selectedCuisine === "Any") return false;
  return String(cuisine).toLowerCase() === selectedCuisine.toLowerCase();
}

function sep() {
  const node = document.createElement("span");
  node.className = "meta-sep";
  node.textContent = "·";
  return node;
}

function option(value) {
  const node = document.createElement("option");
  node.value = value;
  return node;
}

function stepRating(delta) {
  const current = Number(ratingSelect.value);
  const next = Math.min(5, Math.max(0, current + delta));
  ratingSelect.value = next.toFixed(1);
}

function setReady(value) {
  ready = value;
  for (const control of form.elements) {
    if (control !== submitButton) control.disabled = !value;
  }
  ratingDown.disabled = !value;
  ratingUp.disabled = !value;
  submitButton.disabled = !value || inFlight;
}

function setMetaState(state, label) {
  metaPill.dataset.state = state;
  metaPillLabel.textContent = label;
}

function showStatus(text) {
  statusNode.hidden = false;
  statusNode.textContent = text;
}

function hideStatus() {
  statusNode.hidden = true;
  statusNode.textContent = "";
}

function clearResults() {
  resultsNode.replaceChildren();
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

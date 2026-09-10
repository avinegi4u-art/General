const form = document.getElementById("search-form");
const queryInput = document.getElementById("query");
const countrySelect = document.getElementById("country");
const currencySelect = document.getElementById("currency");
const searchBtn = document.getElementById("search-btn");
const statusEl = document.getElementById("status");
const errorEl = document.getElementById("error");
const notesEl = document.getElementById("notes");
const picksEl = document.getElementById("picks");
const moreEl = document.getElementById("more");
const moreList = document.getElementById("more-list");

const TZ_TO_COUNTRY = {
  "Asia/Dubai": "AE",
  "Asia/Muscat": "OM",
  "Asia/Riyadh": "SA",
  "Asia/Qatar": "QA",
  "Asia/Kuwait": "KW",
  "Asia/Bahrain": "BH",
  "Africa/Cairo": "EG",
  "Asia/Kolkata": "IN",
  "Asia/Calcutta": "IN",
  "Asia/Karachi": "PK",
  "America/New_York": "US",
  "America/Chicago": "US",
  "America/Denver": "US",
  "America/Los_Angeles": "US",
  "Europe/London": "GB",
  "Europe/Berlin": "DE",
  "America/Toronto": "CA",
  "Australia/Sydney": "AU",
};

const COUNTRY_EXAMPLES = {
  AE: ["wireless earbuds under 200 AED", "noise cancelling headphones", "office chair under 500 AED"],
  IN: ["wireless earbuds under 2000 INR", "noise cancelling headphones", "office chair under 8000 INR"],
  SA: ["wireless earbuds under 200 SAR", "noise cancelling headphones"],
  US: ["wireless earbuds under $40", "noise cancelling headphones"],
  GB: ["wireless earbuds under £40", "noise cancelling headphones"],
  QA: ["wireless earbuds under 200 QAR", "noise cancelling headphones"],
};

let currencyTouched = false;

function show(el, text) {
  el.hidden = false;
  if (typeof text === "string") {
    el.textContent = text;
  }
}

function hide(el) {
  el.hidden = true;
  el.textContent = "";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatRating(item) {
  if (!item || item.rating == null) {
    return "No rating";
  }
  const mark = item.rating_is_default ? " (default)" : "";
  const count = item.review_count ? ` · ${item.review_count} reviews` : "";
  return `${Number(item.rating).toFixed(1)}/5${mark}${count}`;
}

function formatPrice(item) {
  return item?.price_display || "Price unknown";
}

function availabilityClass(item) {
  const kind = item?.availability || "unknown";
  return `ship-badge ${escapeHtml(kind)}`;
}

function availabilityText(item) {
  return item?.availability_label || "Availability unclear";
}

function renderCard(pick) {
  const item = pick.item;
  if (!item) {
    return `
      <article class="card ${escapeHtml(pick.id)}">
        <p class="badge">${escapeHtml(pick.label)}</p>
        <h3>No pick yet</h3>
        <p class="why">${escapeHtml(pick.blurb)}</p>
        <p class="empty">Nothing in this category for this query.</p>
      </article>
    `;
  }
  const scores = item.scores || {};
  return `
    <article class="card ${escapeHtml(pick.id)}">
      <p class="badge">${escapeHtml(pick.label)}</p>
      <p class="${availabilityClass(item)}">${escapeHtml(availabilityText(item))}</p>
      <h3>${escapeHtml(item.title)}</h3>
      <p class="meta">${escapeHtml(item.source_domain)} · ${escapeHtml(formatRating(item))}</p>
      <p class="price">${escapeHtml(formatPrice(item))}</p>
      <p class="why">${escapeHtml(item.description || pick.blurb)}</p>
      <p class="scores">Match ${Number(scores.relevance || 0).toFixed(2)} · Price ${Number(scores.price || 0).toFixed(2)} · Ships ${Number(scores.availability || 0).toFixed(2)} · Overall ${Number(scores.overall || 0).toFixed(2)}</p>
      <a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">Open listing</a>
    </article>
  `;
}

function renderMore(items, winners) {
  const winnerUrls = new Set(winners.filter(Boolean).map((item) => item.url));
  const extras = (items || []).filter((item) => !winnerUrls.has(item.url)).slice(0, 8);
  if (!extras.length) {
    hide(moreEl);
    moreList.innerHTML = "";
    return;
  }
  moreList.innerHTML = extras
    .map(
      (item) => `
        <div class="row">
          <a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.title)}</a>
          <span>${escapeHtml(item.source_domain)}</span>
          <span class="${availabilityClass(item)}">${escapeHtml(availabilityText(item))}</span>
          <span>${escapeHtml(formatPrice(item))}</span>
          <span>Overall ${Number(item.scores?.overall || 0).toFixed(2)}</span>
        </div>
      `
    )
    .join("");
  moreEl.hidden = false;
}

function syncCurrencyFromCountry() {
  if (currencyTouched) {
    return;
  }
  const option = countrySelect.selectedOptions[0];
  const currency = option?.dataset.currency;
  if (!currency) {
    return;
  }
  const match = [...currencySelect.options].find((item) => item.value === currency);
  if (match) {
    currencySelect.value = currency;
  }
}

function updateChips() {
  const code = countrySelect.value;
  const examples = COUNTRY_EXAMPLES[code];
  const chips = document.querySelector(".chips");
  if (!chips || !examples) {
    return;
  }
  chips.innerHTML = examples
    .map((query) => `<button type="button" class="chip" data-query="${escapeHtml(query)}">${escapeHtml(query)}</button>`)
    .join("");
  chips.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      queryInput.value = chip.dataset.query || chip.textContent;
      queryInput.focus();
    });
  });
}

function detectCountry() {
  const stored = localStorage.getItem("findbest_country");
  if (stored && [...countrySelect.options].some((item) => item.value === stored)) {
    return stored;
  }
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (TZ_TO_COUNTRY[tz] && [...countrySelect.options].some((item) => item.value === TZ_TO_COUNTRY[tz])) {
      return TZ_TO_COUNTRY[tz];
    }
  } catch {
    /* ignore */
  }
  const lang = (navigator.language || "").split("-")[1];
  if (lang && [...countrySelect.options].some((item) => item.value === lang.toUpperCase())) {
    return lang.toUpperCase();
  }
  return countrySelect.value;
}

async function hydrateCountry() {
  let code = detectCountry();
  try {
    const response = await fetch("/api/geo");
    if (response.ok) {
      const data = await response.json();
      if (!localStorage.getItem("findbest_country") && data.country) {
        code = data.country;
      }
    }
  } catch {
    /* keep timezone guess */
  }
  if ([...countrySelect.options].some((item) => item.value === code)) {
    countrySelect.value = code;
  }
  syncCurrencyFromCountry();
  updateChips();
}

async function runSearch(query) {
  hide(errorEl);
  hide(notesEl);
  picksEl.hidden = true;
  hide(moreEl);
  const countryName = countrySelect.selectedOptions[0]?.textContent?.trim() || "your country";
  show(
    statusEl,
    `Searching stores in ${countryName} and sellers that ship there. This can take 15–30 seconds…`
  );
  searchBtn.disabled = true;

  try {
    const response = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        country: countrySelect.value,
        base_currency: currencySelect.value,
        max_pages: 8,
      }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Search failed");
    }
    if (data.error && !data.picks) {
      throw new Error(data.error);
    }
    hide(statusEl);
    picksEl.innerHTML = (data.picks || []).map(renderCard).join("");
    picksEl.hidden = false;
    const winnerItems = (data.picks || []).map((pick) => pick.item);
    renderMore(data.items, winnerItems);
    if (data.notes && data.notes.length) {
      show(notesEl, data.notes.join(" "));
    }
    if (data.error) {
      show(errorEl, data.error);
    }
  } catch (err) {
    hide(statusEl);
    show(errorEl, err.message || "Search failed");
  } finally {
    searchBtn.disabled = false;
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const query = queryInput.value.trim();
  if (query) {
    runSearch(query);
  }
});

currencySelect.addEventListener("change", () => {
  currencyTouched = true;
});

countrySelect.addEventListener("change", () => {
  localStorage.setItem("findbest_country", countrySelect.value);
  syncCurrencyFromCountry();
  updateChips();
});

document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    queryInput.value = chip.dataset.query || chip.textContent;
    queryInput.focus();
  });
});

hydrateCountry();

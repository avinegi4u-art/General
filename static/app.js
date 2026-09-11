const form = document.getElementById("search-form");
const queryInput = document.getElementById("query");
const searchBtn = document.getElementById("search-btn");
const statusEl = document.getElementById("status");
const errorEl = document.getElementById("error");
const notesEl = document.getElementById("notes");
const overviewEl = document.getElementById("overview");
const picksEl = document.getElementById("picks");
const moreEl = document.getElementById("more");
const moreList = document.getElementById("more-list");
const locationLine = document.getElementById("location-line");

const COUNTRY_EXAMPLES = {
  AE: ["best e scooter under 10k aed", "wireless earbuds under 200 AED", "noise cancelling headphones"],
  IN: ["wireless earbuds under 2000 INR", "noise cancelling headphones", "office chair under 8000 INR"],
  SA: ["wireless earbuds under 200 SAR", "noise cancelling headphones"],
  US: ["wireless earbuds under $40", "noise cancelling headphones"],
  GB: ["wireless earbuds under £40", "noise cancelling headphones"],
  QA: ["wireless earbuds under 200 QAR", "noise cancelling headphones"],
};

const detected = {
  country: "",
  name: "",
  currency: "",
};

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

function systemTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch {
    return "";
  }
}

function systemLocale() {
  return navigator.language || "";
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
  return `
    <article class="card ${escapeHtml(pick.id)}">
      <p class="badge">${escapeHtml(pick.label)}</p>
      <p class="${availabilityClass(item)}">${escapeHtml(availabilityText(item))}</p>
      <h3>${escapeHtml(item.title)}</h3>
      <p class="meta">${escapeHtml(item.source_domain)} · ${escapeHtml(formatRating(item))}</p>
      <p class="price">${escapeHtml(formatPrice(item))}</p>
      <p class="why">${escapeHtml(item.description || pick.blurb)}</p>
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

function updateChips(code) {
  const examples = COUNTRY_EXAMPLES[code] || COUNTRY_EXAMPLES.US || ["noise cancelling headphones"];
  const chips = document.querySelector(".chips");
  if (!chips) {
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

function showLocation(name, currency) {
  if (!locationLine) {
    return;
  }
  locationLine.textContent = `Shopping in ${name} · ${currency} (from this device)`;
}

async function hydrateLocation() {
  const tz = systemTimezone();
  const locale = systemLocale();
  const params = new URLSearchParams();
  if (tz) {
    params.set("tz", tz);
  }
  if (locale) {
    params.set("locale", locale);
  }
  try {
    const response = await fetch(`/api/geo?${params.toString()}`, {
      headers: { "X-Timezone": tz },
    });
    if (response.ok) {
      const data = await response.json();
      detected.country = data.country || "";
      detected.name = data.name || "";
      detected.currency = data.currency || "";
      showLocation(detected.name, detected.currency);
      updateChips(detected.country);
      return;
    }
  } catch {
    /* fall through */
  }
  locationLine.textContent = "Shopping with this device’s location";
}

async function runSearch(query) {
  hide(errorEl);
  hide(notesEl);
  if (overviewEl) {
    hide(overviewEl);
    overviewEl.innerHTML = "";
  }
  picksEl.hidden = true;
  hide(moreEl);
  const where = detected.name || "your location";
  show(
    statusEl,
    `Searching stores in ${where} and sellers that ship there. This can take 15–30 seconds…`
  );
  searchBtn.disabled = true;

  try {
    const response = await fetch("/api/search", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Timezone": systemTimezone(),
      },
      body: JSON.stringify({
        query,
        time_zone: systemTimezone(),
        locale: systemLocale(),
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
    if (data.country_name && data.base_currency) {
      detected.name = data.country_name;
      detected.country = data.country_code || detected.country;
      detected.currency = data.base_currency;
      showLocation(data.country_name, data.base_currency);
    }
    hide(statusEl);
    if (data.overview && overviewEl) {
      overviewEl.innerHTML = `<h2>Overview</h2><p>${escapeHtml(data.overview)}</p>`;
      overviewEl.hidden = false;
    }
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

hydrateLocation();

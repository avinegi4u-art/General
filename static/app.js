const form = document.getElementById("search-form");
const queryInput = document.getElementById("query");
const currencySelect = document.getElementById("currency");
const searchBtn = document.getElementById("search-btn");
const statusEl = document.getElementById("status");
const errorEl = document.getElementById("error");
const picksEl = document.getElementById("picks");
const moreEl = document.getElementById("more");
const moreList = document.getElementById("more-list");

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
      <h3>${escapeHtml(item.title)}</h3>
      <p class="meta">${escapeHtml(item.source_domain)} · ${escapeHtml(formatRating(item))}</p>
      <p class="price">${escapeHtml(formatPrice(item))}</p>
      <p class="why">${escapeHtml(item.description || pick.blurb)}</p>
      <p class="scores">Match ${Number(scores.relevance || 0).toFixed(2)} · Price ${Number(scores.price || 0).toFixed(2)} · Overall ${Number(scores.overall || 0).toFixed(2)}</p>
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
          <span>${escapeHtml(formatPrice(item))}</span>
          <span>Overall ${Number(item.scores?.overall || 0).toFixed(2)}</span>
        </div>
      `
    )
    .join("");
  moreEl.hidden = false;
}

async function runSearch(query) {
  hide(errorEl);
  picksEl.hidden = true;
  hide(moreEl);
  show(statusEl, "Searching Google and the rest of the web, then reading product pages. This can take 15–30 seconds…");
  searchBtn.disabled = true;

  try {
    const response = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
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

document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    queryInput.value = chip.dataset.query || chip.textContent;
    queryInput.focus();
  });
});

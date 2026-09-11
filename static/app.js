const form = document.getElementById("search-form");
const queryInput = document.getElementById("query");
const searchBtn = document.getElementById("search-btn");
const errorEl = document.getElementById("error");
const picksEl = document.getElementById("picks");

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

function formatPrice(item) {
  return item?.price_display || "";
}

function renderCard(pick) {
  const item = pick.item;
  const title = (item?.title || "").trim();
  if (!item || !title) {
    return "";
  }
  const price = formatPrice(item);
  const priceHtml = price ? `<p class="price">${escapeHtml(price)}</p>` : "";
  return `
    <article class="card ${escapeHtml(pick.id)}">
      <h3><a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(title)}</a></h3>
      ${priceHtml}
    </article>
  `;
}

async function runSearch(query) {
  hide(errorEl);
  picksEl.hidden = true;
  picksEl.innerHTML = "";
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
    picksEl.innerHTML = (data.picks || []).map(renderCard).join("");
    picksEl.hidden = !picksEl.innerHTML.trim();
  } catch (err) {
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

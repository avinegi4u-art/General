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

function renderChecks(checks) {
  return (checks || [])
    .map((check) => {
      const status = check.status || "warn";
      const mark = status === "pass" ? "Pass" : status === "fail" ? "Fail" : "Check";
      return `<li class="check ${escapeHtml(status)}"><span class="mark">${mark}</span> ${escapeHtml(check.label)}</li>`;
    })
    .join("");
}

function renderRow(row) {
  const buyClass = row.is_buy ? " is-buy" : "";
  return `
    <article class="row-card${buyClass}">
      <div class="row-top">
        <p class="kicker">${escapeHtml(row.label)}</p>
        <p class="price">${escapeHtml(row.price_display || "")}</p>
      </div>
      <h3><a href="${escapeHtml(row.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(row.title)}</a></h3>
      <p class="edge">${escapeHtml(row.edge || "")}</p>
      <p class="facts">${escapeHtml(row.rating_display || "")} · ${escapeHtml(row.availability || "")} · ${escapeHtml(row.source || "")}</p>
      <a class="view" href="${escapeHtml(row.url)}" target="_blank" rel="noopener noreferrer">View listing</a>
    </article>
  `;
}

function renderDecision(data) {
  const decision = data.decision || {};
  const verdict = decision.verdict;
  if (!verdict) {
    return (data.picks || []).map(renderCard).join("");
  }
  const compared = (decision.rows || []).length;
  const considered = Number(data.items_considered || 0);
  const meta =
    considered > compared
      ? `${compared} shortlisted from ${considered} listings`
      : `${compared} listings in the shortlist`;
  const hold = decision.hold
    ? `<p class="hold">${escapeHtml(decision.hold)}</p>`
    : "";
  const spread = decision.spread ? `<p class="spread">${escapeHtml(decision.spread)}</p>` : "";
  const sameTitle = decision.same_title
    ? `<p class="same-title">${escapeHtml(decision.same_title)}</p>`
    : "";
  const price = verdict.price_display
    ? `<p class="verdict-price">${escapeHtml(verdict.price_display)}</p>`
    : "";
  return `
    <section class="verdict">
      <p class="eyebrow">${escapeHtml(verdict.label || "Buy this")}</p>
      <h2><a href="${escapeHtml(verdict.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(verdict.headline)}</a></h2>
      ${price}
      ${hold}
      <p class="reason">${escapeHtml(verdict.reason || "")}</p>
      <ul class="checks">${renderChecks(decision.checks)}</ul>
      ${spread}
      ${sameTitle}
      <p class="meta">${escapeHtml(meta)}</p>
    </section>
    <section class="shortlist">
      ${(decision.rows || []).map(renderRow).join("")}
    </section>
  `;
}

async function runSearch(query) {
  hide(errorEl);
  picksEl.hidden = true;
  picksEl.innerHTML = "";
  searchBtn.disabled = true;
  searchBtn.textContent = "Searching";
  picksEl.hidden = false;
  picksEl.innerHTML = `<p class="meta working">Checking prices, ratings, and delivery.</p>`;

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
    const html = renderDecision(data);
    if (!html.trim()) {
      throw new Error(data.error || "No single product to buy. Try a more specific query.");
    }
    picksEl.innerHTML = html;
    picksEl.hidden = false;
  } catch (err) {
    show(errorEl, err.message || "Search failed");
    picksEl.hidden = true;
    picksEl.innerHTML = "";
  } finally {
    searchBtn.disabled = false;
    searchBtn.textContent = "Search";
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const query = queryInput.value.trim();
  if (query) {
    runSearch(query);
  }
});

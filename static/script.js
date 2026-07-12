/*
 * Homepage data loading: pulls outages + stats from the JSON API and
 * renders the stat strip, outage cards, and (via map.js) map markers.
 * Also wires up the suburb search box.
 */

(function () {
  const cardsContainer = document.getElementById("outage-cards");
  const lastUpdatedEl = document.getElementById("last-updated");
  const searchInput = document.getElementById("suburb-search");
  const searchBtn = document.getElementById("search-btn");
  const clearBtn = document.getElementById("clear-search-btn");
  const notifyBtn = document.getElementById("notify-btn");
  const subscribePanel = document.getElementById("subscribe-panel");
  const subscribeForm = document.getElementById("subscribe-form");
  const subscribeCancel = document.getElementById("subscribe-cancel");
  const subscribeMessage = document.getElementById("subscribe-message");
  const filterTabs = document.querySelectorAll(".filter-tab");

  let allOutages = [];
  let currentStatus = "";

  async function loadOutages(suburb) {
    const params = new URLSearchParams();
    if (suburb) params.set("suburb", suburb);
    if (currentStatus) params.set("status", currentStatus);
    const url = params.toString() ? `/api/outages?${params}` : "/api/outages";
    const res = await fetch(url);
    const data = await res.json();
    if (!suburb) allOutages = data;
    renderCards(data);
    if (window.renderOutageMarkers) window.renderOutageMarkers(data);
  }

  async function loadStats() {
    const res = await fetch("/api/stats");
    const stats = await res.json();
    document.getElementById("stat-total").textContent = stats.total ?? 0;
    document.getElementById("stat-active").textContent = stats.active ?? 0;
    document.getElementById("stat-planned").textContent = stats.planned ?? 0;
    document.getElementById("stat-emergency").textContent = stats.emergency ?? 0;
  }

  async function loadLastUpdated() {
    const res = await fetch("/api/last-updated");
    const data = await res.json();
    if (data.last_updated) {
      const d = new Date(data.last_updated + "Z");
      lastUpdatedEl.textContent = `Last updated ${d.toLocaleString()}`;
    } else {
      lastUpdatedEl.textContent = "No data yet";
    }
  }

  function renderCards(outages) {
    if (!outages.length) {
      cardsContainer.innerHTML = `<p class="muted">No outages found.</p>`;
      return;
    }

    const scroll = document.createElement("div");
    scroll.className = "outage-cards-scroll";

    outages.forEach((o) => {
      const card = document.createElement("div");
      card.className = "outage-card";
      card.style.cursor = "pointer";
      card.addEventListener("click", () => { window.location.href = `/outage/${o.id}`; });
      card.innerHTML = `
        <div class="outage-card__top">
          <span class="outage-card__suburb">${escapeHtml(o.suburb)}</span>
          <span class="badge badge--${o.status.toLowerCase().replace(/\s+/g, '-')}">${escapeHtml(o.status)}</span>
        </div>
        ${o.reason ? `<div class="outage-card__reason">${escapeHtml(o.reason)}</div>` : ""}
        <div class="outage-card__times">
          ${o.time_started ? `Started ${escapeHtml(o.time_started)}` : ""}
          ${o.estimated_restoration ? ` &middot; ETA ${escapeHtml(o.estimated_restoration)}` : ""}
          ${o.confidence_score ? ` &middot; ${o.confidence_score}% confidence` : ""}
        </div>
      `;
      scroll.appendChild(card);
    });

    cardsContainer.innerHTML = "";
    cardsContainer.appendChild(scroll);
  }

  function escapeHtml(str) {
    if (str == null) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  async function loadNationalSummary() {
    const banner = document.getElementById("national-summary-banner");
    const text = document.getElementById("national-summary-text");
    try {
      const res = await fetch("/api/national-summary");
      const data = await res.json();
      if (!data.available) return;  // scraper hasn't successfully read this yet
      const parts = [];
      if (data.active != null) parts.push(`${data.active} active`);
      if (data.upcoming != null) parts.push(`${data.upcoming} upcoming`);
      if (data.maintenance != null) parts.push(`${data.maintenance} maintenance`);
      if (!parts.length) return;
      text.textContent = parts.join(" · ");
      banner.hidden = false;
    } catch (err) {
      // Non-critical -- banner just stays hidden.
    }
  }

  async function loadWeather() {
    const widget = document.getElementById("weather-widget");
    const text = document.getElementById("weather-widget-text");
    try {
      // Uses a central suburb as a stand-in for "Port Moresby" generally --
      // OpenWeather is queried per-coordinate, not per-city-name here.
      const res = await fetch("/api/weather/Boroko");
      const data = await res.json();
      if (!data.available) return;  // weather not configured -- widget stays hidden
      text.textContent = `Port Moresby: ${data.summary}`;
      widget.hidden = false;
      if (data.severe) {
        widget.classList.add("weather-widget--severe");
        text.textContent += " — may affect restoration times";
      }
    } catch (err) {
      // Weather is an enhancement, not critical -- fail silently.
    }
  }

  searchBtn.addEventListener("click", () => {
    const value = searchInput.value.trim();
    loadOutages(value || null);
  });
  searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") searchBtn.click();
  });
  clearBtn.addEventListener("click", () => {
    searchInput.value = "";
    loadOutages(null);
  });

  filterTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      filterTabs.forEach((t) => t.classList.remove("filter-tab--active"));
      tab.classList.add("filter-tab--active");
      currentStatus = tab.dataset.status;
      loadOutages(searchInput.value.trim() || null);
    });
  });

  notifyBtn.addEventListener("click", () => {
    subscribePanel.hidden = !subscribePanel.hidden;
  });
  const quickAccessNotify = document.getElementById("quick-access-notify");
  if (quickAccessNotify) {
    quickAccessNotify.addEventListener("click", (e) => {
      e.preventDefault();
      subscribePanel.hidden = !subscribePanel.hidden;
      subscribePanel.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  }
  subscribeCancel.addEventListener("click", () => {
    subscribePanel.hidden = true;
  });
  subscribeForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    subscribeMessage.textContent = "Subscribing\u2026";
    subscribeMessage.className = "muted";

    const formData = new FormData(subscribeForm);
    try {
      const res = await fetch("/subscribe", { method: "POST", body: formData });
      const data = await res.json();
      if (res.ok) {
        subscribeMessage.textContent = data.already_subscribed
          ? "You're already subscribed for this suburb."
          : "Subscribed! You'll hear from us when something changes.";
        subscribeMessage.className = "success";
        subscribeForm.reset();
        setTimeout(() => { subscribePanel.hidden = true; subscribeMessage.textContent = ""; }, 2500);
      } else {
        subscribeMessage.textContent = data.error || "Something went wrong.";
        subscribeMessage.className = "error";
      }
    } catch (err) {
      subscribeMessage.textContent = "Couldn't reach the server. Try again.";
      subscribeMessage.className = "error";
    }
  });

  // Initial load, then refresh every 60s so the page stays current
  // between the backend's own scheduled scrapes.
  loadOutages();
  loadStats();
  loadLastUpdated();
  loadWeather();
  loadNationalSummary();
  setInterval(() => {
    loadOutages(searchInput.value.trim() || null);
    loadStats();
    loadLastUpdated();
  }, 60000);
})();

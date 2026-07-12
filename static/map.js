/*
 * MapLibre GL JS map setup for the outage tracker homepage.
 * Uses OpenFreeMap (https://openfreemap.org) for tiles -- free, no API
 * key, no signup, no usage limits. MapLibre GL JS is the open-source
 * fork of Mapbox GL JS (same rendering engine lineage, same vector-tile
 * look PNG Power's own site uses), so this gets the same modern feel
 * without needing a paid Mapbox account.
 *
 * Note the coordinate order: MapLibre (like all GeoJSON-based tools)
 * takes [longitude, latitude] -- the opposite order from Leaflet, which
 * this replaced. Every coordinate pair below is deliberately lon-then-lat.
 *
 * Exposes window.outageMap (the MapLibre map instance) and
 * window.renderOutageMarkers(outages) so script.js can update markers
 * whenever fresh data is fetched, without re-initialising the map.
 */

(function () {
  const mapEl = document.getElementById("map");
  const lat = parseFloat(mapEl.dataset.lat);
  const lon = parseFloat(mapEl.dataset.lon);
  const zoom = parseInt(mapEl.dataset.zoom, 10);

  const map = new maplibregl.Map({
    container: "map",
    style: "https://tiles.openfreemap.org/styles/positron",
    center: [lon, lat],
    zoom: zoom,
  });

  map.addControl(new maplibregl.NavigationControl(), "top-right");

  const statusColors = {
    Active: "#e6553b",
    Planned: "#6ea8fe",
    Restored: "#4caf7d",
    Reported: "#f5a623",
    "Under Review": "#f5a623",
    Verified: "#c084fc",
  };

  let currentMarkers = [];

  function renderOutageMarkers(outages) {
    currentMarkers.forEach((m) => m.remove());
    currentMarkers = [];

    outages.forEach((outage) => {
      if (outage.latitude == null || outage.longitude == null) return;

      const color = statusColors[outage.status] || "#aab6cc";

      const el = document.createElement("div");
      el.style.width = "18px";
      el.style.height = "18px";
      el.style.borderRadius = "50%";
      el.style.background = color;
      el.style.border = "2px solid rgba(255,255,255,0.85)";
      el.style.boxShadow = "0 1px 4px rgba(0,0,0,0.4)";
      el.style.cursor = "pointer";

      const popupHtml = `
        <div class="outage-popup">
          <div class="outage-popup__suburb">${escapeHtml(outage.suburb)}</div>
          <div class="outage-popup__row"><strong>Status:</strong> ${escapeHtml(outage.status)}</div>
          ${outage.time_started ? `<div class="outage-popup__row"><strong>Started:</strong> ${escapeHtml(outage.time_started)}</div>` : ""}
          ${outage.reason ? `<div class="outage-popup__row"><strong>Reason:</strong> ${escapeHtml(outage.reason)}</div>` : ""}
          ${outage.estimated_restoration ? `<div class="outage-popup__row"><strong>Est. restoration:</strong> ${escapeHtml(outage.estimated_restoration)}</div>` : ""}
        </div>
      `;

      const popup = new maplibregl.Popup({ offset: 14, closeButton: false }).setHTML(popupHtml);

      const marker = new maplibregl.Marker({ element: el })
        .setLngLat([outage.longitude, outage.latitude])
        .setPopup(popup)
        .addTo(map);

      currentMarkers.push(marker);
    });
  }

  function escapeHtml(str) {
    if (str == null) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  window.outageMap = map;
  window.renderOutageMarkers = renderOutageMarkers;
})();

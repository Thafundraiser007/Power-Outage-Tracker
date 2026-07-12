/*
 * Light/dark theme toggle. The actual theme is applied before first
 * paint by an inline script in base.html (to avoid a flash of the
 * wrong theme) -- this file just wires up the toggle button and
 * persists the choice.
 */

(function () {
  const toggle = document.getElementById("theme-toggle");
  if (!toggle) return;

  toggle.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme") || "dark";
    const next = current === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("theme", next);
  });
})();

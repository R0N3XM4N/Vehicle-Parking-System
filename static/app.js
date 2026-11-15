"use strict";
document.addEventListener("click", event => {
  const target = event.target.closest("[data-confirm], [data-print]");
  if (!target) return;
  if (target.dataset.confirm && !window.confirm(target.dataset.confirm)) event.preventDefault();
  if (target.hasAttribute("data-print")) window.print();
});
// Use the authenticated HTML view: no bearer tokens are exposed to JavaScript.
if (document.querySelector("[data-occupancy]")) {
  window.setInterval(async () => {
    if (document.hidden || document.querySelector("input:focus, select:focus")) return;
    try {
      const response = await fetch(window.location.href, {credentials: "same-origin"});
      if (!response.ok || response.redirected) return;
      const page = new DOMParser().parseFromString(await response.text(), "text/html");
      const updated = page.querySelector("[data-occupancy]");
      if (updated) document.querySelector("[data-occupancy]").replaceWith(updated);
    } catch (_) { /* Retain the last known values if the connection is interrupted. */ }
  }, 15000);
}

/* Symmetric per-page stylesheet gating.
 *
 * Overlay's styles.css and EM's em-styles.css both contain global
 * selectors (body, html, h1-h3, a, .dropdown, etc.) that collide
 * cross-tool. Loaded together they cause z-index, width, layout
 * overlap, and dropdown-stacking bugs.
 *
 * Solution: enable EXACTLY ONE tool's CSS based on URL.
 *   /em*       → EM stylesheets ON, overlay stylesheets OFF
 *   /  + else  → overlay stylesheets ON, EM stylesheets OFF
 *
 * Stylesheets that ALWAYS load (regardless of route):
 *   aa-tool-switcher.css  — the tool-switcher chip styling
 *   tokens.css            — shared design tokens (overlay's)
 *
 * Note: html.A hard-nav tool switcher means each URL change
 * reloads the page; this script re-runs and picks the right
 * state cleanly on every load.
 */
(function () {
  "use strict";

  // Sheets that should ONLY load on /em routes.
  var EM_SHEETS = [
    "em-tokens.css",
    "em-styles.css",
    "zz-em-app.css",
  ];

  // Sheets that should ONLY load on /overlay (default) routes.
  var OVERLAY_SHEETS = [
    "/styles.css",   // overlay's main stylesheet (leading slash to
                     // avoid matching em-styles.css)
  ];

  function isEmPath() {
    return (window.location.pathname || "/").indexOf("/em") === 0;
  }

  function sheetMatches(href, list) {
    for (var j = 0; j < list.length; j++) {
      if (href.indexOf(list[j]) !== -1) return true;
    }
    return false;
  }

  function applyToggle() {
    var em = isEmPath();
    var links = document.querySelectorAll("link[rel='stylesheet']");
    for (var i = 0; i < links.length; i++) {
      var href = links[i].getAttribute("href") || "";
      if (sheetMatches(href, EM_SHEETS)) {
        links[i].disabled = !em;       // EM sheets: on for /em only
      } else if (sheetMatches(href, OVERLAY_SHEETS)) {
        links[i].disabled = em;        // overlay sheets: off on /em
      }
      // aa-tool-switcher.css, em-clientside.js, etc. left alone.
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", applyToggle);
  } else {
    applyToggle();
  }
  window.addEventListener("load", applyToggle);
})();

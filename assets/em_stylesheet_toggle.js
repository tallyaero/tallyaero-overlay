/* Toggle EM-specific stylesheets on/off based on the current URL.
 * Dash auto-serves every .css file under assets/, so the EM
 * stylesheets are loaded regardless of route. They contain global
 * selectors (body, html, h1-h3, a) that override overlay's
 * styling when on /overlay. Setting `link.disabled = true` removes
 * the sheet from the cascade without unloading it — flip the
 * other way when the user navigates to /em.
 *
 * Sheets gated:
 *   em-tokens.css
 *   em-styles.css
 *   zz-em-app.css
 *
 * Note: this runs at page-load only. With the html.A hard-nav
 * tool switcher (not dcc.Link), every URL change reloads the
 * page, so this script re-runs and picks the right state.
 */
(function () {
  "use strict";

  var EM_SHEETS = [
    "em-tokens.css",
    "em-styles.css",
    "zz-em-app.css",
  ];

  function isEmPath() {
    return (window.location.pathname || "/").indexOf("/em") === 0;
  }

  function applyToggle() {
    var em = isEmPath();
    var links = document.querySelectorAll("link[rel='stylesheet']");
    for (var i = 0; i < links.length; i++) {
      var href = links[i].getAttribute("href") || "";
      // Match any of our gated sheets — Dash serves them at
      // /assets/<name> with a cache-bust query string.
      var match = false;
      for (var j = 0; j < EM_SHEETS.length; j++) {
        if (href.indexOf(EM_SHEETS[j]) !== -1) {
          match = true;
          break;
        }
      }
      if (match) {
        links[i].disabled = !em;
      }
    }
  }

  // Apply once stylesheets are loaded. Dash injects them during
  // initial paint, so listen on both DOMContentLoaded (early DOM
  // ready) and on the 'load' event (after all <link>s are in).
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", applyToggle);
  } else {
    applyToggle();
  }
  window.addEventListener("load", applyToggle);
})();

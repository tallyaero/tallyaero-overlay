/* Apply the active class to the matching tool-switcher link based on
 * the current URL. Runs on every load (including hard navigations
 * triggered by html.A). Re-runs when the URL changes (in case we
 * ever go back to a dcc.Link / SPA model later). */
(function () {
  "use strict";

  function setActive() {
    var path = window.location.pathname || "/";
    var emLink = document.getElementById("tool-switcher-em");
    var overlayLink = document.getElementById("tool-switcher-overlay");
    if (!emLink || !overlayLink) return false;

    var ACTIVE = "tool-switcher-link tool-switcher-active";
    var IDLE = "tool-switcher-link";

    if (path.indexOf("/em") === 0) {
      emLink.className = ACTIVE;
      overlayLink.className = IDLE;
    } else {
      overlayLink.className = ACTIVE;
      emLink.className = IDLE;
    }
    return true;
  }

  // Try right away (in case the switcher already exists), then keep
  // watching the DOM until the switcher mounts.
  if (!setActive()) {
    var observer = new MutationObserver(function () {
      if (setActive()) observer.disconnect();
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }
})();

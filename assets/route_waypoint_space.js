/* Route-waypoint dropdown — press SPACE to pick the top highlighted
 * option. Saves a Tab + Enter or a click on every waypoint entry.
 *
 * The dcc.Dropdown is a react-select widget; it already highlights
 * the first matching option as you type. Enter normally selects the
 * highlighted option. We map SPACE → Enter for this specific input.
 *
 * Re-attaches whenever the dropdown remounts (e.g. when the user
 * switches into the Route Planner maneuver shelf).
 */
(function () {
  "use strict";

  function attachSpaceHandler(input) {
    if (!input || input.dataset.taSpaceHandler === "1") return;
    input.dataset.taSpaceHandler = "1";

    input.addEventListener("keydown", function (e) {
      if (e.key !== " " && e.code !== "Space") return;
      // Only intercept when the user has actually typed something —
      // otherwise let the (unlikely) literal-space behavior pass.
      var typed = (input.value || "").trim();
      if (!typed) return;
      e.preventDefault();
      e.stopPropagation();
      // Synthesize an Enter keydown so react-select selects the
      // currently-highlighted option (which is the top match).
      var enterEvent = new KeyboardEvent("keydown", {
        key: "Enter",
        code: "Enter",
        keyCode: 13,
        which: 13,
        bubbles: true,
        cancelable: true,
      });
      input.dispatchEvent(enterEvent);
    });
  }

  function scan() {
    // The dcc.Dropdown wraps its input in a container with the
    // component id. The actual text input is `input[type=text]`
    // inside that container.
    var container = document.getElementById("route-waypoints");
    if (!container) return;
    var inputs = container.querySelectorAll("input");
    for (var i = 0; i < inputs.length; i++) {
      attachSpaceHandler(inputs[i]);
    }
  }

  // Initial pass + MutationObserver so we catch the dropdown when it
  // remounts (the route shelf is added/removed when the user changes
  // the maneuver dropdown).
  function init() {
    scan();
    var observer = new MutationObserver(function () {
      scan();
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

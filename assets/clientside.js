/* TallyAero Maneuver Overlay — clientside namespace.
   Loaded as a normal asset; Dash exposes functions on window.dash_clientside
   so the Python side references them via ClientsideFunction(namespace, fn).

   Ported from the EM Diagram tool (Phase 4 mirror) — only the
   theme + viewport bits land in Batch 1. EM-specific bindings
   (state-card popovers, replayManeuver, update banner) follow in
   later batches once the matching overlay UI lands.
*/

window.dash_clientside = window.dash_clientside || {};
window.dash_clientside.tallyaero = window.dash_clientside.tallyaero || {};

/**
 * Cycle the theme preference based on which button triggered the callback.
 * Reads the current value from localStorage rather than a Dash State,
 * which avoids known Dash-3 quirks with multi-output + State clientside.
 *
 * Returns [pref, c_auto, c_light, c_dark] matching the four Outputs.
 */
window.dash_clientside.tallyaero.cycleTheme = function (autoClicks, lightClicks, darkClicks) {
    var ctx = window.dash_clientside.callback_context;
    var triggered = (ctx && ctx.triggered && ctx.triggered.length)
        ? ctx.triggered[0].prop_id || ''
        : '';

    var pref = localStorage.getItem('tallyaero_theme');
    if (!pref || pref === 'system') pref = 'light';

    if (triggered.indexOf('theme-btn-light') === 0) pref = 'light';
    if (triggered.indexOf('theme-btn-dark')  === 0) pref = 'dark';

    document.documentElement.setAttribute('data-theme', pref);
    document.documentElement.setAttribute('data-theme-pref', pref);
    localStorage.setItem('tallyaero_theme', pref);

    var c_auto  = 'theme-btn';
    var c_light = 'theme-btn' + (pref === 'light' ? ' active' : '');
    var c_dark  = 'theme-btn' + (pref === 'dark'  ? ' active' : '');

    return [pref, c_auto, c_light, c_dark];
};

/**
 * On page load, mirror the theme stored in localStorage into the dcc.Store.
 * Fixes the race where layout-dependent callbacks fire before the Store's
 * persistence restores its value.
 */
window.dash_clientside.tallyaero.syncThemeFromStorage = function (_pathname) {
    var pref = localStorage.getItem('tallyaero_theme');
    if (!pref || pref === 'system') pref = 'light';
    document.documentElement.setAttribute('data-theme', pref);
    document.documentElement.setAttribute('data-theme-pref', pref);
    return pref;
};

/**
 * Viewport-width detector. Returns window.innerWidth.
 * Used by display_page to pick desktop vs mobile layout.
 */
window.dash_clientside.tallyaero.screenWidth = function (_pathname) {
    return window.innerWidth;
};

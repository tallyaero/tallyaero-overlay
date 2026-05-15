/* TallyAero EM Diagram — clientside namespace.
   Loaded as a normal asset; Dash exposes functions on window.dash_clientside
   so the Python side can reference them via ClientsideFunction(namespace, fn).
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

    // Light is the persistent default. Legacy "system" / "auto" values in
    // localStorage are normalized to "light" on first read.
    var pref = localStorage.getItem('tallyaero_theme');
    if (!pref || pref === 'system') pref = 'light';

    if (triggered.indexOf('theme-btn-light') === 0) pref = 'light';
    if (triggered.indexOf('theme-btn-dark')  === 0) pref = 'dark';

    document.documentElement.setAttribute('data-theme', pref);
    document.documentElement.setAttribute('data-theme-pref', pref);
    localStorage.setItem('tallyaero_theme', pref);

    // Outputs map [theme-pref.data, auto.className, light.className, dark.className]
    // theme-btn-auto is hidden but still in the DOM; give it a stable className.
    var c_auto  = 'theme-btn';
    var c_light = 'theme-btn' + (pref === 'light' ? ' active' : '');
    var c_dark  = 'theme-btn' + (pref === 'dark'  ? ' active' : '');

    return [pref, c_auto, c_light, c_dark];
};

/**
 * On page load, mirror the theme stored in localStorage into the dcc.Store.
 * Fixes the race where update_graph fires before the Store's persistence
 * restores its value — causing the chart to render with a stale/None
 * palette in dark mode.
 */
window.dash_clientside.tallyaero.syncThemeFromStorage = function (_pathname) {
    var pref = localStorage.getItem('tallyaero_theme');
    if (!pref || pref === 'system') pref = 'light';
    document.documentElement.setAttribute('data-theme', pref);
    document.documentElement.setAttribute('data-theme-pref', pref);
    return pref;
};

/**
 * Phase 5P — keyboard shortcuts. Installs a single global keydown listener
 * on first run; subsequent invocations are no-ops. Shortcuts:
 *   d / D  → toggle the settings drawer
 *   e / E  → open the Edit/Create Aircraft modal
 *   g / G  → toggle Ps contours overlay
 *   ?      → log shortcut list to console
 * Modifier keys (cmd/ctrl/alt) are ignored, as are keys typed inside
 * input/textarea/contenteditable so users can still type freely.
 */
window.dash_clientside.tallyaero.bindKeyboardShortcuts = function (_pathname) {
    if (window._tallyaero_bootstraps_installed) return window.dash_clientside.no_update;
    window._tallyaero_bootstraps_installed = true;

    // ── Keyboard shortcuts ───────────────────────────────────────────────
    document.addEventListener('keydown', function (e) {
        var t = e.target;
        if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
        if (e.metaKey || e.ctrlKey || e.altKey) return;

        var k = e.key.toLowerCase();
        if (k === 'd') {
            var b = document.getElementById('open-drawer-btn');
            if (b) { b.click(); e.preventDefault(); }
        } else if (k === 'e') {
            var b = document.getElementById('edit-aircraft-button');
            if (b) { b.click(); e.preventDefault(); }
        } else if (k === 'g') {
            var s = document.getElementById('toggle-ps');
            if (s) {
                var input = s.querySelector('input') || s;
                input.click();
                e.preventDefault();
            }
        } else if (e.key === '?') {
            console.info('[TallyAero] Shortcuts: d=drawer, e=edit aircraft, g=Ps contours, ?=help');
        }
    });

    // ── Outside-click dismissal for popovers ────────────────────────────
    // Phase 5AB-2: env popovers retired (airport, altitude, oat, altim are
    // now inline rail controls). Only state-card definition popovers + the
    // Compare popover remain; compare uses dbc.Popover's native dismissal
    // (no Python-side is_open hijack anymore) so we don't need to wire it
    // through this group either.
    var STATE_CARD_POPOVERS = [
        "popover-state-card-weight", "popover-state-card-vs1g",  "popover-state-card-va",
        "popover-state-card-vne",    "popover-state-card-vno",   "popover-state-card-glim",
        "popover-state-card-ke",     "popover-state-card-pe",    "popover-state-card-e",
    ];
    var STATE_CARD_TRIGGERS = [
        "state-card-weight", "state-card-vs1g", "state-card-va",
        "state-card-vne",    "state-card-vno",  "state-card-glim",
        "state-card-ke",     "state-card-pe",   "state-card-e",
    ];

    function handleGroup(e, popoverIds, triggerIds) {
        // popoverIds[i] is the popover for triggerIds[i] — same ordering.
        // Three cases:
        //   1. Click landed on a trigger → close every OTHER popover in the
        //      group, let dbc.Popover toggle the matching one.
        //   2. Click landed inside an open popover → leave it alone.
        //   3. Click landed outside everything → close all popovers in this
        //      group.
        for (var i = 0; i < triggerIds.length; i++) {
            var trig = document.getElementById(triggerIds[i]);
            if (trig && trig.contains(e.target)) {
                for (var k = 0; k < popoverIds.length; k++) {
                    if (k === i) continue;
                    try { window.dash_clientside.set_props(popoverIds[k], { is_open: false }); } catch (err) {}
                }
                return;
            }
        }
        for (var j = 0; j < popoverIds.length; j++) {
            var pop = document.getElementById(popoverIds[j]);
            if (pop && pop.contains(e.target)) return;
        }
        for (var m = 0; m < popoverIds.length; m++) {
            try { window.dash_clientside.set_props(popoverIds[m], { is_open: false }); } catch (err) {}
        }
    }

    document.addEventListener("mousedown", function (e) {
        handleGroup(e, STATE_CARD_POPOVERS, STATE_CARD_TRIGGERS);
    });

    return window.dash_clientside.no_update;
};

/**
 * Viewport-width detector. Returns window.innerWidth.
 * Used by display_page to pick desktop vs mobile layout.
 */
window.dash_clientside.tallyaero.screenWidth = function (_pathname) {
    return window.innerWidth;
};


/* ──────────────────────────────────────────────────────────────────────
   Phase 5h — Chandelle replay scrubber.
   Reads the existing "Chandelle" trace from the figure, interpolates the
   position at the slider's percentage, and writes a single-point marker
   into the same figure. Also updates the readout span with IAS/AOB/G/heading.
   All clientside — zero server roundtrip per scrub frame.
   ──────────────────────────────────────────────────────────────────────*/

window.dash_clientside.tallyaero.replayManeuver = function (scrubPct, figure) {
    if (!figure || !figure.data) return [window.dash_clientside.no_update, ''];

    // Set of trace names that represent a maneuver time-trajectory.
    // Add any new maneuver here when its plot_<maneuver>() in figure.py
    // gives the trace one of these `name` values.
    var MANEUVER_NAMES = ['Chandelle', 'Lazy Eight'];

    // Find whichever maneuver trace is currently plotted (only one at a time).
    var trace = figure.data.find(function (t) {
        return MANEUVER_NAMES.indexOf(t.name) !== -1 && t.x && t.x.length > 0;
    });
    if (!trace) {
        // No maneuver plotted right now — strip any stale marker, clear readout.
        figure.data = figure.data.filter(function (t) { return t.name !== 'Replay Position'; });
        return [figure, ''];
    }

    var n = trace.x.length;
    var pct = Math.max(0, Math.min(100, scrubPct || 0));
    var idx = Math.round((pct / 100) * (n - 1));
    var x = trace.x[idx];
    var y = trace.y[idx];

    // Decode IAS / AOB / G / heading from the hovertext attached by the
    // plot_<maneuver>() function. Format:
    //   "<phase><br>IAS: NN kt<br>Turn Rate: N.N°/s<br>AOB: NN°<br>G: N.NN<br>Heading: NNN°"
    var hoverText = (trace.hovertext && trace.hovertext[idx]) || '';
    var parts = hoverText.split('<br>');
    var iasLine = parts.find(function (p) { return p.indexOf('IAS:')     === 0; }) || 'IAS: —';
    var aobLine = parts.find(function (p) { return p.indexOf('AOB:')     === 0; }) || 'AOB: —';
    var gLine   = parts.find(function (p) { return p.indexOf('G:')       === 0; }) || 'G: —';
    var hdgLine = parts.find(function (p) { return p.indexOf('Heading:') === 0; }) || 'Heading: —';
    var readout = [iasLine, aobLine, gLine, hdgLine].join('   ');

    // Build the replay-position marker trace.
    var marker = {
        type: 'scatter',
        mode: 'markers',
        x: [x],
        y: [y],
        marker: {
            size: 16,
            color: '#f27b0d',           // brand orange — pops on both light/dark
            symbol: 'circle',
            line: { color: '#ffffff', width: 2.5 },
        },
        name: 'Replay Position',
        showlegend: false,
        hoverinfo: 'skip',
    };

    // Replace if it exists, else append.
    var existingIdx = figure.data.findIndex(function (t) {
        return t.name === 'Replay Position';
    });
    if (existingIdx >= 0) {
        figure.data[existingIdx] = marker;
    } else {
        figure.data.push(marker);
    }

    return [figure, readout];
};


/* ──────────────────────────────────────────────────────────────────────
   Phase 6S — Update-check banner.

   On first page load, fetch a small JSON document from tallyaero.com:

       {
         "latest_version": "0.4.0",
         "release_notes":  "Improved Ps accuracy, new Decathlon polar.",
         "download_url":   "https://tallyaero.com/em-diagram/download"
       }

   Compare against the bundled version (rendered into the DOM by the
   server-side template; here it's read from window.__TALLYAERO_VERSION__
   set by a small inline-script tag, OR fallback to a known string).

   If the user is on an older version, the banner is unhidden with a
   message + a link to the download page. The X button stores a
   "dismissed-for-this-version" flag in localStorage so the user isn't
   nagged on every reload of the same outdated build.

   This is a single fire-on-load global, not a Dash callback — keeps the
   banner logic out of the Python callback graph and avoids a Store.
   ──────────────────────────────────────────────────────────────────────*/

(function tallyaeroUpdateCheck() {
    var VERSION_URL = 'https://tallyaero.com/em-version.json';
    var CURRENT     = (window.__TALLYAERO_VERSION__ || '0.0.0').trim();

    // Naive semver comparator — returns negative if a < b, positive if a > b,
    // zero if equal. Handles unequal segment counts (1.0 vs 1.0.1).
    function cmpVer(a, b) {
        var as = a.split('.').map(function (n) { return parseInt(n, 10) || 0; });
        var bs = b.split('.').map(function (n) { return parseInt(n, 10) || 0; });
        var max = Math.max(as.length, bs.length);
        for (var i = 0; i < max; i++) {
            var diff = (as[i] || 0) - (bs[i] || 0);
            if (diff !== 0) return diff;
        }
        return 0;
    }

    function showBanner(msg, downloadUrl) {
        var banner = document.getElementById('update-banner');
        var msgEl  = document.getElementById('update-banner-msg');
        var link   = document.getElementById('update-banner-link');
        if (!banner || !msgEl || !link) return;     // banner DOM not on this page
        msgEl.textContent = msg;
        if (downloadUrl) link.href = downloadUrl;
        banner.style.display = 'flex';
    }

    function dismiss(version) {
        try {
            localStorage.setItem('tallyaero_update_dismissed', version);
        } catch (e) { /* private mode etc. */ }
        var banner = document.getElementById('update-banner');
        if (banner) banner.style.display = 'none';
    }

    // Wire the close button on first DOM-ready
    function attachCloseHandler() {
        var btn = document.getElementById('update-banner-close');
        if (btn && !btn._tallyaeroBound) {
            btn._tallyaeroBound = true;
            btn.addEventListener('click', function () {
                var v = btn.getAttribute('data-latest') || '';
                dismiss(v);
            });
        }
    }

    function check() {
        attachCloseHandler();
        // Skip in dev (file:// or localhost without a real production URL).
        // The check is best-effort — if network fails or the JSON is missing,
        // the banner stays hidden and the app loads normally.
        fetch(VERSION_URL, { cache: 'no-store' })
            .then(function (r) {
                if (!r.ok) throw new Error('http ' + r.status);
                return r.json();
            })
            .then(function (data) {
                var latest = (data.latest_version || '').trim();
                var url    = data.download_url || 'https://tallyaero.com/em-diagram';
                if (!latest || cmpVer(CURRENT, latest) >= 0) return;
                // Honor a previous dismissal for this exact version
                var dismissed = '';
                try { dismissed = localStorage.getItem('tallyaero_update_dismissed') || ''; }
                catch (e) {}
                if (dismissed === latest) return;
                var btn = document.getElementById('update-banner-close');
                if (btn) btn.setAttribute('data-latest', latest);
                showBanner(
                    'TallyAero EM v' + latest + ' is available. ' +
                    'You\'re on v' + CURRENT + '.',
                    url,
                );
            })
            .catch(function () { /* silent */ });
    }

    // Run after the layout's initial render so the banner DOM exists.
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', check);
    } else {
        setTimeout(check, 100);
    }
})();


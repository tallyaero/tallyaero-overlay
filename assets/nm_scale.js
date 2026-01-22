/**
 * Custom nautical miles scale bar with ruler-style design
 * Shows larger scale bars for better visibility
 */

(function() {
    'use strict';

    var FT_PER_NM = 6076.12;
    var MI_PER_NM = 1.15078;

    // NM increments available
    var nmValues = [0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 50, 100];

    // Target bar width range (pixels) - larger for better visibility
    var MIN_BAR_WIDTH = 120;
    var MAX_BAR_WIDTH = 250;

    function getPixelsPerNM() {
        // Get the original scale line to calculate pixels per unit
        var originalLine = document.querySelector('.leaflet-control-scale-line');
        if (!originalLine) return null;

        var text = originalLine.textContent;
        var width = originalLine.offsetWidth;

        if (!text || !width) return null;

        var match = text.match(/([\d.]+)\s*(ft|mi)/i);
        if (!match) return null;

        var value = parseFloat(match[1]);
        var unit = match[2].toLowerCase();

        // Convert to NM
        var nmValue;
        if (unit === 'ft') {
            nmValue = value / FT_PER_NM;
        } else if (unit === 'mi') {
            nmValue = value / MI_PER_NM;
        } else {
            return null;
        }

        // Pixels per nautical mile at current zoom
        return width / nmValue;
    }

    function findBestNMValue(pixelsPerNM) {
        if (!pixelsPerNM) return { nm: 1, width: 150 };

        // Find NM value that gives bar width in target range
        for (var i = 0; i < nmValues.length; i++) {
            var width = nmValues[i] * pixelsPerNM;
            if (width >= MIN_BAR_WIDTH && width <= MAX_BAR_WIDTH) {
                return { nm: nmValues[i], width: width };
            }
        }

        // If nothing in range, find closest to target
        var targetWidth = (MIN_BAR_WIDTH + MAX_BAR_WIDTH) / 2;
        var bestNM = nmValues[0];
        var bestDiff = Math.abs(nmValues[0] * pixelsPerNM - targetWidth);

        for (var j = 1; j < nmValues.length; j++) {
            var diff = Math.abs(nmValues[j] * pixelsPerNM - targetWidth);
            if (diff < bestDiff) {
                bestNM = nmValues[j];
                bestDiff = diff;
            }
        }

        return { nm: bestNM, width: bestNM * pixelsPerNM };
    }

    function createCustomScale(originalScale) {
        // Remove any existing custom scale first
        var existing = document.querySelector('.nm-scale-custom');
        if (existing) {
            existing.remove();
        }

        // Hide original scale visually but keep it updating
        originalScale.style.opacity = '0';
        originalScale.style.pointerEvents = 'none';
        originalScale.style.position = 'absolute';

        var container = document.createElement('div');
        container.className = 'nm-scale-custom';
        container.style.cssText = `
            position: absolute;
            bottom: 25px;
            left: 10px;
            z-index: 1000;
            background: linear-gradient(135deg, rgba(255,255,255,0.5) 0%, rgba(240,245,250,0.5) 100%);
            padding: 8px 12px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.8);
            font-family: 'Inter', -apple-system, sans-serif;
            border: 1px solid rgba(0,0,0,0.1);
            backdrop-filter: blur(4px);
            transition: width 0.15s ease-out;
        `;

        // Ruler bar with segments
        var ruler = document.createElement('div');
        ruler.className = 'nm-ruler';
        ruler.style.cssText = `
            display: flex;
            height: 12px;
            border-radius: 2px;
            overflow: hidden;
            box-shadow: 0 1px 2px rgba(0,0,0,0.15);
            width: 150px;
        `;

        for (var i = 0; i < 4; i++) {
            var segment = document.createElement('div');
            segment.style.cssText = `
                flex: 1;
                background: ${i % 2 === 0 ? 'linear-gradient(180deg, #1a1a2e 0%, #16213e 100%)' : 'linear-gradient(180deg, #f8f9fa 0%, #e9ecef 100%)'};
                border-right: ${i < 3 ? '1px solid rgba(0,0,0,0.2)' : 'none'};
            `;
            ruler.appendChild(segment);
        }

        container.appendChild(ruler);

        // Tick marks
        var ticks = document.createElement('div');
        ticks.className = 'nm-ticks';
        ticks.style.cssText = `
            display: flex;
            justify-content: space-between;
            margin-top: 2px;
            width: 150px;
        `;

        for (var j = 0; j <= 4; j++) {
            var tick = document.createElement('div');
            tick.style.cssText = `
                width: 2px;
                height: ${j === 0 || j === 4 ? '8px' : '5px'};
                background: #333;
            `;
            ticks.appendChild(tick);
        }

        container.appendChild(ticks);

        // Label
        var label = document.createElement('div');
        label.className = 'nm-label';
        label.style.cssText = `
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 4px;
            font-size: 12px;
            font-weight: 600;
            color: #1a1a2e;
            width: 150px;
        `;

        var startLabel = document.createElement('span');
        startLabel.textContent = '0';
        startLabel.style.opacity = '0.6';

        var endLabel = document.createElement('span');
        endLabel.className = 'nm-value';
        endLabel.textContent = '1 nm';
        endLabel.style.cssText = `
            background: linear-gradient(135deg, #0f4c75 0%, #1a1a2e 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            font-weight: 700;
        `;

        label.appendChild(startLabel);
        label.appendChild(endLabel);
        container.appendChild(label);

        originalScale.parentNode.appendChild(container);

        return container;
    }

    function updateCustomScale(container) {
        if (!container) return;

        var pixelsPerNM = getPixelsPerNM();
        if (!pixelsPerNM) return;

        var best = findBestNMValue(pixelsPerNM);
        var width = Math.round(best.width);

        var ruler = container.querySelector('.nm-ruler');
        var ticks = container.querySelector('.nm-ticks');
        var label = container.querySelector('.nm-label');
        var valueLabel = container.querySelector('.nm-value');

        if (ruler) ruler.style.width = width + 'px';
        if (ticks) ticks.style.width = width + 'px';
        if (label) label.style.width = width + 'px';
        if (valueLabel) valueLabel.textContent = best.nm + ' nm';

        // Resize container to fit content
        container.style.width = (width + 24) + 'px'; // 24px for padding
    }

    var customScale = null;

    function init() {
        var originalScale = document.querySelector('.leaflet-control-scale');
        if (!originalScale) {
            console.log('NM Scale: Waiting for scale control...');
            setTimeout(init, 500);
            return;
        }

        var scaleLine = originalScale.querySelector('.leaflet-control-scale-line');
        if (!scaleLine) {
            console.log('NM Scale: Waiting for scale line...');
            setTimeout(init, 500);
            return;
        }

        console.log('NM Scale: Found scale, text:', scaleLine.textContent);

        customScale = createCustomScale(originalScale);
        updateCustomScale(customScale);

        var observer = new MutationObserver(function() {
            updateCustomScale(customScale);
        });

        observer.observe(originalScale, {
            childList: true,
            subtree: true,
            characterData: true,
            attributes: true
        });

        setInterval(function() {
            updateCustomScale(customScale);
        }, 300);

        console.log('NM Scale: Custom scale initialized');
    }

    // Multiple init attempts to handle various loading scenarios
    function startInit() {
        setTimeout(init, 1000);
        setTimeout(init, 2000);
        setTimeout(init, 3000);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', startInit);
    } else {
        startInit();
    }

    window.addEventListener('load', startInit);

})();

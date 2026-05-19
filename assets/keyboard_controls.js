/**
 * Keyboard controls for time scrubber sliders
 * Left/Right arrow keys control the currently visible slider
 */
(function() {
    // ============ Time Scrubber Controls ============
    // Map of slider container IDs
    const sliderContainers = [
        'impossibleturn-slider-container',
        'poweroff180-slider-container',
        'engineout-slider-container',
        'steepturn-slider-container',
        'chandelle-slider-container',
        'lazy8-slider-container',
        'steepspiral-slider-container',
        'sturn-slider-container',
        'turnspoint-slider-container',
        'rectcourse-slider-container',
        'pylons-slider-container'
    ];

    // Find the currently visible slider container
    function findVisibleSliderContainer() {
        for (const containerId of sliderContainers) {
            const container = document.getElementById(containerId);
            if (container) {
                const style = window.getComputedStyle(container);
                if (style.display !== 'none') {
                    return container;
                }
            }
        }
        return null;
    }

    // Handle keyboard events
    function handleKeyDown(event) {
        // Bail on the synthetic keydown we re-dispatch to the slider
        // handle below — otherwise the bubbling event re-enters this
        // capture-phase listener on document and recurses until the
        // call stack overflows. Only the real user keypress is trusted.
        if (!event.isTrusted) return;

        // Only handle left/right arrow keys for sliders
        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;

        // Don't handle if user is typing in an input field (except slider handles)
        const activeElement = document.activeElement;
        const isSliderHandle = activeElement && activeElement.classList.contains('rc-slider-handle');

        if (activeElement && !isSliderHandle && (
            activeElement.tagName === 'INPUT' ||
            activeElement.tagName === 'TEXTAREA' ||
            activeElement.isContentEditable
        )) {
            return;
        }

        const container = findVisibleSliderContainer();
        if (!container) return;

        // Find the slider handle
        const handle = container.querySelector('.rc-slider-handle');
        if (!handle) return;

        // Prevent default page scrolling
        event.preventDefault();

        // Focus the handle if not already focused
        if (document.activeElement !== handle) {
            handle.focus();
        }

        // Dispatch a keyboard event to the handle
        const keyEvent = new KeyboardEvent('keydown', {
            key: event.key,
            code: event.code,
            keyCode: event.keyCode,
            which: event.which,
            shiftKey: event.shiftKey,
            bubbles: true,
            cancelable: true
        });

        handle.dispatchEvent(keyEvent);
    }

    // Add event listener when DOM is ready
    function init() {
        // Use capture phase to intercept before other handlers
        document.addEventListener('keydown', handleKeyDown, true);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

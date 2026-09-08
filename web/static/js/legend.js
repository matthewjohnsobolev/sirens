/* Легенда мапи: логіка відкриття, закриття та доступності.
   Забезпечує перемикання поповера, закриття кліком повз віджет і по Escape. */
(function () {
    'use strict';

    function toggleLegend(force) {
        var dock = document.getElementById('legendDock');
        if (!dock) return;
        var btn = dock.querySelector('.legend-bar-btn');
        var popover = document.getElementById('legendPopover');

        var isCurrentlyOpen = dock.classList.contains('is-open');
        var shouldOpen = typeof force === 'boolean' ? force : !isCurrentlyOpen;

        dock.classList.toggle('is-open', shouldOpen);
        if (btn) btn.setAttribute('aria-expanded', shouldOpen);
        if (popover) popover.setAttribute('aria-hidden', !shouldOpen);
    }

    // Експортуємо для виклику з inline onclick
    window.toggleLegend = toggleLegend;

    // Закриття при кліку повз віджет (по сторінці або карті)
    document.addEventListener('click', function (e) {
        var dock = document.getElementById('legendDock');
        if (!dock || !dock.classList.contains('is-open')) return;
        if (!dock.contains(e.target)) {
            toggleLegend(false);
        }
    });

    // Закриття по Escape з поверненням фокусу на кнопку
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' || e.key === 'Esc') {
            var dock = document.getElementById('legendDock');
            if (dock && dock.classList.contains('is-open')) {
                toggleLegend(false);
                var btn = dock.querySelector('.legend-bar-btn');
                if (btn) btn.focus();
            }
        }
    });

    // Якщо екземпляр карти Leaflet вже є або з'явиться, клік по карті закриває поповер
    function bindMapClick() {
        if (window.sirensMap && window.sirensMap.on) {
            window.sirensMap.on('click', function () {
                toggleLegend(false);
            });
        }
    }

    if (window.sirensMap) {
        bindMapClick();
    } else {
        document.addEventListener('DOMContentLoaded', bindMapClick);
    }
})();

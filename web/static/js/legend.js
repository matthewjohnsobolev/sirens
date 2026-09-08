/* Легенда мапи: логіка відкриття/закриття мобільного Bottom Sheet,
   керування доступністю та підтримка свайпу вниз для закриття. */
(function () {
    'use strict';

    var sheet = null;
    var scrim = null;
    var btn = null;
    var handle = null;

    function initElements() {
        if (!sheet) sheet = document.getElementById('legendSheet');
        if (!scrim) scrim = document.getElementById('legendScrim');
        if (!btn) btn = document.getElementById('legendInfoBtn');
        if (!handle) handle = document.getElementById('legendSheetHandle');
    }

    function openLegendSheet() {
        initElements();
        if (!sheet || !scrim) return;

        sheet.classList.add('is-open');
        scrim.classList.add('is-open');
        sheet.setAttribute('aria-hidden', 'false');
        scrim.setAttribute('aria-hidden', 'false');
        if (btn) btn.setAttribute('aria-expanded', 'true');

        // Фіксуємо прокручування підкладки під час відкритої шторки
        document.body.style.overflow = 'hidden';

        var closeBtn = sheet.querySelector('.legend-sheet__close');
        if (closeBtn) closeBtn.focus();
    }

    function closeLegendSheet() {
        initElements();
        if (!sheet || !scrim) return;

        sheet.classList.remove('is-open');
        scrim.classList.remove('is-open');
        sheet.setAttribute('aria-hidden', 'true');
        scrim.setAttribute('aria-hidden', 'true');
        sheet.style.transform = '';

        document.body.style.overflow = '';

        if (btn) {
            btn.setAttribute('aria-expanded', 'false');
            btn.focus();
        }
    }

    function toggleLegendSheet() {
        initElements();
        if (sheet && sheet.classList.contains('is-open')) {
            closeLegendSheet();
        } else {
            openLegendSheet();
        }
    }

    // Експорт функцій у глобальну область видимості
    window.openLegendSheet = openLegendSheet;
    window.closeLegendSheet = closeLegendSheet;
    window.toggleLegendSheet = toggleLegendSheet;
    window.toggleLegend = toggleLegendSheet; // Для зворотної сумісності

    // Закриття по клавіші Escape
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' || e.key === 'Esc') {
            initElements();
            if (sheet && sheet.classList.contains('is-open')) {
                closeLegendSheet();
            }
        }
    });

    // Підтримка свайпу вниз (drag to dismiss) за ручку шторки
    function setupDragToClose() {
        initElements();
        if (!handle || !sheet) return;

        var startY = 0;
        var deltaY = 0;
        var dragging = false;
        var DRAG_THRESHOLD = 50;

        handle.addEventListener('touchstart', function (e) {
            if (!sheet.classList.contains('is-open')) return;
            if (e.touches.length !== 1) return;

            startY = e.touches[0].clientY;
            deltaY = 0;
            dragging = true;
            sheet.style.transition = 'none';
        }, { passive: true });

        handle.addEventListener('touchmove', function (e) {
            if (!dragging) return;
            var currentY = e.touches[0].clientY;
            deltaY = currentY - startY;

            if (deltaY > 0) {
                sheet.style.transform = 'translateY(' + deltaY + 'px)';
            } else {
                sheet.style.transform = 'translateY(0)';
            }
        }, { passive: true });

        function endDrag() {
            if (!dragging) return;
            dragging = false;
            sheet.style.transition = '';

            if (deltaY > DRAG_THRESHOLD) {
                closeLegendSheet();
            } else {
                sheet.style.transform = '';
            }
            deltaY = 0;
        }

        handle.addEventListener('touchend', endDrag, { passive: true });
        handle.addEventListener('touchcancel', endDrag, { passive: true });
    }

    // Закриття шторки при кліку по карті Leaflet
    function bindMapClick() {
        if (window.sirensMap && window.sirensMap.on) {
            window.sirensMap.on('click', function () {
                initElements();
                if (sheet && sheet.classList.contains('is-open')) {
                    closeLegendSheet();
                }
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            setupDragToClose();
            bindMapClick();
        });
    } else {
        setupDragToClose();
        bindMapClick();
    }
})();

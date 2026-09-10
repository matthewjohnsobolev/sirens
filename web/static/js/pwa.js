(function () {
    'use strict';

    // В iOS Safari у режимі standalone перехід за звичайним посиланням <a>
    // на інший піддомен (status.sirens.live) за замовчуванням відкриває Mobile Safari.
    // Програмний перехід через window.location.href утримує навігацію
    // всередині того самого standalone-вікна PWA.
    var isStandalone = ('standalone' in window.navigator && window.navigator.standalone) ||
                       (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches);

    if (!isStandalone) return;

    document.addEventListener('click', function (e) {
        var anchor = e.target && e.target.closest ? e.target.closest('a') : null;
        if (!anchor || !anchor.href) return;
        if (e.defaultPrevented) return;
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;

        try {
            var url = new URL(anchor.href, window.location.href);
            var isSirens = url.hostname === 'status.sirens.live' ||
                           url.hostname === 'sirens.live' ||
                           url.hostname.endsWith('.sirens.live') ||
                           url.hostname === window.location.hostname;

            if (isSirens && (url.protocol === 'http:' || url.protocol === 'https:')) {
                e.preventDefault();
                window.location.href = anchor.href;
            }
        } catch (err) {}
    }, false);
})();

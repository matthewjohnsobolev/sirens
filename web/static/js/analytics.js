(function () {
    'use strict';

    // Хелпер приходить з _analytics.html і мовчить, коли gtag.js вирізав
    // блокувальник. Перевірка лишається на випадок, коли сторінку віддали
    // без партіала: аналітика не повинна ламати мапу.
    function send(name, params) {
        if (window.track) window.track(name, params);
    }

    var PILL_STATES = {
        'green-oblast-button': 'idle',
        'orange-oblast-button': 'alert',
        'hatched-oblast-button': 'partial',
        'yellow-oblast-button': 'shelling',
        'red-oblast-button': 'explosion',
        'gray-oblast-button': 'unknown'
    };

    function pillState(link) {
        var button = link.querySelector('button');
        if (!button) return 'unknown';
        for (var cls in PILL_STATES) {
            if (button.classList.contains(cls)) return PILL_STATES[cls];
        }
        return 'unknown';
    }

    // Район усередині обласного попапа має власну назву, місто — свою,
    // область — свою. Беремо найточнішу з наявних.
    function regionName(node) {
        var city = node.closest('.popup-city');
        var name = city && city.querySelector('.popup-city-name');
        if (name) return name.textContent.trim();

        var popup = node.closest('.leaflet-popup-content');
        if (!popup) return 'unknown';
        name = popup.querySelector('.channel-popup-name') || popup.querySelector('.oblast-name');
        return name ? name.textContent.trim() : 'unknown';
    }

    function channelName(href) {
        var match = /domain=([\w-]+)/.exec(href);
        return match ? match[1] : 'unknown';
    }

    document.addEventListener('click', function (event) {
        var target = event.target;
        if (!target || !target.closest) return;

        var link = target.closest('.oblast-button-link');
        if (link) {
            var href = link.getAttribute('href') || '';
            if (href.indexOf('tg://resolve') === 0) {
                send('telegram_subscribe_click', {
                    channel_name: channelName(href),
                    region_name: regionName(link),
                    link_location: 'map_popup'
                });
            } else {
                send('alert_source_open', {
                    region_name: regionName(link),
                    threat_state: pillState(link)
                });
            }
            return;
        }

        if (target.closest('.map-ctl--issue')) {
            send('report_cta_click', { link_location: 'map' });
            return;
        }

        var control = target.closest('.map-ctl--markers');
        if (control) {
            // Свій обробник кнопки вже відпрацював на етапі спливання,
            // тож aria-pressed показує новий стан: натиснута кнопка —
            // маркери приховані.
            send('markers_toggle', {
                markers_visible: control.getAttribute('aria-pressed') === 'true' ? 'false' : 'true'
            });
            return;
        }

        var status = target.closest('.map-ctl--status, .map-chip');
        if (status) {
            send('status_page_open', {
                system_state: status.getAttribute('data-state') || 'unknown',
                link_location: status.classList.contains('map-chip') ? 'map_chip' : 'map'
            });
        }
    });
})();

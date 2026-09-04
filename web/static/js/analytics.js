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

        if (target.closest('.contact-button')) {
            send('report_cta_click', { link_location: 'map' });
            return;
        }

        var control = target.closest('.layer-control');
        if (control) {
            // Свій обробник кнопки вже відпрацював на етапі спливання,
            // тож іконка показує новий стан.
            var icon = control.querySelector('.layer-control-icon');
            var src = icon ? icon.getAttribute('src') || '' : '';
            send('markers_toggle', {
                markers_visible: src.indexOf('markers-on-button-icon') === -1 ? 'true' : 'false'
            });
        }
    });
})();

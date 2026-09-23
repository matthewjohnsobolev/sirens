(function () {
    'use strict';

    
    
    
    function send(name, params) {
        if (window.track) window.track(name, params);
    }

    
    
    
    function pillState(link) {
        var button = link.querySelector('button');
        return (button && button.getAttribute('data-state')) || 'unknown';
    }

    
    
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


        if (target.closest('.map-ctl--time')) {
            send('reload_click', { link_location: 'map' });
            return;
        }

        var status = target.closest('.map-chip');
        if (status) {
            send('status_page_open', {
                system_state: status.getAttribute('data-state') || 'unknown',
                link_location: 'map_chip'
            });
        }
    });
})();

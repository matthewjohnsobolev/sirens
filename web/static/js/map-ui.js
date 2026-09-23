
(function () {
    'use strict';

    var map = window.sirensMap;
    if (!map || !window.L) return;

    
    
    var STATUS_URL = 'https://status.sirens.live/status.json';
    var STATUS_PAGE = 'https://status.sirens.live';
    var POLL_MS = 60000;

    
    
    
    var SPIN_MS = 900;

    
    
    var calm = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)');

    
    var STALE_MS = 20 * 60 * 1000;

    var isClientOnline = typeof navigator !== 'undefined' ? navigator.onLine !== false : true;
    var showRestoredUntil = 0;
    var restoredTimer = null;
    var restoredText = 'ЗВ\'ЯЗОК ВІДНОВЛЕНО';
    var lastAlarmState = null;
    var lastApiSuccess = null;
    var lastApiError = 0;
    var statusData = null;

    
    
    
    
    var STATES = {
        none: { state: 'ok', word: 'Все працює', loud: false },
        minor: { state: 'minor', word: 'Часткові збої', loud: false },
        major: { state: 'down', word: 'Дані не оновлюються', loud: true },
        critical: { state: 'down', word: 'Дані не оновлюються', loud: true },
        maintenance: { state: 'mnt', word: 'Планові роботи', loud: false },
        unknown: { state: 'nodata', word: 'Дані не оновлюються', loud: false }
    };
    var UNKNOWN = STATES.unknown;

    
    
    var kyivTime = new Intl.DateTimeFormat('uk-UA', {
        timeZone: 'Europe/Kyiv',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false
    });

    var tile = null;
    var chip = null;
    var currentInfo = UNKNOWN;

    function updateLabel() {
        if (!tile) return;
        var text = 'Оновити дані';
        tile.title = text;
        tile.setAttribute('aria-label', text);
    }

    
    
    
    function control(position, build) {
        var element = null;

        var Control = L.Control.extend({
            options: { position: position },
            onAdd: function () {
                if (!element) {
                    element = build();
                    L.DomEvent.disableClickPropagation(element);
                    L.DomEvent.disableScrollPropagation(element);
                }

                return element;
            }
        });

        return new Control();
    }

    
    
    function label(element, text) {
        element.title = text;
        element.setAttribute('aria-label', text);
    }

    function icon(parent, modifier) {
        var element = L.DomUtil.create('span', 'map-ctl-icon map-ctl-icon--' + modifier, parent);
        element.setAttribute('aria-hidden', 'true');
        return element;
    }

    
    
    
    function iconMarkup(modifier) {
        return '<span class="map-ctl-icon map-ctl-icon--' + modifier + '" aria-hidden="true"></span>';
    }

    
    
    
    
    function flash(element, name) {
        
        
        if (calm && calm.matches) return;

        if (!element.sirensFlash) {
            element.sirensFlash = {};

            
            
            L.DomEvent.on(element, 'animationend', function () {
                for (var cls in element.sirensFlash) {
                    if (element.sirensFlash[cls]) {
                        L.DomUtil.removeClass(element, cls);
                        element.sirensFlash[cls] = false;
                    }
                }
            });
        }

        L.DomUtil.removeClass(element, name);
        element.sirensFlash[name] = true;

        
        
        void element.offsetWidth;
        L.DomUtil.addClass(element, name);
    }

    
    
    
    function spinTail(since) {
        if (calm && calm.matches) return 0;
        var elapsed = Date.now() - since;
        var rem = elapsed % SPIN_MS;
        return (rem === 0 && elapsed > 0) ? 0 : SPIN_MS - rem;
    }


    
    
    function timeTile() {
        var button = L.DomUtil.create('button', 'map-ctl map-ctl--time');
        button.type = 'button';

        icon(button, 'refresh');

        var stamp = L.DomUtil.create('span', 'map-sync-time', button);

        tile = button;

        function say() {
            var moment = window.SirensThreats ? SirensThreats.at() : null;
            var at = moment ? kyivTime.format(moment) : null;

            
            
            var text = at || '--:--';
            updateLabel();

            
            
            
            if (stamp.textContent === text) return;
            stamp.textContent = text;
            flash(stamp, 'is-fresh');
        }

        L.DomEvent.on(button, 'click', function (e) {
            L.DomEvent.stop(e);
            if (button.getAttribute('aria-busy') === 'true') return;
            button.setAttribute('aria-busy', 'true');

            var since = Date.now();

            function done() {
                setTimeout(function () {
                    button.removeAttribute('aria-busy');
                }, spinTail(since));
            }

            poll();
            if (window.SirensThreats && window.SirensThreats.load) {
                SirensThreats.load(true).then(done, done);
            } else {
                done();
            }
        });

        if (window.SirensThreats) {
            SirensThreats.onPaint(say);
        }
        say();

        return button;
    }

    
    function issueTile() {
        var link = L.DomUtil.create('a', 'map-ctl map-ctl--issue');
        link.href = '/issue';
        label(link, 'Повідомити про збій');
        var flag = L.DomUtil.create('span', 'map-ctl-icon map-ctl-icon--flag material-symbols-rounded', link);
        flag.setAttribute('aria-hidden', 'true');
        flag.textContent = 'flag';
        return link;
    }

    
    
    
    
    var chipHideTimer = null;

    function statusChip() {
        var live = L.DomUtil.create('div', 'map-chip-live', map.getContainer());
        live.setAttribute('aria-live', 'polite');

        var link = L.DomUtil.create('a', 'map-chip', live);
        link.rel = 'noopener';
        link.hidden = true;

        var dot = L.DomUtil.create('span', 'map-chip-dot', link);
        dot.setAttribute('aria-hidden', 'true');

        var text = L.DomUtil.create('span', 'map-chip-text', link);

        L.DomEvent.disableClickPropagation(link);
        L.DomEvent.disableScrollPropagation(link);

        
        
        
        L.DomEvent.on(link, 'click', function (e) {
            if (link.dataset.state === 'offline' || link.dataset.state === 'ok' || link.dataset.state === 'beta') {
                L.DomEvent.stop(e);
                if (link.dataset.state === 'offline') {
                    poll();
                    if (window.SirensThreats && window.SirensThreats.load) {
                        SirensThreats.load(true).catch(function () {});
                    }
                }
            }
        });

        chip = { root: link, text: text, said: null };
    }

    function showChip(alarm) {
        if (!chip) return;
        if (chipHideTimer) {
            clearTimeout(chipHideTimer);
            chipHideTimer = null;
        }

        chip.root.dataset.state = alarm.state;
        chip.text.textContent = alarm.text;

        if (alarm.state === 'offline' || alarm.state === 'ok' || alarm.state === 'beta') {
            chip.root.removeAttribute('href');
            chip.root.setAttribute('role', 'status');
        } else {
            chip.root.href = STATUS_PAGE;
            chip.root.setAttribute('role', 'link');
        }

        if (chip.root.hidden) {
            chip.root.hidden = false;
            L.DomUtil.removeClass(chip.root, 'is-leaving');
            L.DomUtil.removeClass(chip.root, 'is-visible');
            void chip.root.offsetWidth;
            L.DomUtil.addClass(chip.root, 'is-visible');
        } else {
            L.DomUtil.removeClass(chip.root, 'is-leaving');
            L.DomUtil.addClass(chip.root, 'is-visible');
        }
    }

    function hideChip() {
        if (!chip || chip.root.hidden) return;
        if (chip.root.classList.contains('is-leaving')) return;

        if (calm && calm.matches) {
            chip.root.hidden = true;
            L.DomUtil.removeClass(chip.root, 'is-visible');
            L.DomUtil.removeClass(chip.root, 'is-leaving');
            chip.text.textContent = '';
            chip.said = null;
            return;
        }

        L.DomUtil.removeClass(chip.root, 'is-visible');
        L.DomUtil.addClass(chip.root, 'is-leaving');

        if (chipHideTimer) clearTimeout(chipHideTimer);
        chipHideTimer = setTimeout(function () {
            chipHideTimer = null;
            if (chip && chip.root.classList.contains('is-leaving')) {
                chip.root.hidden = true;
                L.DomUtil.removeClass(chip.root, 'is-leaving');
                chip.text.textContent = '';
                chip.said = null;
            }
        }, 250);
    }

    function render(info, alarm) {
        currentInfo = info;
        if (tile) {
            tile.dataset.state = info.state;

            
            
            
            
            updateLabel();
        }

        if (!chip) return;

        
        
        var said = alarm ? alarm.state + '|' + alarm.text : null;
        if (said === chip.said && !chip.root.hidden && !chip.root.classList.contains('is-leaving')) return;
        chip.said = said;

        if (!alarm) {
            hideChip();
            return;
        }

        showChip(alarm);
    }

    function triggerRestored(text) {
        restoredText = text || 'ЗВ\'ЯЗОК ВІДНОВЛЕНО';
        showRestoredUntil = Date.now() + 4000;
        if (restoredTimer) clearTimeout(restoredTimer);
        restoredTimer = setTimeout(function () {
            restoredTimer = null;
            updateState();
        }, 4000);
    }

    function setClientOnline(online) {
        if (!online) {
            var wasOnline = isClientOnline;
            var hadRestored = showRestoredUntil > 0;
            isClientOnline = false;
            showRestoredUntil = 0;
            if (restoredTimer) {
                clearTimeout(restoredTimer);
                restoredTimer = null;
            }
            if (wasOnline || hadRestored) {
                updateState();
            }
        } else {
            if (!isClientOnline) {
                isClientOnline = true;
                triggerRestored('ЗВ\'ЯЗОК ВІДНОВЛЕНО');
                updateState();
            }
        }
    }

    function isThreatsStale() {
        if (!window.SirensThreats || !window.SirensThreats.at) return false;
        var moment = window.SirensThreats.at();
        if (!moment) return false;
        return Date.now() - moment.getTime() > STALE_MS;
    }

    function isFreshApi() {
        if (!lastApiSuccess) return false;
        if (lastApiError > lastApiSuccess) return false;
        
        
        return Date.now() - lastApiSuccess < 180000;
    }

    
    
    
    function alarmFor(info) {
        if (!isClientOnline) {
            return { state: 'offline', text: 'НЕМАЄ ЗВ\'ЯЗКУ' };
        }

        if (Date.now() < showRestoredUntil) {
            return { state: 'ok', text: restoredText };
        }

        var syncIso = telemetryAt(statusData);
        var sourceStale = isStale(syncIso);
        var threatsStale = isThreatsStale();

        if (sourceStale || threatsStale) {
            return { state: 'down', text: 'ДАНІ НЕ ОНОВЛЮЮТЬСЯ' };
        }

        if (info.state === 'down' || info.loud) {
            
            
            
            if (!isFreshApi()) {
                return { state: 'down', text: 'ДАНІ НЕ ОНОВЛЮЮТЬСЯ' };
            }
        }

        return { state: 'beta', text: 'БЕТА' };
    }

    function isStale(iso) {
        if (!iso) return false;
        var date = new Date(iso);
        return !isNaN(date.getTime()) && Date.now() - date.getTime() > STALE_MS;
    }

    
    
    function telemetryAt(data) {
        if (!data || !data.telemetry) return null;
        return data.telemetry.synced_at || data.telemetry.last_source_sync_at || data.telemetry.updated_at || null;
    }

    function updateState() {
        var indicator = statusData && statusData.status ? statusData.status.indicator : null;
        var info = STATES[indicator] || UNKNOWN;
        var alarm = alarmFor(info);

        
        
        if (alarm && alarm.state === 'beta' && lastAlarmState === 'down' && isClientOnline) {
            triggerRestored('ДАНІ ОНОВЛЕНО');
            alarm = { state: 'ok', text: 'ДАНІ ОНОВЛЕНО' };
        }

        if (alarm) {
            lastAlarmState = alarm.state;
        } else {
            lastAlarmState = null;
        }

        render(info, alarm);
    }

    var POLL_TIMEOUT_MS = 6000;

    function poll() {
        if (typeof navigator !== 'undefined' && navigator.onLine === false) {
            setClientOnline(false);
            return;
        }

        var controller = window.AbortController ? new AbortController() : null;
        var timeoutId = controller
            ? setTimeout(function () { controller.abort(); }, POLL_TIMEOUT_MS)
            : null;

        fetch(STATUS_URL, {
            cache: 'no-store',
            signal: controller ? controller.signal : undefined
        })
            .then(function (response) {
                if (!response.ok) throw new Error('status ' + response.status);
                return response.json();
            })
            .then(function (data) {
                statusData = data;
                setClientOnline(true);
                updateState();
            })
            .catch(function (err) {
                if (!navigator.onLine || (err && (err.name === 'TypeError' || err.name === 'AbortError' || String(err).indexOf('fetch') !== -1 || String(err).indexOf('NetworkError') !== -1 || String(err).indexOf('Load failed') !== -1))) {
                    setClientOnline(false);
                } else {
                    updateState();
                }
            })
            .finally(function () {
                if (timeoutId) clearTimeout(timeoutId);
            });
    }

    
    
    
    function respondToPress(button) {
        L.DomEvent.on(button, 'click', function () {
            if (L.DomUtil.hasClass(button, 'leaflet-disabled')) return;
            flash(button, 'is-pressed');
        });
    }

    var zoomControl = L.control.zoom({
        position: 'topleft',
        zoomInText: iconMarkup('zoom-in'),
        zoomInTitle: 'Наблизити',
        zoomOutText: iconMarkup('zoom-out'),
        zoomOutTitle: 'Віддалити'
    }).addTo(map);

    var zoomContainer = zoomControl.getContainer();
    if (zoomContainer) {
        var zoomButtons = zoomContainer.querySelectorAll('a');
        for (var i = 0; i < zoomButtons.length; i++) respondToPress(zoomButtons[i]);
    }

    
    
    
    control('bottomleft', issueTile).addTo(map);
    control('bottomleft', timeTile).addTo(map);

    statusChip();

    
    
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
        isClientOnline = false;
        render(UNKNOWN, alarmFor(UNKNOWN));
    } else {
        render(UNKNOWN, alarmFor(UNKNOWN));
    }

    poll();
    setInterval(poll, POLL_MS);

    
    
    document.addEventListener('visibilitychange', function () {
        if (!document.hidden) {
            if (typeof navigator !== 'undefined' && navigator.onLine === false) {
                setClientOnline(false);
            } else {
                poll();
            }
        }
    });

    
    
    window.addEventListener('pageshow', function () {
        if (typeof navigator !== 'undefined' && navigator.onLine === false) {
            setClientOnline(false);
        } else {
            poll();
        }
    });

    
    
    window.addEventListener('online', function () {
        if (typeof navigator !== 'undefined' && navigator.onLine === false) {
            setClientOnline(false);
        } else {
            poll();
        }
    });
    window.addEventListener('offline', function () { setClientOnline(false); });

    if (window.SirensThreats) {
        if (window.SirensThreats.at && window.SirensThreats.at()) {
            lastApiSuccess = window.SirensThreats.at().getTime();
        }
        window.SirensThreats.onSuccess(function () {
            lastApiSuccess = Date.now();
            if (typeof navigator !== 'undefined' && navigator.onLine === false) {
                setClientOnline(false);
            } else {
                if (!isClientOnline) {
                    setClientOnline(true);
                } else if (lastAlarmState === 'down' || (chip && chip.root && !chip.root.hidden && chip.root.dataset.state === 'down')) {
                    poll();
                    updateState();
                }
            }
        });
        window.SirensThreats.onError(function (err) {
            lastApiError = Date.now();
            if (!navigator.onLine || (err && (err.name === 'TypeError' || err.name === 'AbortError' || String(err).indexOf('fetch') !== -1 || String(err).indexOf('NetworkError') !== -1 || String(err).indexOf('Load failed') !== -1))) {
                setClientOnline(false);
            } else {
                poll();
            }
        });
    }
})();

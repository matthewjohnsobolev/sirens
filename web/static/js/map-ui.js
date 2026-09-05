/* Навігаційні кнопки й стан сервісу на мапі.
   Кожна кнопка — окремий контрол Leaflet, тож стопку тримає сам Leaflet:
   порядок задається порядком addTo, відступи — кутовим контейнером.
   Стан сервісу говорить двома голосами: крапка на плитці — завжди,
   темний чіп — лише коли є що сказати. */
(function () {
    'use strict';

    var map = window.sirensMap;
    if (!map || !window.L) return;

    // Статус-сторінка кешує свій JSON на 60 секунд, тож частіше питати
    // нема сенсу: відповідь усе одно буде та сама.
    var STATUS_URL = 'https://status.sirens.live/status.json';
    var STATUS_PAGE = 'https://status.sirens.live';
    var POLL_MS = 60000;

    // Телеметрію в KV кладе бот: за подіями і раз на 15 хвилин
    // (TELEMETRY_PERIODIC_SYNC_INTERVAL в alerts/main.py). TTL у ключа
    // немає, тож коли збір даних стає, час не зникає, а застигає. Поріг —
    // потрійний запас від періоду: ловить зупинку, але не сварить за
    // пропущений такт.
    var STALE_MS = 45 * 60 * 1000;

    // indicator зі status.json → стан крапки, слово для скрінрідера й те,
    // чи має сервіс говорити вголос. Крапка каже стан кольором, тож слово
    // читається лише з підказки — але без нього доступна назва лишила б
    // стан невідомим. Слова ті самі, що в STATUS_WORDS на статус-сторінці.
    var STATES = {
        none: { state: 'ok', word: 'Все працює', loud: false },
        minor: { state: 'minor', word: 'Часткові збої', loud: false },
        major: { state: 'down', word: 'Не працює', loud: true },
        critical: { state: 'down', word: 'Не працює', loud: true },
        maintenance: { state: 'mnt', word: 'Планові роботи', loud: false },
        unknown: { state: 'nodata', word: 'Немає даних', loud: true }
    };
    var UNKNOWN = STATES.unknown;

    // Час завжди київський: сервіс говорить про Україну, тож «13:54» має
    // означати те саме і для читача з Варшави.
    var kyivTime = new Intl.DateTimeFormat('uk-UA', {
        timeZone: 'Europe/Kyiv',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false
    });

    var tile = null;
    var chip = null;

    function control(position, build) {
        var Control = L.Control.extend({
            options: { position: position },
            onAdd: function () {
                var element = build();
                L.DomEvent.disableClickPropagation(element);
                L.DomEvent.disableScrollPropagation(element);
                return element;
            }
        });

        return new Control();
    }

    // Назва кнопки потрібна і в тултипі, і скрінрідеру: іконка сама по
    // собі не називає нічого.
    function label(element, text) {
        element.title = text;
        element.setAttribute('aria-label', text);
    }

    function icon(parent, modifier) {
        var element = L.DomUtil.create('span', 'map-ctl-icon map-ctl-icon--' + modifier, parent);
        element.setAttribute('aria-hidden', 'true');
        return element;
    }

    // Кнопки зума Leaflet будує сам і кладе цей рядок усередину як HTML.
    // Плюс і мінус — такі самі іконки-маски, як в інших кнопок: уся стопка
    // малюється однаково й не залежить від того, чи приїхав шрифт.
    function iconMarkup(modifier) {
        return '<span class="map-ctl-icon map-ctl-icon--' + modifier + '" aria-hidden="true"></span>';
    }

    function markersButton() {
        var button = L.DomUtil.create('button', 'map-ctl map-ctl--markers');
        button.type = 'button';
        button.setAttribute('aria-pressed', 'false');
        label(button, 'Прибрати маркери');

        // Відкрите око, поки маркери видно; перекреслене — коли сховані.
        var glyph = icon(button, 'markers-on');

        L.DomEvent.on(button, 'click', function () {
            var hidden = map.getContainer().classList.toggle('markers-hidden');
            button.setAttribute('aria-pressed', String(hidden));
            label(button, hidden ? 'Показати маркери' : 'Прибрати маркери');
            glyph.className = 'map-ctl-icon map-ctl-icon--markers-' + (hidden ? 'off' : 'on');
            if (hidden) map.closePopup();
        });

        return button;
    }

    function issueLink() {
        var link = L.DomUtil.create('a', 'map-ctl map-ctl--issue');
        link.href = '/issue';
        label(link, 'Повідомити про збій');
        icon(link, 'issue');
        return link;
    }

    function statusTile() {
        var link = L.DomUtil.create('a', 'map-ctl map-ctl--status');
        link.href = STATUS_PAGE;
        link.rel = 'noopener';
        icon(link, 'status');

        var dot = L.DomUtil.create('span', 'map-ctl-badge', link);
        dot.setAttribute('aria-hidden', 'true');

        tile = link;
        return link;
    }

    // Чіп не стоїть у кутовій стопці, тож і не є контролом Leaflet: його
    // тримає сам контейнер мапи. Обгортка з aria-live лишається в DOM
    // назавжди — порожній регіон має існувати заздалегідь, інакше поява
    // тексту в ньому не озвучиться.
    function statusChip() {
        var live = L.DomUtil.create('div', 'map-chip-live', map.getContainer());
        live.setAttribute('aria-live', 'polite');

        var link = L.DomUtil.create('a', 'map-chip', live);
        link.href = STATUS_PAGE;
        link.rel = 'noopener';
        link.hidden = true;

        var dot = L.DomUtil.create('span', 'map-chip-dot', link);
        dot.setAttribute('aria-hidden', 'true');

        L.DomEvent.disableClickPropagation(link);
        L.DomEvent.disableScrollPropagation(link);

        chip = { root: link, text: L.DomUtil.create('span', 'map-chip-text', link), said: null };
    }

    function render(info, at, alarm) {
        if (tile) {
            tile.dataset.state = info.state;
            label(tile, at
                ? 'Стан системи: ' + info.word.toLowerCase() + '. Дані оновлено о ' + at + '.'
                : 'Стан системи: ' + info.word.toLowerCase() + '.');
        }

        if (!chip) return;

        // Та сама новина щохвилини — не новина: DOM чіпаємо лише коли
        // текст справді змінився, інакше aria-live озвучував би її знову.
        var said = alarm ? alarm.state + '|' + alarm.text : null;
        if (said === chip.said) return;
        chip.said = said;

        if (!alarm) {
            chip.root.hidden = true;
            chip.text.textContent = '';
            return;
        }

        chip.root.dataset.state = alarm.state;
        chip.text.textContent = alarm.text;
        chip.root.hidden = false;
    }

    // Три випадки, коли є що сказати вголос: сервіс ліг, стан невідомий і
    // — окремо — телеметрія застигла, хоча indicator ще каже, що все
    // гаразд. Саме третій робить мапу мовчазно неправдивою, тож його
    // сторожує код, а не читач.
    function alarmFor(info, data, iso, at) {
        if (info.loud) {
            // Слова бере статус-сторінка: хай мапа й вона кажуть про збій
            // однією фразою.
            var headline = data && data.status ? data.status.headline : null;
            return { state: info.state, text: headline || info.word };
        }

        if (!isStale(iso)) return null;
        return { state: 'minor', text: 'Дані не оновлюються з ' + at };
    }

    function isStale(iso) {
        if (!iso) return false;
        var date = new Date(iso);
        return !isNaN(date.getTime()) && Date.now() - date.getTime() > STALE_MS;
    }

    // Час пишеться, коли бот востаннє клав телеметрію в KV. Саме він і
    // застигає, якщо збір даних став. Фолбека на page.updated_at тут бути
    // не може: той завжди «щойно», тож у власному відмовному сценарії
    // підміняв би застиглий час свіжим.
    function telemetryAt(data) {
        return data && data.telemetry ? data.telemetry.updated_at || null : null;
    }

    function formatTime(iso) {
        if (!iso) return null;
        var date = new Date(iso);
        return isNaN(date.getTime()) ? null : kyivTime.format(date);
    }

    function poll() {
        fetch(STATUS_URL)
            .then(function (response) {
                if (!response.ok) throw new Error('status ' + response.status);
                return response.json();
            })
            .then(function (data) {
                var indicator = data && data.status ? data.status.indicator : null;
                var info = STATES[indicator] || UNKNOWN;
                var iso = telemetryAt(data);
                var at = formatTime(iso);
                render(info, at, alarmFor(info, data, iso, at));
            })
            .catch(function () {
                // Причина мовчить навмисне: читачеві важливо, що стан
                // невідомий, а не яким кодом відповів апстрім.
                render(UNKNOWN, null, alarmFor(UNKNOWN, null, null, null));
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
        for (var i = 0; i < zoomButtons.length; i++) {
            (function (btn) {
                var timer = null;
                L.DomEvent.on(btn, 'click', function () {
                    if (btn.classList.contains('leaflet-disabled')) return;
                    btn.classList.add('is-zoomed');
                    if (timer) clearTimeout(timer);
                    timer = setTimeout(function () {
                        btn.classList.remove('is-zoomed');
                        timer = null;
                    }, 1000);
                });
            })(zoomButtons[i]);
        }
    }

    control('topleft', markersButton).addTo(map);
    control('topleft', issueLink).addTo(map);
    control('topleft', statusTile).addTo(map);

    statusChip();

    // Поки перша відповідь не прийшла, стан невідомий — але мовчки:
    // кричати про аварію, якої ще ніхто не бачив, не можна.
    render(UNKNOWN, null, null);

    poll();
    setInterval(poll, POLL_MS);

    // Вкладку могли лишити відкритою на ніч: щойно на неї повернулись,
    // плашка питає стан, не чекаючи наступного такту.
    document.addEventListener('visibilitychange', function () {
        if (!document.hidden) poll();
    });
})();

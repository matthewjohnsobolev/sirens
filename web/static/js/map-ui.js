/* Навігаційні кнопки й плашка стану на мапі.
   Кожна кнопка — окремий контрол Leaflet, тож стопку тримає сам Leaflet:
   порядок задається порядком addTo, відступи — кутовим контейнером. */
(function () {
    'use strict';

    var map = window.sirensMap;
    if (!map || !window.L) return;

    // Статус-сторінка кешує свій JSON на 60 секунд, тож частіше питати
    // нема сенсу: відповідь усе одно буде та сама.
    var STATUS_URL = 'https://status.sirens.live/status.json';
    var POLL_MS = 60000;

    // indicator зі status.json → стан плашки й слово для скрінрідера.
    // Око читає стан кольором крапки, тож у самому підпису слова немає —
    // але доступна назва без нього залишила б стан невідомим. Слова ті
    // самі, що в STATUS_WORDS на статус-сторінці.
    var STATES = {
        none: { state: 'ok', word: 'Все працює' },
        minor: { state: 'minor', word: 'Часткові збої' },
        major: { state: 'down', word: 'Не працює' },
        critical: { state: 'down', word: 'Не працює' },
        maintenance: { state: 'mnt', word: 'Планові роботи' },
        unknown: { state: 'nodata', word: 'Немає даних' }
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

    var badge = null;

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

    function markersButton() {
        var button = L.DomUtil.create('button', 'map-ctl map-ctl--markers');
        button.type = 'button';
        button.setAttribute('aria-pressed', 'false');
        label(button, 'Прибрати маркери');
        icon(button, 'markers');

        L.DomEvent.on(button, 'click', function () {
            var hidden = map.getContainer().classList.toggle('markers-hidden');
            button.setAttribute('aria-pressed', String(hidden));
            label(button, hidden ? 'Показати маркери' : 'Прибрати маркери');
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

    function statusBadge() {
        var link = L.DomUtil.create('a', 'map-status');
        link.href = 'https://status.sirens.live';
        link.rel = 'noopener';

        var dot = L.DomUtil.create('span', 'map-status-dot', link);
        dot.setAttribute('aria-hidden', 'true');

        badge = { root: link, time: L.DomUtil.create('span', 'map-status-time', link) };
        render(UNKNOWN, null);

        return link;
    }

    function render(info, at) {
        if (!badge) return;

        badge.root.dataset.state = info.state;
        // Без часу писати «оновлено» нема про що: тоді плашка так і каже.
        badge.time.textContent = at ? 'Оновлено о ' + at : 'Немає даних';
        badge.root.setAttribute(
            'aria-label',
            at
                ? 'Стан системи: ' + info.word.toLowerCase() + '. Дані оновлено о ' + at + '.'
                : 'Стан системи: ' + info.word.toLowerCase() + '.'
        );
    }

    // Час пишеться, коли воркер востаннє клав телеметрію в KV. Саме він і
    // застигає, якщо збір даних став, — тоді плашка показує це сама,
    // не питаючи про це моніторинг.
    function updatedAt(data) {
        if (data && data.telemetry && data.telemetry.updated_at) return data.telemetry.updated_at;
        return data && data.page ? data.page.updated_at : null;
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
                render(STATES[indicator] || UNKNOWN, formatTime(updatedAt(data)));
            })
            .catch(function () {
                // Причина мовчить навмисне: читачеві важливо, що стан
                // невідомий, а не яким кодом відповів апстрім.
                render(UNKNOWN, null);
            });
    }

    L.control.zoom({
        position: 'topleft',
        zoomInTitle: 'Наблизити',
        zoomOutTitle: 'Віддалити'
    }).addTo(map);

    control('topleft', markersButton).addTo(map);
    control('topleft', issueLink).addTo(map);
    control('bottomleft', statusBadge).addTo(map);

    poll();
    setInterval(poll, POLL_MS);

    // Вкладку могли лишити відкритою на ніч: щойно на неї повернулись,
    // плашка питає стан, не чекаючи наступного такту.
    document.addEventListener('visibilitychange', function () {
        if (!document.hidden) poll();
    });
})();

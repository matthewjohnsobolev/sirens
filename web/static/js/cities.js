/* Маркери міст.

   Місто на мапі — крапка. Одна й та сама для всіх станів: однаковий
   розмір, однакове біле кільце, — а відрізняє їх рівно колір. Так мапа
   лишається однорідною: у кадрі тридцять вісім однакових знаків, і те, що
   в них змінюється, змінюється в одному-єдиному вимірі.

   Біле кільце тут не прикраса, а те, що відділяє крапку від заливки під
   нею: на жовтій чи червоній області кольорове коло без обідка втратило б
   межу. Тінь під ним тримає крапку помітною і на самій білій підкладці.

   Маркер — це divIcon, а не L.icon, бо разом із крапкою їде назва міста:
   підкладка тепер узагалі без тексту, і всі підписи на мапі — оці. Поле
   маркера дорівнює крапці, тож підпис стоїть на однаковій відстані від її
   краю, а вістря попапа впирається саме в неї. */

const PIN_SIZE = 15;

const PIN_STATES = {
    idle:      { lift: 0 },
    yellow:    { lift: 200 },
    shelling:  { lift: 200 },
    red:       { lift: 400 },
    // Вибухи мапа поки не малює (RENDER_EXPLOSIONS у districts.js).
    explosion: { lift: 400 }
};

function pinState(threats) {
    const dominant = pickDominant(threats);
    return dominant ? threatVariant(dominant, threats[dominant]) : 'idle';
}

function pinIcon(marker, state) {
    return L.divIcon({
        className: 'map-pin map-pin--' + state + ' map-pin--label-' + labelSide(marker),
        html: '<span class="map-pin__dot"></span><span class="map-pin__name">' + marker.name + '</span>',
        iconSize: [PIN_SIZE, PIN_SIZE],
        iconAnchor: [PIN_SIZE / 2, PIN_SIZE / 2],

        // Вістря попапа впирається у верхній край крапки, а не в центр
        // якогось умовного поля: інакше над нею висів би зазор утричі
        // більший за неї саму.
        popupAnchor: [0, -PIN_SIZE / 2]
    });
}

/* Назва стоїть збоку від крапки — і сторону їй вибирає сусідство. Міста
   на мапі стоять нерівно: Буча з Фастовом тиснуться до Києва, а Ковель
   стоїть сам. Якби підпис завжди йшов праворуч, у таких купках назви
   лягали б одна на одну й на чужі крапки.

   Тож для кожного міста дивимося, куди тягне його оточення: сусіди на
   сході — підпис іде ліворуч, на заході — праворуч. Ближчий сусід важить
   більше (внесок ділиться на квадрат відстані), а далі за радіус сусіди
   не рахуються зовсім.

   Сторона рахується раз і назавжди з координат, а не з піксельних
   відстаней поточного кадру: підпис, який перестрибує з боку на бік при
   кожному зумі, дратує сильніше, ніж підпис, який десь колись
   притулився не з того боку. */
const LABEL_REACH = 0.9;

function labelSide(marker) {
    const scale = Math.cos(marker.lat * Math.PI / 180);
    let pull = 0;

    for (const other of DISTRICT_MARKERS) {
        if (other === marker) continue;

        const dx = (other.lng - marker.lng) * scale;
        const dy = other.lat - marker.lat;
        const distance = dx * dx + dy * dy;
        if (!distance || distance > LABEL_REACH * LABEL_REACH) continue;

        pull += dx / distance;
    }

    return pull > 0 ? 'left' : 'right';
}

// Тривога піднімає своє місто над сусідами: інакше червона крапка могла б
// опинитися під зеленою просто тому, що лежить північніше — Leaflet
// складає маркери за широтою.
function applyPinState(entry, state) {
    entry.layer.setIcon(pinIcon(entry.marker, state));
    entry.layer.setZIndexOffset((PIN_STATES[state] || PIN_STATES.idle).lift);
    nameElement(entry);
}

// setIcon перестворює вузол маркера, тож доступну назву доводиться ставити
// щоразу заново: кружок сам по собі не називає нічого.
function nameElement(entry) {
    const element = entry.layer.getElement();
    if (element) element.setAttribute('aria-label', entry.marker.name);
}

function subscribeButtonHtml(channel) {
    return `
        <div class="info-block">
            <a href="tg://resolve?domain=${channel}" class="oblast-button-link">
                <button class="channel-popup-button">
                    <div class="icon-container-marker">
                        <img class="icon-marker" src="static/img/icons/telegram.svg">
                    </div>
                    Підпишіться на канал, щоб отримувати сповіщення про тривогу
                </button>
            </a>
        </div>`;
}

function getMarkerPopupContent(marker, threats) {
    const dominant = pickDominant(threats) || 'idle';
    const winner = threats[dominant] || threats.alert || {};

    return `<div class='channel-popup-name'>${marker.name}</div>`
         + renderPill({
               variant: threatVariant(dominant, winner),
               updatedAt: winner.updated_at,
               source: winner.source
           })
         + subscribeButtonHtml(marker.channel);
}

var customOptions = {'maxWidth': '310', 'width': '310'};

// Маркери будуються один раз, а далі лише міняють стан: перестворювати
// їх на кожній відповіді означало б згортати відкритий попап і губити
// маркер під курсором.
const CITY_MARKERS = [];

// Загрози маркера читаються з поточної відповіді, а не з тієї, що була на
// момент побудови: попап і подія відкриття мають говорити про зараз.
function markerThreats(marker) {
    return getMarkerThreats(SirensThreats.get(), marker);
}

function buildCities(data) {
    DISTRICT_MARKERS.forEach(marker => {
        const state = pinState(getMarkerThreats(data, marker));
        const layer = L.marker([marker.lat, marker.lng], {
            icon: pinIcon(marker, state),
            // Назва потрібна і мишці, і скрінрідеру: підпис поруч
            // з'являється лише від оглядового зума й вище.
            title: marker.name,
            zIndexOffset: (PIN_STATES[state] || PIN_STATES.idle).lift
        });

        layer.bindPopup(() => getMarkerPopupContent(marker, markerThreats(marker)), customOptions);
        layer.on('popupopen', () => {
            if (window.track) window.track('marker_popup_open', {
                marker_type: 'city',
                region_name: marker.name,
                threat_state: pinState(markerThreats(marker))
            });
        });

        layer.addTo(map);

        const entry = { marker: marker, layer: layer, state: state };
        nameElement(entry);
        CITY_MARKERS.push(entry);
    });
}

function paintCities(data) {
    if (!CITY_MARKERS.length) {
        buildCities(data);
        return;
    }

    for (const entry of CITY_MARKERS) {
        const state = pinState(getMarkerThreats(data, entry.marker));

        // Відповідь приходить кожні кілька секунд, а стан маркера за нею
        // змінюється рідко: чіпаємо лише справжню зміну.
        if (entry.state === state) continue;

        entry.state = state;
        applyPinState(entry, state);
    }
}

SirensThreats.onPaint(paintCities);

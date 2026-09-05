function setMarkerStyle(dominant) {
    if (dominant === 'explosion') {
        return (typeof redChannelIcon !== 'undefined' && redChannelIcon) ? redChannelIcon : L.icon({
            iconUrl: 'static/img/icons/channel-red.svg',
            iconSize: [27.5, 27.5],
            popupAnchor: [0, -14]
        });
    }
    if (dominant === 'alert') {
        return (typeof orangeChannelIcon !== 'undefined' && orangeChannelIcon) ? orangeChannelIcon : L.icon({
            iconUrl: 'static/img/icons/air-raid-alert-marker.svg',
            iconSize: [27.5, 27.5],
            popupAnchor: [0, -14]
        });
    }
    if (dominant === 'shelling') {
        return (typeof yellowChannelIcon !== 'undefined' && yellowChannelIcon) ? yellowChannelIcon : L.icon({
            iconUrl: 'static/img/icons/channel-yellow.svg',
            iconSize: [27.5, 27.5],
            popupAnchor: [0, -14]
        });
    }
    return (typeof greenChannelIcon !== 'undefined' && greenChannelIcon) ? greenChannelIcon : L.icon({
        iconUrl: 'static/img/icons/air-raid-alert-cancelled-marker.svg',
        iconSize: [27.5, 27.5],
        popupAnchor: [0, -14]
    });
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
         + renderPill({ variant: dominant, updatedAt: winner.updated_at, source: winner.source })
         + subscribeButtonHtml(marker.channel);
}

var customOptions = {'maxWidth': '310', 'width': '310'};

// Маркери будуються один раз, а далі лише міняють іконку: перестворювати
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
        const state = pickDominant(getMarkerThreats(data, marker)) || 'idle';
        const layer = L.marker([marker.lat, marker.lng], { icon: setMarkerStyle(state) });

        layer.bindPopup(() => getMarkerPopupContent(marker, markerThreats(marker)), customOptions);
        layer.on('popupopen', () => {
            if (window.track) window.track('marker_popup_open', {
                marker_type: 'city',
                region_name: marker.name,
                threat_state: pickDominant(markerThreats(marker)) || 'idle'
            });
        });

        layer.addTo(map);
        CITY_MARKERS.push({ marker: marker, layer: layer, state: state });
    });
}

function paintCities(data) {
    if (!CITY_MARKERS.length) {
        buildCities(data);
        return;
    }

    for (const entry of CITY_MARKERS) {
        const state = pickDominant(getMarkerThreats(data, entry.marker)) || 'idle';

        // Відповідь приходить кожні кілька секунд, а стан маркера за нею
        // змінюється рідко. setIcon перестворює <img>, тож ставити ту саму
        // іконку означало б регулярно висмикувати з-під курсора те, на що
        // читач саме наводиться.
        if (entry.state === state) continue;

        entry.state = state;
        entry.layer.setIcon(setMarkerStyle(state));
    }
}

SirensThreats.onPaint(paintCities);
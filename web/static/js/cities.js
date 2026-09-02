function setMarkerStyle(dominant) {
    if (dominant === 'unknown') {
        return (typeof grayChannelIcon !== 'undefined' && grayChannelIcon) ? grayChannelIcon : L.icon({
            iconUrl: 'static/img/icons/channel-gray.svg',
            iconSize: [27.5, 27.5],
            popupAnchor: [0, -14]
        });
    }
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

function getMarkerPopupContent(marker, threats, known = true) {
    const dominant = known ? (pickDominant(threats) || 'idle') : 'unknown';
    const winner = threats[dominant] || threats.alert || {};
    const pill = known
        ? { variant: dominant, updatedAt: winner.updated_at, source: winner.source }
        : { variant: 'unknown', showTime: false };

    return `<div class='channel-popup-name'>${marker.name}</div>`
         + renderPill(pill)
         + subscribeButtonHtml(marker.channel);
}

var customOptions = {'maxWidth': '310', 'width': '310'};

loadThreats()
    .then(data => {
        const known = stateIsKnown(data);

        DISTRICT_MARKERS.forEach(marker => {
            const threats = getMarkerThreats(data, marker);
            const dominant = known ? pickDominant(threats) : 'unknown';
            const icon = setMarkerStyle(dominant);
            const m = L.marker([marker.lat, marker.lng], { icon: icon });

            m.bindPopup(() => getMarkerPopupContent(marker, threats, known), customOptions);
            m.addTo(map);
        });
    })
    .catch(error => {
        console.error(error);
    });
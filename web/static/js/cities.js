

const PIN_SIZE = 15;

const PIN_STATES = {
    idle:      { lift: 0 },
    yellow:    { lift: 200 },
    shelling:  { lift: 200 },
    red:       { lift: 400 },
    
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

        
        
        
        popupAnchor: [0, -PIN_SIZE / 2]
    });
}


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




function applyPinState(entry, state) {
    entry.layer.setIcon(pinIcon(entry.marker, state));
    entry.layer.setZIndexOffset((PIN_STATES[state] || PIN_STATES.idle).lift);
    nameElement(entry);
}



function nameElement(entry) {
    const element = entry.layer.getElement();
    if (element) {
        element.setAttribute('aria-label', entry.marker.name);
        element.removeAttribute('title');
    }
}

function subscribeButtonHtml(channel) {
    if (!channel) return '';
    return `
        <div class="info-block">
            <a href="tg://resolve?domain=${channel}" class="oblast-button-link">
                <button class="channel-popup-button">
                    <div class="icon-container-marker">
                        <img class="icon-marker" src="static/img/icons/telegram.svg" alt="" aria-hidden="true">
                    </div>
                    Підписатися на сповіщення
                </button>
            </a>
        </div>`;
}

function getMarkerPopupContent(marker, threats) {
    const dominant = pickDominant(threats) || 'idle';
    const winner = threats[dominant] || threats.alert || {};
    const channelHtml = subscribeButtonHtml(marker.channel);

    return `<div class='channel-popup-name'>${marker.name}</div>`
         + renderPill({
               variant: threatVariant(dominant, winner),
               updatedAt: winner.updated_at,
               source: winner.source
           })
         + (channelHtml ? '\n' + channelHtml : '');
}

var customOptions = {'maxWidth': '310', 'width': '310'};




const CITY_MARKERS = [];



function markerThreats(marker) {
    return getMarkerThreats(SirensThreats.get(), marker);
}

function buildCities(data) {
    DISTRICT_MARKERS.forEach(marker => {
        const state = pinState(getMarkerThreats(data, marker));
        const layer = L.marker([marker.lat, marker.lng], {
            icon: pinIcon(marker, state),
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

        
        
        if (entry.state === state) continue;

        entry.state = state;
        applyPinState(entry, state);
    }
}

SirensThreats.onPaint(paintCities);

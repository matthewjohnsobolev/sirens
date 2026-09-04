const OBLAST_FILL_OPACITY = {
    idle:  0.18,
    alert: 0.2
};

const HATCH = { minStripe: 3, maxStripe: 7 };

function hatchStripe(zoom) {
    return Math.min(HATCH.maxStripe, Math.max(HATCH.minStripe, Math.round(zoom) - 3));
}

function resizeHatch(pattern, zoom) {
    const stripe = hatchStripe(zoom);
    const size = stripe * 2;
    if (pattern.getAttribute('width') === String(size)) return;

    pattern.setAttribute('width', size);
    pattern.setAttribute('height', size);
    const [bar, gap] = pattern.children;
    bar.setAttribute('width', stripe);
    bar.setAttribute('height', size);
    gap.setAttribute('x', stripe);
    gap.setAttribute('width', stripe);
    gap.setAttribute('height', size);
}

function ensureHatchDefs(map) {
    const svg = map.getPane('overlayPane').querySelector('svg');
    if (!svg) return;

    let pattern = svg.querySelector('#alert-hatch');
    if (!pattern) {
        const defs = L.SVG.create('defs');
        defs.innerHTML = `
      <pattern id="alert-hatch" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <rect x="0" fill="${ALERT_COLORS.ALERT}"/>
        <rect fill="${ALERT_COLORS.IDLE}" fill-opacity="${OBLAST_FILL_OPACITY.idle}"/>
      </pattern>`;
        svg.insertBefore(defs, svg.firstChild);
        pattern = svg.querySelector('#alert-hatch');
        map.on('zoomend', () => resizeHatch(pattern, map.getZoom()));
    }
    resizeHatch(pattern, map.getZoom());
}

const OBLAST_STYLES = {
    idle:      { color: ALERT_COLORS.IDLE,      weight: 2, fillColor: ALERT_COLORS.IDLE,      fillOpacity: OBLAST_FILL_OPACITY.idle },
    partial:   { color: ALERT_COLORS.ALERT,     weight: 2 },
    full:      { color: ALERT_COLORS.ALERT,     weight: 2, fillColor: ALERT_COLORS.ALERT,     fillOpacity: OBLAST_FILL_OPACITY.alert },
    explosion: { color: ALERT_COLORS.EXPLOSION, weight: 2, fillColor: ALERT_COLORS.EXPLOSION, fillOpacity: 0.55 }
};

function oblastState(data) {
    const dominant = pickDominant({
        alert: data.alert, explosion: data.explosion,
    });
    return dominant === 'alert' ? (data.alert ? data.alert.coverage : 'idle')
         : dominant || 'idle';
}

function setOblastStyle(layer, data) {
    const state = oblastState(data);

    layer.setStyle(OBLAST_STYLES[state] || OBLAST_STYLES.idle);
    if (layer._path) {
        L.DomUtil[state === 'partial' ? 'addClass' : 'removeClass'](layer._path, 'oblast-partial');
    }
    layer[state === 'idle' ? 'bringToBack' : 'bringToFront']();
}

function getOblastPopupContent(oblastData) {
    const alert = (oblastData && oblastData.alert) || {};
    const tracked = alert.tracked_districts || [];

    if (!tracked.length) {
        return `
      <div class="container">
          ${renderPill({ variant: 'unknown', showTime: false })}
      </div>`;
    }

    let rows = '';
    for (const key of tracked) {
        const district = (oblastData.districts && oblastData.districts[key]) || {};
        rows += `
              <div class="popup-city">
                  <div class="popup-city-name">${district.name || key}</div>
                  ${renderPill(districtPillState(oblastData, key))}
              </div>`;
    }

    return `
      <div class="container">
          <div class="scrollable-content">${rows}
          </div>
      </div>`;
}

// Місто-регіон — полігон, що збігається з єдиним своїм районом (нині це Київ).
// Розповідати про нього двічі й по-різному нема про що, тож картку полігона
// збираємо тим самим кодом, що й картку маркера.
const CITY_REGIONS = {};
for (const marker of DISTRICT_MARKERS) {
    if (marker.oblast === marker.district) CITY_REGIONS[marker.oblast] = marker;
}

var customOptions = {'maxWidth': '310', 'width': '310'};

fetch('/api')
    .then(response => response.json())
    .then(apiData => {
        fetch('https://geo.sirens.live/ukraine.geojson')
            .then(res => res.json())
            .then(geoData => {
                const geoLayer = L.geoJSON(geoData, {
                    onEachFeature: function(feature, layer) {
                        const regionId = feature.properties.id;
                        const data = apiData[regionId];
                        if (!data) return;
                        
                        const nameMap = {
                            'cherkasy_oblast': 'Черкаська область', 'chernihiv_oblast': 'Чернігівська область',
                            'chernivtsi_oblast': 'Чернівецька область', 'crimea': 'Крим',
                            'dnipropetrovsk_oblast': 'Дніпропетровська область', 'donetsk_oblast': 'Донецька область',
                            'ivanofrankivsk_oblast': 'Івано-Франківська область', 'kharkiv_oblast': 'Харківська область',
                            'kherson_oblast': 'Херсонська область', 'khmelnytskyi_oblast': 'Хмельницька область',
                            'kirovohrad_oblast': 'Кіровоградська область', 'kyiv': 'Київ',
                            'kyiv_oblast': 'Київська область', 'luhansk_oblast': 'Луганська область',
                            'lviv_oblast': 'Львівська область', 'mykolaiv_oblast': 'Миколаївська область',
                            'odesa_oblast': 'Одеська область', 'poltava_oblast': 'Полтавська область',
                            'rivne_oblast': 'Рівненська область', 'sevastopol': 'Севастополь',
                            'sumy_oblast': 'Сумська область', 'ternopil_oblast': 'Тернопільска область',
                            'vinnytsia_oblast': 'Вінницька область', 'volyn_oblast': 'Волинська область',
                            'zakarpattia_oblast': 'Закарпатська область', 'zaporizhzhia_oblast': 'Запорізька область',
                            'zhytomyr_oblast': 'Житомирська область'
                        };
                        const name = nameMap[regionId] || regionId;
                        const cityMarker = CITY_REGIONS[regionId];

                        layer.bindPopup(
                            () => cityMarker
                                ? getMarkerPopupContent(cityMarker, getMarkerThreats(apiData, cityMarker))
                                : '<div class="oblast-name">' + name + '</div>' + getOblastPopupContent(data),
                            customOptions
                        );
                        layer.on('popupopen', () => {
                            if (window.track) window.track('region_popup_open', {
                                region_name: name,
                                threat_state: oblastState(data)
                            });
                        });
                    }
                }).addTo(map);

                ensureHatchDefs(map);

                geoLayer.eachLayer(function(layer) {
                    const data = apiData[layer.feature.properties.id];
                    if (!data) return;
                    setOblastStyle(layer, data);
                });
            });
    })
    .catch(error => { console.error('Error fetching data:', error); });

  

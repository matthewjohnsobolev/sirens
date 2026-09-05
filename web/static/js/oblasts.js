// Підкладка монохромна, тож стани мусять відрізнятися не лише відтінком, а
// й вагою заливки: спокій — найсвітліший, тривога помітно темніша, вибухи —
// найтемніші. Помаранчевий і сірий однакової світлоти на сонці та в очах
// того, хто їх не розрізняє, — це одна пляма; сходинка яскравості лишається
// зрозумілою й тоді, коли колір не читається.
const OBLAST_FILL_OPACITY = {
    idle:      0.08,
    alert:     0.22,
    explosion: 0.32
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
        // Помаранчева смужка має колір і прозорість тривожного регіону,
        // а проміжна смужка — колір і прозорість спокійного регіону (відбою).
        const defs = L.SVG.create('defs');
        defs.innerHTML = `
      <pattern id="alert-hatch" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <rect x="0" fill="${ALERT_COLORS.ALERT}" fill-opacity="${OBLAST_FILL_OPACITY.alert}"/>
        <rect fill="${ALERT_COLORS.IDLE}" fill-opacity="${OBLAST_FILL_OPACITY.idle}"/>
      </pattern>`;
        svg.insertBefore(defs, svg.firstChild);
        pattern = svg.querySelector('#alert-hatch');
        map.on('zoomend', () => resizeHatch(pattern, map.getZoom()));
    }
    resizeHatch(pattern, map.getZoom());
}

const OBLAST_STYLES = {
    idle:      { color: ALERT_COLORS.IDLE,      weight: 1.5, fillColor: ALERT_COLORS.IDLE,      fillOpacity: OBLAST_FILL_OPACITY.idle },
    partial:   { color: ALERT_COLORS.ALERT,     weight: 2.5 },
    full:      { color: ALERT_COLORS.ALERT,     weight: 2.5, fillColor: ALERT_COLORS.ALERT,     fillOpacity: OBLAST_FILL_OPACITY.alert },
    explosion: { color: ALERT_COLORS.EXPLOSION, weight: 2.5, fillColor: ALERT_COLORS.EXPLOSION, fillOpacity: OBLAST_FILL_OPACITY.explosion }
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

    // Відповідь приходить кожні кілька секунд, а стан області за нею
    // змінюється рідко. Перефарбовуємо лише зміну: bringToFront пересуває
    // <path> у SVG, і робити це щотакту означало б перебирати всю мапу
    // заради нічого.
    if (layer.sirensState === state) return;
    layer.sirensState = state;

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

const OBLAST_NAMES = {
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

let oblastLayer = null;

// Дані області читаються з поточної відповіді, а не з тієї, що була на
// момент побудови шару: попап і подія відкриття мають говорити про зараз.
function oblastData(regionId) {
    const data = SirensThreats.get();
    return data ? data[regionId] : null;
}

function buildOblasts(geoData) {
    oblastLayer = L.geoJSON(geoData, {
        onEachFeature: function(feature, layer) {
            const regionId = feature.properties.id;
            if (!oblastData(regionId)) return;

            const name = OBLAST_NAMES[regionId] || regionId;
            const cityMarker = CITY_REGIONS[regionId];

            layer.bindPopup(
                () => {
                    const data = oblastData(regionId);
                    if (!data) return '';
                    return cityMarker
                        ? getMarkerPopupContent(cityMarker, getMarkerThreats(SirensThreats.get(), cityMarker))
                        : '<div class="oblast-name">' + name + '</div>' + getOblastPopupContent(data);
                },
                customOptions
            );
            layer.on('popupopen', () => {
                const data = oblastData(regionId);
                if (window.track) window.track('region_popup_open', {
                    region_name: name,
                    threat_state: data ? oblastState(data) : 'idle'
                });
            });
        }
    }).addTo(map);

    ensureHatchDefs(map);
}

// Шар будується один раз, а далі лише перефарбовується: перестворювати
// його на кожній відповіді означало б згортати відкритий попап і на мить
// лишати мапу без областей.
function paintOblasts(data) {
    if (!oblastLayer) return;

    oblastLayer.eachLayer(function(layer) {
        const regionData = data[layer.feature.properties.id];
        if (regionData) setOblastStyle(layer, regionData);
    });
}

// Межі приходять з окремого джерела й не змінюються, тож качаються раз.
// Малювальник реєструється лише коли вони є: без меж фарбувати нічого.
fetch('https://geo.sirens.live/ukraine.geojson')
    .then(res => res.json())
    .then(geoData => {
        SirensThreats.onPaint(function(data) {
            if (!oblastLayer) buildOblasts(geoData);
            paintOblasts(data);
        });
    })
    .catch(error => { console.error('Error fetching data:', error); });

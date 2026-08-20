/**
 * Oblast boundary styles and popup configurations for Sirens map.
 */

function ensureHatchDefs(map) {
    const svg = map.getPane('overlayPane').querySelector('svg');
    if (!svg || svg.querySelector('#alert-hatch')) return;
    const defs = L.SVG.create('defs');   // createElementNS in SVG namespace
    defs.innerHTML = `
      <pattern id="alert-hatch" patternUnits="userSpaceOnUse"
               width="10" height="10" patternTransform="rotate(45)">
        <rect width="10" height="10" fill="${ALERT_COLORS.IDLE}"  fill-opacity="0.3"/>
        <rect width="5"  height="10" fill="${ALERT_COLORS.ALERT}" fill-opacity="0.75"/>
      </pattern>`;
    svg.insertBefore(defs, svg.firstChild);
}

const OBLAST_STYLES = {
    idle:      { color: ALERT_COLORS.IDLE,      weight: 2, fillColor: ALERT_COLORS.IDLE,      fillOpacity: 0.18 },
    partial:   { color: ALERT_COLORS.ALERT,     weight: 2 },
    full:      { color: ALERT_COLORS.ALERT,     weight: 2, fillColor: ALERT_COLORS.ALERT,     fillOpacity: 0.55 },
    explosion: { color: ALERT_COLORS.EXPLOSION, weight: 2, fillColor: ALERT_COLORS.EXPLOSION, fillOpacity: 0.55 }
};

function setOblastStyle(layer, data) {
    const dominant = pickDominant({
        alert: data.alert, explosion: data.explosion,
    });
    const state = dominant === 'alert' ? (data.alert ? data.alert.coverage : 'idle')   // 'partial' | 'full'
                : dominant || 'idle';                          // 'explosion' | 'idle'

    layer.setStyle(OBLAST_STYLES[state] || OBLAST_STYLES.idle);
    if (layer._path) {
        L.DomUtil[state === 'partial' ? 'addClass' : 'removeClass'](layer._path, 'oblast-partial');
    }
    layer[state === 'idle' ? 'bringToBack' : 'bringToFront']();
}

const DISTRICTS_TOGGLE_LABEL = { expanded: 'Згорнути', collapsed: 'Показати всі' };

// Базове положення - вниз (згорнуто); розгорнутий стан повертає його вгору через CSS.
const CHEVRON_SVG = `
    <svg class="districts-chevron" width="10" height="6" viewBox="0 0 10 6" aria-hidden="true">
        <path d="M1 1l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.5"
              stroke-linecap="round" stroke-linejoin="round"/>
    </svg>`;

// Контент попапа - функція, тож Leaflet перебудовує його на кожному відкритті.
// Тримаємо стан акордеона зовні, інакше він скидався б щоразу.
// За замовчуванням згорнутий: спершу зведення по області, деталі - за запитом.
let districtsExpanded = false;

function getOblastPopupContent(oblastData) {
    const summary = oblastSummary(oblastData);
    const alert = (oblastData && oblastData.alert) || {};
    const tracked = alert.tracked_districts || [];

    let popupContent = `
      <div class="container">
          <div class="scrollable-content scrollable-content--oblast">`;

    popupContent += renderPill({ ...summary, source: alert.source, showTime: false });

    if (tracked.length) {
        popupContent += `
            <button type="button" class="districts-toggle" aria-expanded="${districtsExpanded}">
                <span class="districts-toggle-text">Міста</span>
                <span class="districts-toggle-action">
                    <span class="districts-toggle-label">${districtsExpanded
                        ? DISTRICTS_TOGGLE_LABEL.expanded
                        : DISTRICTS_TOGGLE_LABEL.collapsed}</span>
                    ${CHEVRON_SVG}
                </span>
            </button>
            <div class="districts-list"${districtsExpanded ? '' : ' hidden'}>`;

        for (const key of tracked) {
            const marker = DISTRICT_MARKERS.find(m => m.district === key);
            // Назва - фіксована ліва колонка, компактна таблетка забирає решту рядка.
            popupContent += `
                <div class="district-row">
                    <div class="district-name">${marker ? marker.name : key}</div>
                    ${renderPill({ ...districtPillState(oblastData, key), compact: true })}
                </div>`;
        }

        popupContent += `
            </div>`;
    }

    popupContent += `
          </div>
      </div>`;
    return popupContent;
}

// Акордеон живе всередині попапа, який Leaflet перебудовує на кожному відкритті,
// тож слухача вішаємо на свіжий DOM у popupopen - накопичення обробників немає.
function bindDistrictsAccordion(map) {
    map.on('popupopen', function (e) {
        const root = e.popup.getElement();
        const toggle = root && root.querySelector('.districts-toggle');
        const list = root && root.querySelector('.districts-list');
        if (!toggle || !list) return;

        toggle.addEventListener('click', function () {
            districtsExpanded = !districtsExpanded;
            toggle.setAttribute('aria-expanded', String(districtsExpanded));
            list.hidden = !districtsExpanded;

            const label = toggle.querySelector('.districts-toggle-label');
            if (label) {
                label.textContent = districtsExpanded
                    ? DISTRICTS_TOGGLE_LABEL.expanded
                    : DISTRICTS_TOGGLE_LABEL.collapsed;
            }
            // popup.update() тут не можна: він перевикликає функцію контенту
            // й перезаписує innerHTML, миттєво повертаючи список назад.
            // Контейнер попапа має auto-висоту, тож він стискається сам.
        });
    });
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
                        
                        // Функція, а не рядок: тривалість рахується у мить відкриття попапа.
                        layer.bindPopup(
                            () => '<div class="oblast-name">' + name + '</div>' + getOblastPopupContent(data),
                            customOptions
                        );
                    }
                }).addTo(map);

                ensureHatchDefs(map);
                bindDistrictsAccordion(map);

                geoLayer.eachLayer(function(layer) {
                    const data = apiData[layer.feature.properties.id];
                    if (!data) return;
                    setOblastStyle(layer, data);
                });
            });
    })
    .catch(error => { console.error('Error fetching data:', error); });

  

/**
 * Oblast boundary styles and popup configurations for Sirens map.
 */

// Заливки полігонів: початкові значення Leaflet, які були до появи штриховки.
const OBLAST_FILL_OPACITY = {
    idle:  0.18,
    alert: 0.2
};

// Штриховка часткової тривоги: смуга - той самий помаранчевий, що й обведення,
// на повну насиченість; проміжок - сірий спокійної області. Смуги не
// перекриваються, тож кожен колір лишається чистим.
const HATCH = { size: 14, stripe: 7 };

function ensureHatchDefs(map) {
    const svg = map.getPane('overlayPane').querySelector('svg');
    if (!svg || svg.querySelector('#alert-hatch')) return;
    const defs = L.SVG.create('defs');   // createElementNS in SVG namespace
    defs.innerHTML = `
      <pattern id="alert-hatch" patternUnits="userSpaceOnUse"
               width="${HATCH.size}" height="${HATCH.size}" patternTransform="rotate(45)">
        <rect x="0" width="${HATCH.stripe}" height="${HATCH.size}" fill="${ALERT_COLORS.ALERT}"/>
        <rect x="${HATCH.stripe}" width="${HATCH.size - HATCH.stripe}" height="${HATCH.size}"
              fill="${ALERT_COLORS.IDLE}" fill-opacity="${OBLAST_FILL_OPACITY.idle}"/>
      </pattern>`;
    svg.insertBefore(defs, svg.firstChild);
}

const OBLAST_STYLES = {
    idle:      { color: ALERT_COLORS.IDLE,      weight: 2, fillColor: ALERT_COLORS.IDLE,      fillOpacity: OBLAST_FILL_OPACITY.idle },
    partial:   { color: ALERT_COLORS.ALERT,     weight: 2 },
    full:      { color: ALERT_COLORS.ALERT,     weight: 2, fillColor: ALERT_COLORS.ALERT,     fillOpacity: OBLAST_FILL_OPACITY.alert },
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

// Попап області - той самий список стандартних таблеток, що й у попапах маркерів:
// над кожною таблеткою стоїть моношрифтом місто, якого вона стосується.
function getOblastPopupContent(oblastData) {
    const alert = (oblastData && oblastData.alert) || {};
    const tracked = alert.tracked_districts || [];

    // Області без жодного відстежуваного міста (Крим, Донеччина, Луганщина,
    // Севастополь): показуємо єдину таблетку "немає даних" замість порожнього списку.
    if (!tracked.length) {
        return `
      <div class="container">
          ${renderPill({ variant: 'unknown', text: 'Немає даних по районах', showTime: false })}
      </div>`;
    }

    let rows = '';
    for (const key of tracked) {
        const marker = DISTRICT_MARKERS.find(m => m.district === key);
        rows += `
              <div class="popup-city">
                  <div class="popup-city-name">${marker ? marker.name : key}</div>
                  ${renderPill(districtPillState(oblastData, key))}
              </div>`;
    }

    return `
      <div class="container">
          <div class="scrollable-content">${rows}
          </div>
      </div>`;
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

                geoLayer.eachLayer(function(layer) {
                    const data = apiData[layer.feature.properties.id];
                    if (!data) return;
                    setOblastStyle(layer, data);
                });
            });
    })
    .catch(error => { console.error('Error fetching data:', error); });

  

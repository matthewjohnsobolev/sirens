/* Області на мапі: полігони, штрихування й заслінка навколо країни.

   Увесь колір станів лежить у map-layers.css і вмикається класом на
   <path>. Leaflet кладе стиль презентаційними атрибутами, а властивість
   CSS сильніша за атрибут — тож стан області міняється одним classList,
   без setStyle на кожній відповіді, і палітра мапи лишається в стилях
   поряд із рештою дизайн-системи. Тут — лише геометрія й логіка стану. */

/* Полігон області говорить рівно про одне — про повітряну тривогу. Ні
   загроза артобстрілу, ні вибухи його не фарбують: перше оголошують
   окремим районам (нині це Нікополь), друге чують у точці, а не в
   області. Обидва живуть маркерами міст — і саме тому полігон лишається
   однозначним: колір на ньому означає тривогу й нічого крім неї. */
function oblastState(data) {
    // Вибухи мапа поки не малює (RENDER_EXPLOSIONS у districts.js). Гілка
    // лишається, щоб повернути їх можна було прапорцем, а не розслідуванням.
    if (RENDER_EXPLOSIONS && data.explosion && data.explosion.status) return 'explosion';

    const alert = data.alert;
    const coverage = alert && alert.coverage;
    if (coverage !== 'full' && coverage !== 'partial') return 'idle';

    // Два рівні поруч — уже саме по собі складна картина, і додавати до
    // неї третій шар («а ще не в усіх районах») нема сенсу: область, де є
    // і відбій, і жовтий, і червоний, виглядає так само, як область, де є
    // просто жовтий і червоний. Покриття залишається питанням одного
    // рівня: воно відповідає, чи скрізь оголошено те саме.
    const levels = activeLevels(data);
    if (levels.size > 1) return 'mixed';

    const level = levels.values().next().value || alertLevel(alert);
    return coverage === 'partial' ? level + '-partial' : level;
}

/* Рівень області — не одне число. Тривогу оголошують районам, і в сусідніх
   районах однієї області цілком буває різний рівень: у прикордонному
   червоний, у дальньому жовтий. Тож збираємо рівні всіх районів під
   тривогою: один — область говорить ним, два — область говорить обома. */
function activeLevels(data) {
    const alert = data.alert || {};
    const active = alert.active_districts || [];
    const districts = data.districts || {};
    const levels = new Set();

    for (const key of active) {
        const district = districts[key];
        if (district && district.alert && district.alert.status) {
            levels.add(alertLevel(district.alert));
        }
    }

    // Район може бути в active_districts і без власного запису — тоді
    // рівень бере на себе область: іншого джерела в нас усе одно немає.
    if (!levels.size && active.length) levels.add(alertLevel(alert));

    return levels;
}

/* ── Штрихування ────────────────────────────────────────────────────── */

/* Усе штрихування на мапі — одна й та сама сітка: похилі смуги однакової
   ширини, що чергуються попарно. Різниться в них рівно одне — що саме
   стоїть у другій смузі:

     жовтий  + порожньо  тривога жовтого рівня не в усіх районах
     червоний + порожньо  те саме для червоного
     жовтий  + червоний   в області оголошено обидва рівні

   Через це три випадки читаються як три значення однієї величини, а не як
   три різні візерунки. Раніше комбінований патерн мав власну клітинку,
   власну ширину смуги й власну щільність — і поруч із неповною тривогою
   виглядав так, ніби прийшов з іншої мапи.

   Колір смуги — той самий колір і та сама прозорість, що в суцільної
   заливки того ж рівня (MAP_TINTS, зібрані з токенів). Тобто жовта смуга
   дорівнює жовтій області, а не «якомусь іншому жовтому»; область з обома
   рівнями важить рівно стільки ж, скільки суцільна, а неповна — удвічі
   менше, бо половина її площі порожня. Це не збіг, а сама суть шкали.

   Смуги не налазять одна на одну навмисно: прозорий жовтий поверх
   прозорого червоного дає буру кашу, у якій жодного з двох рівнів не
   впізнати. Кожна смуга лягає на чисту підкладку й лишається собою.

   Крок сітки сталий, не прив'язаний до зума: смужка живе в пікселях
   екрана, і що ближче мапа, то менше областей у кадрі — розтягувати там
   смужку означало б робити текстуру помітнішою саме тоді, коли її роль
   найменша. */
const HATCH = { band: 6 };

const HATCH_PATTERNS = {
    'yellow-partial': ['yellow', null],
    'red-partial': ['red', null],
    'mixed': ['yellow', 'red']
};

function ensureHatchDefs(map) {
    const svg = map.getPane('overlayPane').querySelector('svg');
    if (!svg || svg.querySelector('#map-hatch-mixed')) return;

    const cell = HATCH.band * 2;
    const defs = L.SVG.create('defs');

    defs.innerHTML = Object.keys(HATCH_PATTERNS).map(name => {
        const bars = HATCH_PATTERNS[name].map((hue, index) => {
            if (!hue) return '';
            const tint = MAP_TINTS[hue];
            return '<rect x="' + index * HATCH.band + '" width="' + HATCH.band +
                   '" height="' + cell + '" fill="' + tint.color +
                   '" fill-opacity="' + tint.alpha + '"/>';
        }).join('');

        return '<pattern id="map-hatch-' + name + '" patternUnits="userSpaceOnUse"' +
               ' width="' + cell + '" height="' + cell + '"' +
               ' patternTransform="rotate(45)">' + bars + '</pattern>';
    }).join('');

    svg.insertBefore(defs, svg.firstChild);
}

/* ── Смуги зума ─────────────────────────────────────────────────────── */

/* Мапа читається по-різному здалеку й зблизька, тож і розповідає про себе
   по-різному. Смуга — одне слово на контейнері, а все, що з нього
   випливає, лишається в CSS:

   wide (z ≤ 5)  країна завширшки з долоню: тонкі межі, самі крапки;
   far  (z 6)    видно всю країну — крапки без назв: тридцять вісім
                 підписів тут злиплися б в одну смугу;
   mid  (z 7-8)  у кадр влізла область — з'являються назви: питання
                 змінилося з «де тривога?» на «яке саме це місто?»;
   near (z ≥ 9)  межі товщають, бо в кадрі їх лишилося одна-дві.

   Самі крапки видно завжди й у будь-якому стані: спокійне місто — це не
   порожнє місце, у нього клікають, щоб підписатися на канал. Тихішим за
   тривожні його робить колір, а не зникнення. */
const ZOOM_BANDS = [
    { upTo: 5, name: 'wide' },
    { upTo: 6, name: 'far' },
    { upTo: 8, name: 'mid' },
    { upTo: Infinity, name: 'near' }
];

function applyZoomBand(map) {
    const zoom = map.getZoom();
    const band = ZOOM_BANDS.find(entry => zoom <= entry.upTo);
    map.getContainer().dataset.zoom = band.name;
}

/* ── Фарбування ─────────────────────────────────────────────────────── */

/* Сусідні області ділять одну межу, а малюються двома лініями, що лягають
   одна на одну. Хто з них лишиться зверху — вирішує порядок у SVG, і
   пускати це на самоплив не можна: тоді те, чия межа видима, залежить від
   того, в якому порядку прийшли оновлення.

   Порядок тут змістовний, а не технічний: спокійна сіра межа найнижча,
   жовта перекриває сіру, червона перекриває жовту. Навпаки не буває —
   лінія на межі двох областей має називати гіршу з них, інакше поруч із
   червоною областю було б видно спокійний контур. */
const STROKE_ORDER = {
    idle: 0,
    yellow: 1,
    'yellow-partial': 1,
    red: 2,
    'red-partial': 2,
    mixed: 2,
    explosion: 3
};

function setOblastStyle(layer, data) {
    const state = oblastState(data);

    // Відповідь приходить кожні кілька секунд, а стан області за нею
    // змінюється рідко. Перефарбовуємо лише зміну: перекладати <path> у
    // SVG щотакту означало б перебирати всю мапу заради нічого.
    if (layer.sirensState === state) return false;

    const path = layer._path;
    if (path) {
        if (layer.sirensState) path.classList.remove('map-oblast--' + layer.sirensState);
        path.classList.add('map-oblast--' + state);
    }

    layer.sirensState = state;
    return true;
}

// Сортування стабільне, тож області з однаковим станом лишаються в тому
// порядку, у якому були: перекладаємо тільки те, що справді має поїхати.
function orderOblastStrokes() {
    const layers = [];
    oblastLayer.eachLayer(layer => { if (layer._path) layers.push(layer); });
    if (!layers.length) return;

    layers.sort((a, b) =>
        (STROKE_ORDER[a.sirensState] || 0) - (STROKE_ORDER[b.sirensState] || 0));

    const parent = layers[0]._path.parentNode;
    for (const layer of layers) parent.appendChild(layer._path);
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

var customOptions = { minWidth: 310, maxWidth: 310 };

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
        // Колір і товщина приходять із CSS, а звідси — лише дозвіл малювати
        // обидва: без stroke і fill Leaflet поставив би fill="none", і жодне
        // правило стилів уже нічого не залило б.
        style: function () {
            return { className: 'map-oblast', stroke: true, fill: true };
        },
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
    applyZoomBand(map);
    map.on('zoomend', () => applyZoomBand(map));
}

// Шар будується один раз, а далі лише перефарбовується: перестворювати
// його на кожній відповіді означало б згортати відкритий попап і на мить
// лишати мапу без областей.
function paintOblasts(data) {
    if (!oblastLayer) return;

    let changed = false;
    oblastLayer.eachLayer(function(layer) {
        const regionData = data[layer.feature.properties.id];
        if (regionData && setOblastStyle(layer, regionData)) changed = true;
    });

    // Перекладати шар має сенс лише тоді, коли щось справді змінило стан.
    if (changed) orderOblastStrokes();
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

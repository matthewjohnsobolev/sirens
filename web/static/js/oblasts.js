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
    if (!data) return 'idle';

    const districts = data.districts || data;
    const districtKeys = Object.keys(districts).filter(k => k !== 'alert' && k !== 'shelling' && k !== 'explosion' && k !== 'title');
    if (!districtKeys.length) return 'idle';

    const activeKeys = districtKeys.filter(key => {
        const d = districts[key];
        return d && d.alert && d.alert.status;
    });

    if (!activeKeys.length) return 'idle';

    const coverage = activeKeys.length >= districtKeys.length ? 'full' : 'partial';

    const levels = new Set();
    for (const key of activeKeys) {
        const d = districts[key];
        if (d && d.alert) {
            levels.add(alertLevel(d.alert));
        }
    }

    if (levels.size > 1) return 'mixed';

    const level = levels.values().next().value || DEFAULT_ALERT_LEVEL;
    return coverage === 'partial' ? level + '-partial' : level;
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

function attachOblastScrollbar(view) {
    const host = view.parentElement;
    if (!host || host.querySelector('.scroller-bar')) return null;

    const bar = document.createElement('div');
    bar.className = 'scroller-bar';
    bar.setAttribute('aria-hidden', 'true');
    const thumb = document.createElement('div');
    thumb.className = 'scroller-thumb';
    bar.appendChild(thumb);
    host.appendChild(bar);
    host.classList.add('is-live');

    const range = () => view.scrollHeight - view.clientHeight;

    function update() {
        const max = range();
        host.classList.toggle('is-scrollable', max > 1);
        if (max <= 1) return;
        const track = bar.clientHeight || view.clientHeight || (host.clientHeight ? host.clientHeight : 0);
        if (track <= 0) return;
        const height = Math.max(24, Math.round(track * view.clientHeight / view.scrollHeight));
        const free = Math.max(0, track - height);
        const clampedTop = Math.max(0, Math.min(view.scrollTop, max));
        const y = max > 0 ? Math.round(free * clampedTop / max) : 0;
        thumb.style.height = height + 'px';
        thumb.style.webkitTransform = `translate3d(0, ${y}px, 0)`;
        thumb.style.transform = `translate3d(0, ${y}px, 0)`;
    }

    let fromY = 0, fromTop = 0;

    thumb.addEventListener('pointerdown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        thumb.setPointerCapture(e.pointerId);
        host.classList.add('is-dragging');
        fromY = e.clientY;
        fromTop = view.scrollTop;
    });

    thumb.addEventListener('pointermove', (e) => {
        if (!host.classList.contains('is-dragging')) return;
        const free = bar.clientHeight - thumb.offsetHeight;
        if (free > 0) view.scrollTop = fromTop + (e.clientY - fromY) * range() / free;
    });

    const drop = () => host.classList.remove('is-dragging');
    thumb.addEventListener('pointerup', drop);
    thumb.addEventListener('pointercancel', drop);

    bar.addEventListener('pointerdown', (e) => {
        if (e.target === thumb) return;
        e.stopPropagation();
        const free = bar.clientHeight - thumb.offsetHeight;
        if (free <= 0) return;
        const at = e.clientY - bar.getBoundingClientRect().top - thumb.offsetHeight / 2;
        view.scrollTop = Math.min(Math.max(at, 0), free) * range() / free;
    });

    view.addEventListener('scroll', update, { passive: true });
    if (window.ResizeObserver) new ResizeObserver(update).observe(view);
    update();
    requestAnimationFrame(update);

    return { update };
}

function getOblastPopupContent(oblastData) {
    if (!oblastData) {
        return `
      <div class="container">
          ${renderPill({ variant: 'unknown', showTime: false })}
      </div>`;
    }

    const districts = oblastData.districts || oblastData;
    const districtKeys = Object.keys(districts).filter(k => k !== 'alert' && k !== 'shelling' && k !== 'explosion' && k !== 'title');

    if (!districtKeys.length) {
        return `
      <div class="container">
          ${renderPill({ variant: 'unknown', showTime: false })}
      </div>`;
    }

    let rows = '';
    for (const key of districtKeys) {
        const district = districts[key] || {};
        const districtName = district.title || district.name || key;
        rows += `
              <div class="popup-city">
                  <div class="popup-city-name">${districtName}</div>
                  ${renderPill(districtPillState(district))}
              </div>`;
    }

    return `
      <div class="container scroller">
          <div class="scrollable-content scroller-view">${rows}
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

            const cityMarker = CITY_REGIONS[regionId];

            layer.bindPopup(
                () => {
                    const data = oblastData(regionId) || {};
                    const title = (data && data.title) || regionId;
                    return cityMarker
                        ? getMarkerPopupContent(cityMarker, getMarkerThreats(SirensThreats.get(), cityMarker))
                        : '<div class="oblast-name">' + title + '</div>' + getOblastPopupContent(data);
                },
                customOptions
            );
            layer.on('popupopen', (e) => {
                const data = oblastData(regionId) || {};
                const title = (data && data.title) || regionId;
                if (window.track) window.track('region_popup_open', {
                    region_name: title,
                    threat_state: oblastState(data)
                });
                const popupEl = (e && e.popup) ? e.popup.getElement() : null;
                if (popupEl) {
                    const view = popupEl.querySelector('.scrollable-content');
                    if (view) attachOblastScrollbar(view);
                }
            });
        }
    }).addTo(map);

    map.on('popupopen', (e) => {
        const popupEl = (e && e.popup) ? e.popup.getElement() : null;
        if (popupEl) {
            const view = popupEl.querySelector('.scrollable-content');
            if (view) attachOblastScrollbar(view);
        }
    });

    ensureHatchDefs(map);
    applyZoomBand(map);
    map.on('zoomend', () => applyZoomBand(map));
}

// Шар будується один раз, а далі лише перефарбовується: перестворювати
// його на кожній відповіді означало б згортати відкритий попап і на мить
// лишати мапу без областей.
function paintOblasts(data) {
    if (!oblastLayer || !data) return;

    let changed = false;
    oblastLayer.eachLayer(function(layer) {
        const regionData = data[layer.feature.properties.id] || {};
        if (setOblastStyle(layer, regionData)) changed = true;
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

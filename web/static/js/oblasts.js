


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

    const alertLevelFn = typeof alertLevel !== 'undefined'
        ? alertLevel
        : (typeof require !== 'undefined' ? require('./districts.js').alertLevel : () => 'red');
    const defaultLevel = typeof DEFAULT_ALERT_LEVEL !== 'undefined' ? DEFAULT_ALERT_LEVEL : 'red';

    const levels = new Set();
    for (const key of activeKeys) {
        const d = districts[key];
        if (d && d.alert) {
            levels.add(alertLevelFn(d.alert));
        }
    }

    if (levels.size > 1) return 'mixed';

    const level = levels.values().next().value || defaultLevel;
    return coverage === 'partial' ? level + '-partial' : level;
}




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

    
    
    
    if (layer.sirensState === state) return false;

    const path = layer._path;
    if (path) {
        if (layer.sirensState) path.classList.remove('map-oblast--' + layer.sirensState);
        path.classList.add('map-oblast--' + state);
    }

    layer.sirensState = state;
    return true;
}



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
    if (window.ResizeObserver) {
        const ro = new ResizeObserver(update);
        ro.observe(view);
        if (host) ro.observe(host);
    }
    update();
    requestAnimationFrame(update);

    return { update };
}

function getOblastPopupContent(oblastData) {
    const renderPillFn = typeof renderPill !== 'undefined'
        ? renderPill
        : (typeof require !== 'undefined' ? require('./districts.js').renderPill : () => '');
    const districtPillStateFn = typeof districtPillState !== 'undefined'
        ? districtPillState
        : (typeof require !== 'undefined' ? require('./districts.js').districtPillState : () => ({ variant: 'unknown' }));

    if (!oblastData) {
        return `
      <div class="container">
          ${renderPillFn({ variant: 'unknown', showTime: false })}
      </div>`;
    }

    const districts = oblastData.districts || oblastData;
    const districtKeys = Object.keys(districts).filter(k => k !== 'alert' && k !== 'shelling' && k !== 'explosion' && k !== 'title');

    if (!districtKeys.length) {
        return `
      <div class="container">
          ${renderPillFn({ variant: 'unknown', showTime: false })}
      </div>`;
    }

    const items = districtKeys.map(key => {
        const district = districts[key] || {};
        const rawName = district.title || district.name || key;
        const districtName = rawName.replace(/^м\.\s+/, '');
        const pill = districtPillStateFn(district);
        const rawTime = pill && pill.updatedAt;
        const time = (typeof rawTime === 'number' && Number.isFinite(rawTime))
            ? rawTime
            : (rawTime && Number.isFinite(Number(rawTime)) ? Number(rawTime) : 0);
        return {
            key,
            district,
            districtName,
            pill,
            time
        };
    });

    const isAlertActive = (item) => {
        const d = item.district;
        if (d && ((d.alert && d.alert.status) || (d.shelling && d.shelling.status))) return true;
        const v = item.pill && item.pill.variant;
        return Boolean(v && v !== 'idle' && v !== 'unknown');
    };

    items.sort((a, b) => {
        const aActive = isAlertActive(a) ? 1 : 0;
        const bActive = isAlertActive(b) ? 1 : 0;

        if (bActive !== aActive) {
            return bActive - aActive;
        }

        if (b.time !== a.time) {
            return b.time - a.time;
        }

        return a.districtName.localeCompare(b.districtName, 'uk');
    });

    let rows = '';
    for (const item of items) {
        rows += `
              <div class="popup-city">
                  <div class="popup-city-name">${item.districtName}</div>
                  ${renderPillFn(item.pill)}
              </div>`;
    }

    return `
      <div class="container scroller">
          <div class="scrollable-content scroller-view">${rows}
          </div>
      </div>`;
}




const CITY_REGIONS = {};
const _districtMarkers = (typeof DISTRICT_MARKERS !== 'undefined')
    ? DISTRICT_MARKERS
    : (typeof require !== 'undefined' ? require('./districts.js').DISTRICT_MARKERS : []);
for (const marker of _districtMarkers) {
    if (marker.oblast === marker.district) CITY_REGIONS[marker.oblast] = marker;
}

var customOptions = {'maxWidth': '310', 'width': '310'};

let oblastLayer = null;



function oblastData(regionId) {
    const data = SirensThreats.get();
    return data ? data[regionId] : null;
}

function buildOblasts(geoData) {
    oblastLayer = L.geoJSON(geoData, {
        
        
        
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
                    const rawTitle = (data && data.title) || regionId;
                    const title = rawTitle.replace(/^м\.\s+/, '');
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




function paintOblasts(data) {
    if (!oblastLayer || !data) return;

    let changed = false;
    oblastLayer.eachLayer(function(layer) {
        const regionData = data[layer.feature.properties.id] || {};
        if (setOblastStyle(layer, regionData)) changed = true;
    });

    
    if (changed) orderOblastStrokes();
}



if (typeof window !== 'undefined' && typeof fetch !== 'undefined' && typeof SirensThreats !== 'undefined') {
    fetch('https://geo.sirens.live/ukraine.geojson')
        .then(res => res.json())
        .then(geoData => {
            SirensThreats.onPaint(function(data) {
                if (!oblastLayer) buildOblasts(geoData);
                paintOblasts(data);
            });
        })
        .catch(error => { console.error('Error fetching data:', error); });
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        oblastState,
        getOblastPopupContent
    };
}

/* Експериментальна мапа тривог за районами (District-level alert map).
   Реалізує дворівневу геометрію:
   1. Нижній шар: контури областей на pane 'oblastPane' (z-index 350)
      для пізнаваного каркаса країни.
   2. Верхній шар: інтерактивні полігони окремих районів України із плавною
      підсвіткою при наведенні та персистентним виділенням без мерехтіння.
   3. Попапи районів за усталеною дизайн-системою головної версії:
      - Головний заголовок: Inter, назва району.
      - Підзаголовок: JetBrains Mono, назва області.
      - Фіксований розмір кожного попапа (310px).
      - Вивірені типографічні відступи (2px між назвою району та області, 10px до першої плашки).
      - Верстка з Telegram-каналом (відступ 8px) та без нього (без зайвого простору внизу).
      - Без скролбарів.
*/

(function () {
    'use strict';

    let districtLayer = null;
    let geoDistrictsData = null;
    let geoOblastsData = null;
    let currentThreatsData = null;
    let selectedDistrictLayer = null;
    const districtLayersById = {};

    // Суворо фіксовані розміри попапа з точним позиціонуванням:
    // offset: [0, 8] — вістря попапа влучає строго в точку кліку на мапі/районі
    const districtPopupOptions = {
        maxWidth: 310,
        minWidth: 310,
        width: 310,
        className: 'district-leaflet-popup',
        offset: [0, 8]
    };

    // offset: [0, -2] — невеликий охайний простір (~3px) між маркером та вістрям попапа
    const markerPopupOptions = {
        maxWidth: 310,
        minWidth: 310,
        width: 310,
        className: 'district-leaflet-popup',
        offset: [0, -2]
    };

    const customOptions = districtPopupOptions;

    const SCENARIOS = {};

    /* ── Смуги зума ─────────────────────────────────────────────────── */
    const ZOOM_BANDS = [
        { upTo: 5, name: 'wide' },
        { upTo: 6, name: 'far' },
        { upTo: 8, name: 'mid' },
        { upTo: Infinity, name: 'near' }
    ];

    function applyZoomBand(map) {
        if (!map) return;
        const zoom = map.getZoom();
        const band = ZOOM_BANDS.find(entry => zoom <= entry.upTo);
        if (band) {
            map.getContainer().dataset.zoom = band.name;
        }
    }

    /* ── Визначення стану окремого району ───────────────────────────── */
    function getDistrictState(apiData, oblastId, districtId) {
        if (!apiData || !oblastId || !districtId) return 'idle';

        const oblastData = apiData[oblastId];
        if (!oblastData) return 'idle';

        const districts = oblastData.districts || oblastData;
        let d = districts[districtId];

        if (!d && districtId.endsWith('_raion')) {
            const parentId = districtId.replace('_raion', '');
            const parentD = districts[parentId];
            if (parentD) {
                if (parentD.alert && parentD.alert.status) {
                    const levelFn = typeof alertLevel === 'function' ? alertLevel : () => 'red';
                    return levelFn(parentD.alert);
                }
            }
            return 'idle';
        }

        if (!d) return 'idle';

        if (d.shelling && d.shelling.status) {
            return 'shelling';
        }

        if (d.alert && d.alert.status) {
            const levelFn = typeof alertLevel === 'function' ? alertLevel : () => 'red';
            return levelFn(d.alert);
        }

        return 'idle';
    }

    /* ── Кнопка підписки на сповіщення в Telegram ────────────────────── */
    function subscribeButtonHtml(channel) {
        if (!channel) return '';
        return `
            <div class="info-block">
                <a href="tg://resolve?domain=${channel}" class="oblast-button-link" target="_blank" rel="noopener noreferrer">
                    <button class="channel-popup-button">
                        <div class="icon-container-marker">
                            <img class="icon-marker" src="/static/img/icons/telegram.svg" alt="" aria-hidden="true">
                        </div>
                        Підписатися на сповіщення
                    </button>
                </a>
            </div>`;
    }

    /* ── Визначення стану контуру всієї області ─────────────────────── */
    function getOblastOutlineState(apiData, oblastId) {
        return 'idle';
    }

    /* ── Попап для району за усталеною дизайн-системою ─────────────────── */
    function getDistrictPopupContent(feature, apiData) {
        if (!feature || !feature.properties) return '';
        const districtId = feature.properties.id;
        const oblastId = feature.properties.oblast;
        let districtName = (feature.properties.name || districtId).replace(/^м\.\s+/, '');
        if (districtId === 'crimea') {
            districtName = 'Крим';
        }

        const oblastData = (apiData && apiData[oblastId]) || {};
        const districts = oblastData.districts || oblastData;
        let districtData = (districts && districts[districtId]) || {};
        if (!districtData.title && districtId.endsWith('_raion')) {
            const parentId = districtId.replace('_raion', '');
            const parentD = districts[parentId];
            if (parentD) {
                districtData = {
                    title: districtName,
                    alert: parentD.alert || { status: false },
                    shelling: { status: false }
                };
            }
        }

        const districtPillStateFn = typeof districtPillState === 'function'
            ? districtPillState
            : (typeof require !== 'undefined' ? require('./districts.js').districtPillState : () => ({ variant: 'unknown' }));
        const renderPillFn = typeof renderPill === 'function'
            ? renderPill
            : (typeof require !== 'undefined' ? require('./districts.js').renderPill : () => '');

        const pillState = districtPillStateFn(districtData);

        // Пошук каналу у переліку маркерів (тільки для районів із налаштованим оповіщенням)
        const markersList = typeof DISTRICT_MARKERS !== 'undefined'
            ? DISTRICT_MARKERS
            : (typeof require !== 'undefined' ? require('./districts.js').DISTRICT_MARKERS : []);
        const marker = markersList.find(m => m.district === districtId || (districtId && districtId.endsWith('_raion') && m.district === districtId.replace('_raion', '')));
        const channel = (marker && marker.channel) ? marker.channel : null;
        const channelHtml = subscribeButtonHtml(channel);

        return `
            <div class="district-popup">
                <div class="district-popup-header">
                    <div class="district-popup-name">${districtName}</div>
                </div>
                ${renderPillFn(pillState)}${channelHtml ? '\n                ' + channelHtml : ''}
            </div>
        `.trim();
    }

    /* ── Плавне персистентне виділення району без мерехтіння ─────────── */
    function setSelectedDistrict(layer) {
        if (!layer || selectedDistrictLayer === layer) return;

        if (selectedDistrictLayer && selectedDistrictLayer._path) {
            selectedDistrictLayer._path.classList.remove('map-district--selected');
        }

        selectedDistrictLayer = layer;

        if (layer._path) {
            layer._path.classList.add('map-district--selected');
            const parent = layer._path.parentNode;
            if (parent && parent.lastElementChild !== layer._path) {
                parent.appendChild(layer._path);
            }
        }
    }

    function clearSelectedDistrict() {
        if (selectedDistrictLayer) {
            if (selectedDistrictLayer._path) {
                selectedDistrictLayer._path.classList.remove('map-district--selected');
            }
            selectedDistrictLayer = null;
        }
    }

    /* ── Точки міст мовлення ────────────────────────────────────────── */
    const PIN_SIZE = 12;

    const PIN_STATES = {
        idle:      { lift: 0 },
        yellow:    { lift: 200 },
        shelling:  { lift: 200 },
        red:       { lift: 400 },
        explosion: { lift: 400 }
    };

    function pinState(threats) {
        const pickDominantFn = typeof pickDominant === 'function'
            ? pickDominant
            : (typeof require !== 'undefined' ? require('./districts.js').pickDominant : () => null);
        const threatVariantFn = typeof threatVariant === 'function'
            ? threatVariant
            : (typeof require !== 'undefined' ? require('./districts.js').threatVariant : (k, w) => k || 'idle');
        const dominant = pickDominantFn(threats);
        return dominant ? threatVariantFn(dominant, threats[dominant]) : 'idle';
    }

    const LABEL_REACH = 0.9;

    function labelSide(marker) {
        const markersList = typeof DISTRICT_MARKERS !== 'undefined'
            ? DISTRICT_MARKERS
            : (typeof require !== 'undefined' ? require('./districts.js').DISTRICT_MARKERS : []);
        const scale = Math.cos(marker.lat * Math.PI / 180);
        let pull = 0;

        for (const other of markersList) {
            if (other === marker) continue;

            const dx = (other.lng - marker.lng) * scale;
            const dy = other.lat - marker.lat;
            const distance = dx * dx + dy * dy;
            if (!distance || distance > LABEL_REACH * LABEL_REACH) continue;

            pull += dx / distance;
        }

        return pull > 0 ? 'left' : 'right';
    }

    function pinIcon(marker, state) {
        const isNikopol = marker.district === 'nikopol';
        const side = labelSide(marker);
        const nikopolCls = isNikopol ? ' map-pin--nikopol' : '';
        const className = 'map-pin map-pin--' + state + ' map-pin--label-' + side + nikopolCls;
        const cityName = (marker.name || '').replace(/^м\.\s+/, '');
        const html = '<span class="map-pin__dot"></span><span class="map-pin__name">' + cityName + '</span>';
        if (typeof L === 'undefined' || !L.divIcon) {
            return {
                options: {
                    className: className,
                    html: html,
                    iconSize: [PIN_SIZE, PIN_SIZE],
                    iconAnchor: [PIN_SIZE / 2, PIN_SIZE / 2],
                    popupAnchor: [0, -PIN_SIZE / 2]
                }
            };
        }
        return L.divIcon({
            className: className,
            html: html,
            iconSize: [PIN_SIZE, PIN_SIZE],
            iconAnchor: [PIN_SIZE / 2, PIN_SIZE / 2],
            popupAnchor: [0, -PIN_SIZE / 2]
        });
    }

    /* Уніфікований попап для міст/районів без окремого дублюючого попапа */
    function getMarkerPopupContent(marker, threats) {
        const feat = (geoDistrictsData && geoDistrictsData.features)
            ? geoDistrictsData.features.find(f => f.properties.id === marker.district)
            : { properties: { id: marker.district, oblast: marker.oblast, name: marker.name } };
        const apiData = currentThreatsData || (typeof SirensThreats !== 'undefined' ? SirensThreats.get() : null);
        return getDistrictPopupContent(feat, apiData);
    }

    function isMobileClient() {
        if (typeof window === 'undefined') return false;
        return /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent)
            || (typeof window.matchMedia === 'function' && window.matchMedia('(pointer: coarse)').matches);
    }

    /* Знаходження маркера поблизу точки кліку:
       - На мобільному: більший радіус (28px) під дотик пальця
       - На десктопі: невеликий радіус (14px) для точного кліку поруч із маркером
       - Якщо передано districtId: шукаємо тільки маркер цього конкретного району,
         щоб клік по сусідньому району не чіпляв чужий якорний маркер */
    function findNearbyMarker(latlng, targetMap, districtId) {
        if (!latlng || !targetMap || !targetMap.latLngToContainerPoint) return null;
        const markersList = typeof DISTRICT_MARKERS !== 'undefined'
            ? DISTRICT_MARKERS
            : (typeof require !== 'undefined' ? require('./districts.js').DISTRICT_MARKERS : []);
        if (!markersList || !markersList.length) return null;

        const clickPt = targetMap.latLngToContainerPoint(latlng);
        const maxDistPx = isMobileClient() ? 28 : 14;

        let nearest = null;
        let minDist = Infinity;
        for (const m of markersList) {
            if (districtId && m.district !== districtId) continue;
            const mPt = targetMap.latLngToContainerPoint([m.lat, m.lng]);
            const d = Math.hypot(clickPt.x - mPt.x, clickPt.y - mPt.y);
            if (d <= maxDistPx && d < minDist) {
                minDist = d;
                nearest = m;
            }
        }
        return nearest;
    }

    /* Відкриття єдиного попапа району безпосередньо над точкою міста */
    function openDistrictPopupForMarker(marker, targetMap) {
        const m = targetMap || (typeof map !== 'undefined' ? map : (typeof window !== 'undefined' ? window.sirensMap : null));
        if (!m || !marker) return;

        const dId = marker.district;
        const dLayer = districtLayersById[dId];

        const feat = (geoDistrictsData && geoDistrictsData.features)
            ? geoDistrictsData.features.find(f => f.properties.id === dId)
            : { properties: { id: marker.district, oblast: marker.oblast, name: marker.name } };
        const apiData = currentThreatsData || (typeof SirensThreats !== 'undefined' ? SirensThreats.get() : null);
        const html = getDistrictPopupContent(feat, apiData);

        if (html && typeof L !== 'undefined' && L.popup) {
            L.popup(markerPopupOptions)
                .setLatLng([marker.lat, marker.lng])
                .setContent(html)
                .openOn(m);
        }

        if (dLayer) {
            setSelectedDistrict(dLayer);
        }

        if (window.track) {
            window.track('district_popup_open', {
                district_id: dId,
                oblast_id: marker.oblast
            });
        }
    }

    const CITY_MARKERS = [];

    function markerThreats(marker) {
        const data = currentThreatsData || (typeof SirensThreats !== 'undefined' ? SirensThreats.get() : null);
        const getMarkerThreatsFn = typeof getMarkerThreats === 'function'
            ? getMarkerThreats
            : (typeof require !== 'undefined' ? require('./districts.js').getMarkerThreats : () => ({ alert: null, explosion: null, shelling: null }));
        return getMarkerThreatsFn(data, marker);
    }

    function applyPinState(entry, state) {
        entry.layer.setIcon(pinIcon(entry.marker, state));
        entry.layer.setZIndexOffset((PIN_STATES[state] || PIN_STATES.idle).lift);
        nameElement(entry);
    }

    function nameElement(entry) {
        const element = entry.layer.getElement ? entry.layer.getElement() : null;
        if (element) {
            const cityName = (entry.marker.name || '').replace(/^м\.\s+/, '');
            element.setAttribute('aria-label', cityName);
            element.removeAttribute('title');
        }
    }

    function buildCities(data, targetMap) {
        const m = targetMap || (typeof map !== 'undefined' ? map : (typeof window !== 'undefined' ? window.sirensMap : null));
        if (!m || typeof L === 'undefined' || !L.marker) return;

        const markersList = typeof DISTRICT_MARKERS !== 'undefined'
            ? DISTRICT_MARKERS
            : (typeof require !== 'undefined' ? require('./districts.js').DISTRICT_MARKERS : []);
        const getMarkerThreatsFn = typeof getMarkerThreats === 'function'
            ? getMarkerThreats
            : (typeof require !== 'undefined' ? require('./districts.js').getMarkerThreats : () => ({ alert: null, explosion: null, shelling: null }));

        CITY_MARKERS.length = 0;

        markersList.forEach(marker => {
            const threats = getMarkerThreatsFn(data, marker);
            const state = pinState(threats);
            const layer = L.marker([marker.lat, marker.lng], {
                icon: pinIcon(marker, state),
                zIndexOffset: (PIN_STATES[state] || PIN_STATES.idle).lift
            });

            // Окремий поп-ап маркера прибрано: клік по маркеру відкриває попап над маркером
            layer.on('click', function (e) {
                if (e && e.originalEvent && typeof L !== 'undefined' && L.DomEvent) {
                    L.DomEvent.stopPropagation(e.originalEvent);
                }
                openDistrictPopupForMarker(marker, m);
            });

            layer.addTo(m);

            const entry = { marker: marker, layer: layer, state: state };
            nameElement(entry);
            CITY_MARKERS.push(entry);
        });
    }

    function paintCities(data, targetMap) {
        if (!CITY_MARKERS.length) {
            buildCities(data, targetMap);
            return;
        }

        const getMarkerThreatsFn = typeof getMarkerThreats === 'function'
            ? getMarkerThreats
            : (typeof require !== 'undefined' ? require('./districts.js').getMarkerThreats : () => ({ alert: null, explosion: null, shelling: null }));

        for (const entry of CITY_MARKERS) {
            const state = pinState(getMarkerThreatsFn(data, entry.marker));
            if (entry.state === state) continue;

            entry.state = state;
            applyPinState(entry, state);
        }
    }

    /* ── Побудова шарів ──────────────────────────────────────────────── */
    function initDistrictMap(map, districtsGeo, oblastsGeo) {
        if (!map) return;

        if (!map.getPane('oblastPane')) {
            const oblastPane = map.createPane('oblastPane');
            oblastPane.style.zIndex = '350';
            oblastPane.style.pointerEvents = 'none';
        }

        if (oblastsGeo) {
            L.geoJSON(oblastsGeo, {
                pane: 'oblastPane',
                interactive: false,
                style: function () {
                    return {
                        className: 'map-oblast-border',
                        stroke: true,
                        fill: false
                    };
                }
            }).addTo(map);
        }

        districtLayer = L.geoJSON(districtsGeo, {
            style: function () {
                return {
                    className: 'map-district map-district--idle',
                    stroke: true,
                    fill: true
                };
            },
            onEachFeature: function (feature, layer) {
                if (feature.properties && feature.properties.id) {
                    districtLayersById[feature.properties.id] = layer;
                }
                layer.bindPopup(function () {
                    const apiData = currentThreatsData || (typeof SirensThreats !== 'undefined' ? SirensThreats.get() : null);
                    return getDistrictPopupContent(feature, apiData);
                }, districtPopupOptions);

                // Якщо клік поруч із маркером (14px десктоп, 28px мобільний) — відкриваємо над маркером,
                // інакше — відкриваємо точно за координатами кліку на районі.
                layer.off('click', layer._openPopup, layer);
                layer.on('click', function (e) {
                    if (e && e.originalEvent && typeof L !== 'undefined' && L.DomEvent) {
                        L.DomEvent.stopPropagation(e.originalEvent);
                    }
                    const nearby = findNearbyMarker(e && e.latlng, map, feature.properties.id);
                    if (nearby) {
                        openDistrictPopupForMarker(nearby, map);
                        return;
                    }
                    layer.openPopup(e && e.latlng);
                });

                layer.on('popupopen', function () {
                    setSelectedDistrict(layer);
                    if (window.track) {
                        window.track('district_popup_open', {
                            district_id: feature.properties.id,
                            oblast_id: feature.properties.oblast
                        });
                    }
                });
            }
        }).addTo(map);

        map.on('popupclose', function (e) {
            clearSelectedDistrict();
        });

        buildCities(currentThreatsData, map);

        applyZoomBand(map);
        map.on('zoom zoomend', () => {
            applyZoomBand(map);
        });

        const urlParams = new URLSearchParams(window.location.search);
        const openDistrict = urlParams.get('district');
        if (openDistrict && districtLayersById[openDistrict]) {
            districtLayersById[openDistrict].openPopup();
        }
    }

    /* ── Картографічна ієрархія штрихів ──────────────────────────────── */
    const STROKE_ORDER = {
        idle: 0,
        yellow: 1,
        red: 2,
        shelling: 3
    };

    function orderDistrictStrokes() {
        if (!districtLayer) return;
        const layers = [];
        districtLayer.eachLayer(layer => {
            if (layer._path) layers.push(layer);
        });
        if (!layers.length) return;

        layers.sort((a, b) =>
            (STROKE_ORDER[a._sirensDistrictState] || 0) - (STROKE_ORDER[b._sirensDistrictState] || 0)
        );

        const parent = layers[0]._path.parentNode;
        if (parent) {
            let needsReorder = false;
            let current = parent.firstElementChild;
            for (let i = 0; i < layers.length; i++) {
                if (current !== layers[i]._path) {
                    needsReorder = true;
                    break;
                }
                current = current.nextElementSibling;
            }

            if (needsReorder) {
                for (const layer of layers) {
                    parent.appendChild(layer._path);
                }
            }

            if (selectedDistrictLayer && selectedDistrictLayer._path) {
                if (parent.lastElementChild !== selectedDistrictLayer._path) {
                    parent.appendChild(selectedDistrictLayer._path);
                }
            }
        }
    }

    /* ── Оновлення кольорів при зміні даних ───────────────────────────── */
    function paintDistricts(apiData) {
        if (!apiData) return;

        currentThreatsData = apiData;

        let changed = false;
        if (districtLayer) {
            districtLayer.eachLayer(function (layer) {
                const feat = layer.feature;
                if (!feat || !feat.properties) return;

                const districtId = feat.properties.id;
                const oblastId = feat.properties.oblast;
                const state = getDistrictState(apiData, oblastId, districtId);

                if (layer._sirensDistrictState !== state) {
                    const path = layer._path;
                    if (path) {
                        if (layer._sirensDistrictState) {
                            path.classList.remove('map-district--' + layer._sirensDistrictState);
                        }
                        path.classList.remove('map-district--idle');
                        path.classList.add('map-district--' + state);

                        if (layer === selectedDistrictLayer) {
                            path.classList.add('map-district--selected');
                        }
                    }
                    layer._sirensDistrictState = state;
                    changed = true;
                }
            });
        }

        if (changed) {
            orderDistrictStrokes();
        }

        paintCities(apiData);
    }

    /* ── Завантаження геометрії та старт ──────────────────────────────── */
    function loadAndInit() {
        const map = window.sirensMap;
        if (!map) {
            setTimeout(loadAndInit, 50);
            return;
        }

        const districtsUrl = window.GEO_DISTRICTS_URL || 'https://geo.sirens.live/districts.geojson';
        const oblastsUrl = window.GEO_OBLASTS_URL || 'https://geo.sirens.live/oblasts.geojson';

        Promise.all([
            fetch(districtsUrl).then(r => r.json()),
            fetch(oblastsUrl).then(r => r.json())
        ])
        .then(([districts, oblasts]) => {
            geoDistrictsData = districts;
            geoOblastsData = oblasts;

            initDistrictMap(map, districts, oblasts);

            if (typeof SirensThreats !== 'undefined') {
                SirensThreats.onPaint(paintDistricts);
                const currentData = SirensThreats.get();
                if (currentData) {
                    paintDistricts(currentData);
                }
            }
        })
        .catch(err => {
            console.error('Failed to load district geometries:', err);
        });
    }

    if (typeof window !== 'undefined') {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', loadAndInit);
        } else {
            loadAndInit();
        }
    }

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = {
            getDistrictState,
            getOblastOutlineState,
            getDistrictPopupContent,
            subscribeButtonHtml,
            SCENARIOS,
            pinState,
            pinIcon,
            labelSide,
            getMarkerPopupContent,
            buildCities,
            paintCities,
            CITY_MARKERS,
            PIN_STATES,
            PIN_SIZE,
            findNearbyMarker,
            openDistrictPopupForMarker,
            districtPopupOptions,
            markerPopupOptions,
            customOptions
        };
    }
})();

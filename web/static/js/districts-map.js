

(function () {
    'use strict';

    let districtLayer = null;
    let geoDistrictsData = null;
    let geoOblastsData = null;
    let currentThreatsData = null;
    let selectedDistrictLayer = null;
    const districtLayersById = {};

    
    
    const districtPopupOptions = {
        maxWidth: 310,
        minWidth: 310,
        width: 310,
        className: 'district-leaflet-popup',
        offset: [0, 8]
    };

    
    const markerPopupOptions = {
        maxWidth: 310,
        minWidth: 310,
        width: 310,
        className: 'district-leaflet-popup',
        offset: [0, -2]
    };

    const customOptions = districtPopupOptions;

    const SCENARIOS = {};

    
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

    
    function getDistrictState(apiData, oblastId, districtId) {
        if (!apiData || !oblastId || !districtId) return 'idle';

        const oblastData = apiData[oblastId];
        if (!oblastData) return 'idle';

        const districts = oblastData.districts || oblastData;
        const getDistrictDataFn = typeof getDistrictData === 'function'
            ? getDistrictData
            : (typeof require !== 'undefined' ? require('./districts.js').getDistrictData : (dist, id) => dist ? dist[id] : null);
        const d = getDistrictDataFn(districts, districtId);
        if (!d) return 'idle';

        const isAlert = Boolean(d.alert && d.alert.status);
        const isShelling = Boolean(d.shelling && d.shelling.status);
        const levelFn = typeof alertLevel === 'function'
            ? alertLevel
            : (typeof require !== 'undefined' ? require('./districts.js').alertLevel : () => 'red');
        const aLevel = isAlert ? levelFn(d.alert) : null;

        if (aLevel === 'red') {
            return 'red';
        }
        if (isShelling) {
            return 'shelling';
        }
        if (aLevel === 'yellow') {
            return 'yellow';
        }

        return 'idle';
    }

    
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

    
    function getOblastOutlineState(apiData, oblastId) {
        return 'idle';
    }

    function attachScrollbar(view) {
        if (!view) return null;
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
        if (typeof ResizeObserver !== 'undefined') {
            const ro = new ResizeObserver(update);
            ro.observe(view);
            if (host) ro.observe(host);
        }
        update();
        return update;
    }

    
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
        const getDistrictDataFn = typeof getDistrictData === 'function'
            ? getDistrictData
            : (typeof require !== 'undefined' ? require('./districts.js').getDistrictData : (dist, id) => dist ? dist[id] : null);
        const districtData = getDistrictDataFn(districts, districtId) || {};

        const districtPillStateFn = typeof districtPillState === 'function'
            ? districtPillState
            : (typeof require !== 'undefined' ? require('./districts.js').districtPillState : () => ({ variant: 'unknown' }));
        const renderPillFn = typeof renderPill === 'function'
            ? renderPill
            : (typeof require !== 'undefined' ? require('./districts.js').renderPill : () => '');
        const alertLevelFn = typeof alertLevel === 'function'
            ? alertLevel
            : (typeof require !== 'undefined' ? require('./districts.js').alertLevel : () => 'red');

        const markersList = typeof DISTRICT_MARKERS !== 'undefined'
            ? DISTRICT_MARKERS
            : (typeof require !== 'undefined' ? require('./districts.js').DISTRICT_MARKERS : []);
        const isSplitRaion = (
            districtId === 'nikopol_district' ||
            districtId === 'nikopol_raion' ||
            districtId === 'kharkiv_district' ||
            districtId === 'kharkiv_raion' ||
            districtId === 'zaporizhzhia_district' ||
            districtId === 'zaporizhzhia_raion'
        );
        const marker = isSplitRaion
            ? markersList.find(m => m.district === districtId)
            : markersList.find(m => m.district === districtId || (districtId && (districtId.endsWith('_district') || districtId.endsWith('_raion')) && m.district === districtId.replace(/(_district|_raion)$/, '')));
        const channel = (marker && marker.channel) ? marker.channel : null;
        const channelHtml = subscribeButtonHtml(channel);

        if (districtId === 'nikopol') {
            const isAlertActive = Boolean(districtData.alert && districtData.alert.status);
            const isShellingActive = Boolean(districtData.shelling && districtData.shelling.status);

            const pills = [];

            if (isAlertActive) {
                const lvl = alertLevelFn(districtData.alert);
                if (lvl === 'yellow') {
                    pills.push({
                        variant: 'yellow',
                        updatedAt: districtData.alert.updated_at,
                        source: districtData.alert.source,
                        priority: 2
                    });
                } else {
                    pills.push({
                        variant: 'red',
                        updatedAt: districtData.alert.updated_at,
                        source: districtData.alert.source,
                        priority: 4
                    });
                }
            } else {
                pills.push({
                    variant: 'idle',
                    updatedAt: districtData.alert ? districtData.alert.updated_at : null,
                    source: districtData.alert ? districtData.alert.source : null,
                    priority: 1
                });
            }

            if (isShellingActive) {
                pills.push({
                    variant: 'shelling',
                    updatedAt: districtData.shelling.updated_at,
                    source: districtData.shelling.source,
                    priority: 3
                });
            }

            pills.sort((a, b) => b.priority - a.priority);

            const pillsHtml = pills.map(p => renderPillFn(p)).join('\n');

            if (pills.length > 1) {
                return `
            <div class="district-popup">
                <div class="district-popup-header">
                    <div class="district-popup-name">${districtName}</div>
                </div>
                <div class="container scroller">
                    <div class="scrollable-content scroller-view">
                        ${pillsHtml}${channelHtml ? '\n                        ' + channelHtml : ''}
                    </div>
                </div>
            </div>
                `.trim();
            }

            return `
            <div class="district-popup">
                <div class="district-popup-header">
                    <div class="district-popup-name">${districtName}</div>
                </div>
                ${pillsHtml}${channelHtml ? '\n                ' + channelHtml : ''}
            </div>
            `.trim();
        }

        const pillState = districtPillStateFn(districtData);

        return `
            <div class="district-popup">
                <div class="district-popup-header">
                    <div class="district-popup-name">${districtName}</div>
                </div>
                ${renderPillFn(pillState)}${channelHtml ? '\n                ' + channelHtml : ''}
            </div>
        `.trim();
    }

    
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

    
    const PIN_SIZE = 12;

    const PIN_STATES = {
        idle:      { lift: 0 },
        yellow:    { lift: 200 },
        shelling:  { lift: 300 },
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

    const CITY_POPUPS = new Set(['kharkiv', 'zaporizhzhia', 'nikopol', 'kyiv']);

    const MARKER_DISTRICT_NAMES = {
        bilatserkva: 'Білоцерківський район',
        bucha: 'Бучанський район',
        fastiv: 'Фастівський район',
        cherkasy: 'Черкаський район',
        chernihiv: 'Чернігівський район',
        chernivtsi: 'Чернівецький район',
        dnipro: 'Дніпровський район',
        ivanofrankivsk: 'Івано-Франківський район',
        kamianske: "Кам'янський район",
        kharkiv: 'Харків',
        khmelnytskyi: 'Хмельницький район',
        kovel: 'Ковельський район',
        kropyvnytskyi: 'Кропивницький район',
        kryvyirih: 'Криворізький район',
        kyiv: 'Київ',
        lutsk: 'Луцький район',
        lviv: 'Львівський район',
        mykolaiv: 'Миколаївський район',
        odesa: 'Одеський район',
        pervomaisk: 'Первомайський район',
        kremenchuk: 'Кременчуцький район',
        sumy: 'Сумський район',
        ternopil: 'Тернопільський район',
        vinnytsia: 'Вінницький район',
        uzhhorod: 'Ужгородський район',
        zaporizhzhia: 'Запоріжжя',
        zhytomyr: 'Житомирський район',
        rivne: 'Рівненський район',
        uman: 'Уманський район',
        poltava: 'Полтавський район',
        nikopol: 'Нікополь',
        kherson: 'Херсонський район',
        izmail: 'Ізмаїльський район',
        zolotonosha: 'Золотоніський район',
        zvenyhorodka: 'Звенигородський район'
    };

    function getFeatureForMarker(marker) {
        if (!marker) return null;

        let layerFeat = null;
        if (districtLayersById[marker.district] && districtLayersById[marker.district].feature) {
            layerFeat = districtLayersById[marker.district].feature;
        } else if (geoDistrictsData && Array.isArray(geoDistrictsData.features)) {
            layerFeat = geoDistrictsData.features.find(f => {
                if (!f.properties) return false;
                const id = f.properties.id;
                if (id === marker.district) return true;
                if (id.endsWith('_raion') && id.replace(/_raion$/, '') === marker.district) return true;
                if (id.endsWith('_district') && id.replace(/_district$/, '') === marker.district) return true;
                return false;
            });
        }

        if (CITY_POPUPS.has(marker.district)) {
            return {
                properties: {
                    id: marker.district,
                    oblast: marker.oblast,
                    name: (layerFeat && layerFeat.properties && layerFeat.properties.name)
                        || MARKER_DISTRICT_NAMES[marker.district]
                        || (marker.name || '').replace(/^м\.\s+/, '')
                }
            };
        }

        if (layerFeat && layerFeat.properties) {
            return layerFeat;
        }

        return {
            properties: {
                id: marker.district,
                oblast: marker.oblast,
                name: MARKER_DISTRICT_NAMES[marker.district]
                    || ((marker.name || '').replace(/^м\.\s+/, '') + ' район')
            }
        };
    }

    
    function getMarkerPopupContent(marker, threats) {
        const feat = getFeatureForMarker(marker);
        const apiData = currentThreatsData || (typeof SirensThreats !== 'undefined' ? SirensThreats.get() : null);
        return getDistrictPopupContent(feat, apiData);
    }

    function isMobileClient() {
        if (typeof window === 'undefined') return false;
        return /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent)
            || (typeof window.matchMedia === 'function' && window.matchMedia('(pointer: coarse)').matches);
    }

    
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
            if (districtId) {
                const cleanDistrictId = districtId.replace(/(_district|_raion)$/, '');
                if (m.district !== districtId && m.district !== cleanDistrictId) continue;
            }
            const mPt = targetMap.latLngToContainerPoint([m.lat, m.lng]);
            const d = Math.hypot(clickPt.x - mPt.x, clickPt.y - mPt.y);
            if (d <= maxDistPx && d < minDist) {
                minDist = d;
                nearest = m;
            }
        }
        return nearest;
    }

    
    function openDistrictPopupForMarker(marker, targetMap) {
        const m = targetMap || (typeof map !== 'undefined' ? map : (typeof window !== 'undefined' ? window.sirensMap : null));
        if (!m || !marker) return;

        const dId = marker.district;
        const dLayer = districtLayersById[dId];

        const feat = getFeatureForMarker(marker);
        const apiData = currentThreatsData || (typeof SirensThreats !== 'undefined' ? SirensThreats.get() : null);
        const html = getDistrictPopupContent(feat, apiData);

        if (html && typeof L !== 'undefined' && L.popup) {
            const popup = L.popup(markerPopupOptions)
                .setLatLng([marker.lat, marker.lng])
                .setContent(html)
                .openOn(m);

            const popupEl = (popup && popup.getElement) ? popup.getElement() : null;
            if (popupEl) {
                const view = popupEl.querySelector('.scrollable-content');
                if (view) attachScrollbar(view);
            }
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

    
    function initDistrictMap(map, districtsGeo, oblastsGeo) {
        if (!map) return;

        if (districtsGeo) {
            geoDistrictsData = districtsGeo;
        }
        if (oblastsGeo) {
            geoOblastsData = oblastsGeo;
        }

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
                    const id = feature.properties.id;
                    districtLayersById[id] = layer;
                    if (id.endsWith('_raion')) {
                        districtLayersById[id.replace(/_raion$/, '_district')] = layer;
                    } else if (id.endsWith('_district')) {
                        districtLayersById[id.replace(/_district$/, '_raion')] = layer;
                    } else if (id === 'chervonohrad') {
                        districtLayersById['sheptytskyi'] = layer;
                    } else if (id === 'sheptytskyi') {
                        districtLayersById['chervonohrad'] = layer;
                    }
                }
                layer.bindPopup(function () {
                    const apiData = currentThreatsData || (typeof SirensThreats !== 'undefined' ? SirensThreats.get() : null);
                    return getDistrictPopupContent(feature, apiData);
                }, districtPopupOptions);

                
                
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

                layer.on('popupopen', function (e) {
                    setSelectedDistrict(layer);
                    if (window.track) {
                        window.track('district_popup_open', {
                            district_id: feature.properties.id,
                            oblast_id: feature.properties.oblast
                        });
                    }
                    const popupEl = (e && e.popup && e.popup.getElement) ? e.popup.getElement() : (layer.getPopup ? layer.getPopup().getElement() : null);
                    if (popupEl) {
                        const view = popupEl.querySelector('.scrollable-content');
                        if (view) attachScrollbar(view);
                    }
                });
            }
        }).addTo(map);

        map.on('popupopen', function (e) {
            const popupEl = (e && e.popup && e.popup.getElement) ? e.popup.getElement() : null;
            if (popupEl) {
                const view = popupEl.querySelector('.scrollable-content');
                if (view) attachScrollbar(view);
            }
        });

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

    
    const STROKE_ORDER = {
        idle: 0,
        yellow: 1,
        shelling: 2,
        red: 3
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
            customOptions,
            attachScrollbar,
            CITY_POPUPS,
            getFeatureForMarker,
            MARKER_DISTRICT_NAMES,
            STROKE_ORDER
        };
    }
})();

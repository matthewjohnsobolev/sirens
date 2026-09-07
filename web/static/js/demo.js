/* Демонстраційний режим: /?demo

   Мапа показує стан, який зараз у країні, — і це означає, що більшість
   станів на ній одночасно не побачиш ніколи. Щоб дивитися на палітру, а
   не чекати на неї, демо підміняє відповідь /api набором, у якому всі
   стани стоять поруч: два рівні тривоги, кожен суцільний і по районах,
   область з обома рівнями відразу, загроза артобстрілу маркером і відбій.

   Дані тут вигадані від першої до останньої цифри, і мапа про це говорить
   вголос: сервіс про повітряні тривоги не має права ані на мить виглядати
   так, ніби показує справжню тривогу. Звідси й червона стрічка згори, і
   заголовок вкладки.

   Сам файл їде на сторінку лише за запитом — шаблон підключає його тільки
   коли в адресі є ?demo. */
(function () {
    'use strict';

    var params = new URLSearchParams(window.location.search);
    if (!params.has('demo')) return;

    var NOW = Math.floor(Date.now() / 1000);
    var MINUTE = 60;

    /* Стан на область. Разом вони покривають усе, що мапа вміє намалювати,
       і розкладені по країні так, щоб сусідні стани було з чим порівняти:
       жовтий поруч із червоним, суцільний поруч зі штрихованим.

       Неповним і комбінованим станам потрібні області з кількома
       районами: там, де район один, тривога буває тільки на всю область,
       а двом рівням просто нема де розійтися. */
    var SCENARIO = {
        // Червоний рівень — на всю область і по окремих районах
        kharkiv_oblast: 'red',
        sumy_oblast: 'red',
        chernihiv_oblast: 'red',
        poltava_oblast: 'red-partial',

        // Жовтий рівень — так само у двох варіантах
        lviv_oblast: 'yellow',
        volyn_oblast: 'yellow',
        rivne_oblast: 'yellow',
        ternopil_oblast: 'yellow',
        khmelnytskyi_oblast: 'yellow',
        vinnytsia_oblast: 'yellow',
        odesa_oblast: 'yellow-partial',
        mykolaiv_oblast: 'yellow-partial',

        // Обидва рівні в одній області: у частині районів жовтий, у
        // частині червоний. У Черкаській під тривогою всі райони, у
        // Житомирській і Київській — половина, тобто там є ще й відбій.
        // На мапі обидва випадки виглядають однаково, і саме це треба
        // бачити поруч: до двох рівнів третій стан нічого не додає.
        cherkasy_oblast: 'mixed',
        zhytomyr_oblast: 'mixed-half',
        kyiv_oblast: 'mixed-half',

        // Місто-регіон під тривогою
        kyiv: 'red',

        // Загроза артобстрілу. Полігон при цьому лишається спокійним:
        // обстріл оголошують району, а не області, тож говорить про нього
        // тільки маркер міста.
        dnipropetrovsk_oblast: 'shelling',

        // Вибухи: стан у відповіді є, але мапа його поки не малює —
        // Донецька має лишитися такою ж, як області у відбої.
        donetsk_oblast: 'explosion',

        // Немає даних: жодного району під наглядом
        crimea: 'unknown',
        sevastopol: 'unknown',
        luhansk_oblast: 'unknown'
    };

    var OBLASTS = [
        'cherkasy_oblast', 'chernihiv_oblast', 'chernivtsi_oblast', 'crimea',
        'dnipropetrovsk_oblast', 'donetsk_oblast', 'ivanofrankivsk_oblast',
        'kharkiv_oblast', 'kherson_oblast', 'khmelnytskyi_oblast',
        'kirovohrad_oblast', 'kyiv', 'kyiv_oblast', 'luhansk_oblast',
        'lviv_oblast', 'mykolaiv_oblast', 'odesa_oblast', 'poltava_oblast',
        'rivne_oblast', 'sevastopol', 'sumy_oblast', 'ternopil_oblast',
        'vinnytsia_oblast', 'volyn_oblast', 'zakarpattia_oblast',
        'zaporizhzhia_oblast', 'zhytomyr_oblast'
    ];

    // Райони беремо з переліку маркерів: демо має бути схожим на правду
    // рівно настільки, щоб мапа не відрізнила його від відповіді сервера.
    var DISTRICTS = {};
    for (var i = 0; i < DISTRICT_MARKERS.length; i++) {
        var m = DISTRICT_MARKERS[i];
        (DISTRICTS[m.oblast] = DISTRICTS[m.oblast] || []).push(m);
    }

    function isMixed(state) {
        return state.indexOf('mixed') === 0;
    }

    // Половина районів під тривогою — і для однорівневих станів, і для
    // комбінованого: різні назви, одне правило.
    function isHalf(state) {
        return state.indexOf('-partial') > 0 || state.indexOf('-half') > 0;
    }

    function isAlert(state) {
        return isMixed(state) || state.indexOf('red') === 0 || state.indexOf('yellow') === 0;
    }

    // У комбінованій області рівні чергуються по районах, у звичайній —
    // однакові в усіх.
    function levelAt(state, index) {
        if (isMixed(state)) return index % 2 ? 'red' : 'yellow';
        return state.indexOf('yellow') === 0 ? 'yellow' : 'red';
    }

    function quiet() {
        return { status: false, time: 'None', source: 'None', updated_at: 0 };
    }

    function active(minutesAgo, extra) {
        var threat = {
            status: true,
            time: '--:--',
            source: 'https://t.me/sirens_live/1',
            updated_at: NOW - minutesAgo * MINUTE
        };
        for (var key in extra) threat[key] = extra[key];
        return threat;
    }

    // Рівень їде двома шляхами одночасно — окремим полем level і хвостом
    // типу ('air_raid_alert:red'), — бо мапа вміє читати обидва, і демо
    // має перевіряти обидва.
    function alertAt(level, minutesAgo) {
        return active(minutesAgo, { level: level, type: 'air_raid_alert:' + level });
    }

    function buildOblast(id) {
        var state = SCENARIO[id] || 'idle';
        var markers = DISTRICTS[id] || [];
        var tracked = state === 'unknown' ? [] : markers.map(function (m) { return m.district; });

        // Неповна тривога — це частина районів під нею; саме так її рахує
        // сервер, виводячи coverage з active_districts. Комбінованій
        // потрібні щонайменше двоє: одному району двох рівнів не мати.
        var activeDistricts = [];
        if (isAlert(state)) {
            if (isHalf(state)) {
                var half = Math.floor(tracked.length / 2);
                activeDistricts = tracked.slice(0, Math.max(isMixed(state) ? 2 : 1, half));
            } else {
                activeDistricts = tracked.slice();
            }
        }

        // Обстріл оголошують району — беремо Нікополь, як воно й буває.
        var shellingDistricts = [];
        if (state === 'shelling') {
            shellingDistricts = tracked.indexOf('nikopol') >= 0 ? ['nikopol'] : tracked.slice(0, 1);
        }

        var districts = {};
        for (var i = 0; i < markers.length; i++) {
            var key = markers[i].district;
            var position = activeDistricts.indexOf(key);

            districts[key] = {
                name: markers[i].name,
                alert: position >= 0
                    ? alertAt(levelAt(state, position), 4 + position * 7)
                    : active(90 + i * 11, { status: false, type: 'air_raid_alert_cancelled' }),
                shelling: shellingDistricts.indexOf(key) >= 0 ? active(12) : quiet()
            };
        }

        // Рівень самої області — запасний: мапа читає рівні районів, а сюди
        // дивиться лише коли район свого запису не має. У комбінованій це
        // гірше з двох: контур має називати найнебезпечніше.
        var oblastAlert = isAlert(state) ? alertAt(levelAt(state, 1), 4) : quiet();
        oblastAlert.tracked_districts = tracked;
        oblastAlert.active_districts = activeDistricts;
        oblastAlert.coverage = activeDistricts.length
            ? (activeDistricts.length >= tracked.length ? 'full' : 'partial')
            : 'none';

        return {
            alert: oblastAlert,
            explosion: state === 'explosion' ? active(3) : quiet(),
            shelling: shellingDistricts.length ? active(12) : quiet(),
            districts: districts
        };
    }

    var PAYLOAD = {};
    for (var o = 0; o < OBLASTS.length; o++) {
        PAYLOAD[OBLASTS[o]] = buildOblast(OBLASTS[o]);
    }

    // Міста-виключення, які сервер віддає окремими ключами поряд з областями.
    PAYLOAD.nikopol = PAYLOAD.dnipropetrovsk_oblast;
    PAYLOAD.kherson = PAYLOAD.kherson_oblast;

    // Мапа ходить по дані звичайним fetch, тож підміняти достатньо його:
    // решта коду не знає, що вона в демо, і поводиться точно так само, як
    // на бойових даних. Усі інші запити — стиль підкладки, межі, статус —
    // ідуть як ішли.
    var realFetch = window.fetch.bind(window);

    // Відповідь віддається не раніше, ніж зібрано сторінку. Справжній
    // запит іде мережею й гарантовано доходить після того, як у <body>
    // створено мапу; готова відповідь із пам'яті випередила б її й
    // почала б фарбувати те, чого ще немає.
    function whenReady() {
        if (document.readyState !== 'loading') return Promise.resolve();
        return new Promise(function (resolve) {
            document.addEventListener('DOMContentLoaded', resolve, { once: true });
        });
    }

    window.fetch = function (input, init) {
        var url = typeof input === 'string' ? input : (input && input.url) || '';
        if (url === '/api' || url.indexOf('/api?') === 0) {
            return whenReady().then(function () {
                return new Response(JSON.stringify(PAYLOAD), {
                    status: 200,
                    headers: { 'Content-Type': 'application/json' }
                });
            });
        }
        return realFetch(input, init);
    };

    /* ── Помітка й легенда ──────────────────────────────────────────── */

    var STYLE = [
        '.demo-banner{position:fixed;inset:0 0 auto 0;z-index:1200;display:flex;',
        'align-items:center;justify-content:center;gap:8px;height:26px;',
        'background:#C0211A;color:#fff;font:600 11px/1 var(--font);',
        'letter-spacing:.06em;text-transform:uppercase;pointer-events:none}',
        '.demo-banner + #map{top:26px;height:calc(100% - 26px)}',
        '.demo-legend{background:var(--surface);border:1px solid var(--hairline);',
        'border-radius:var(--radius-card);box-shadow:var(--shadow-card);',
        'padding:12px;font-family:var(--font);font-size:11px;color:var(--ink);',
        'max-height:calc(100vh - 80px);overflow:auto}',
        '@media (max-width:700px){.demo-legend{padding:8px;font-size:10px;',
        'border-radius:var(--radius-control)}.demo-legend h2{margin-bottom:6px}}',
        '.demo-legend h2{margin:0 0 8px;font-size:10px;font-weight:700;',
        'letter-spacing:.08em;text-transform:uppercase;color:var(--ink-muted)}',
        '.demo-legend h2 + h2{margin-top:12px}',
        '.demo-legend li{display:flex;align-items:center;gap:8px;margin:0 0 6px;',
        'list-style:none;white-space:nowrap}',
        '.demo-legend ul{margin:0;padding:0}',
        '.demo-legend svg{flex:none}',
        '.demo-pin{position:relative;flex:none;width:26px;height:24px;',
        'display:flex;align-items:center;justify-content:center}',
        '.demo-pin img{width:22px;height:22px;display:block}'
    ].join('');

    var POLYGONS = [
        ['idle', 'Відбій'],
        ['yellow', 'Жовтий рівень'],
        ['yellow-partial', 'Жовтий рівень у районах'],
        ['red', 'Червоний рівень'],
        ['red-partial', 'Червоний рівень у районах'],
        ['mixed', 'Обидва рівні']
    ];

    var PINS = [
        ['idle', 'Відбій'],
        ['yellow', 'Жовтий рівень'],
        ['red', 'Червоний рівень'],
        ['shelling', 'Загроза артобстрілу']
    ];

    // Кожен зразок у легенді пофарбований тими самими класами й тими
    // самими файлами, що й мапа: якщо стан колись поїде, легенда поїде
    // разом із ним і не почне брехати.
    function legendHtml() {
        var html = '<h2>Області</h2><ul>';
        POLYGONS.forEach(function (row) {
            html += '<li><svg width="26" height="16">'
                + '<rect class="map-oblast map-oblast--' + row[0] + '" '
                + 'x="0.9" y="0.9" width="24.2" height="14.2" rx="3"/></svg>'
                + '<span>' + row[1] + '</span></li>';
        });
        html += '</ul><h2>Міста</h2><ul>';
        PINS.forEach(function (row) {
            html += '<li><span class="demo-pin map-pin map-pin--' + row[0] + '">'
                + pinBody() + '</span><span>' + row[1] + '</span></li>';
        });
        return html + '</ul>';
    }

    function mount() {
        var style = document.createElement('style');
        style.textContent = STYLE;
        document.head.appendChild(style);

        var banner = document.createElement('div');
        banner.className = 'demo-banner';
        banner.textContent = 'Демонстрація — дані вигадані';
        document.body.insertBefore(banner, document.body.firstChild);

        document.title = 'ДЕМО — ' + document.title;

        var map = window.sirensMap;
        if (!map) return;

        var Legend = L.Control.extend({
            options: { position: 'topright' },
            onAdd: function () {
                var box = L.DomUtil.create('div', 'demo-legend');
                box.innerHTML = legendHtml();
                L.DomEvent.disableClickPropagation(box);
                L.DomEvent.disableScrollPropagation(box);
                return box;
            }
        });

        new Legend().addTo(map);
        map.invalidateSize();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', mount);
    } else {
        mount();
    }
})();

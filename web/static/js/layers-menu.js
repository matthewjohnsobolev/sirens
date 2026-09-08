/* Панель шарів мапи: чим керує читач і що на мапі означає колір.

   До неї на мапі жило одне око: натиснув — маркери зникли, натиснув ще
   раз — повернулися. Про самі області кнопки не було зовсім, а легенди не
   було ніде: колір на мапі доводилося вгадувати або перевіряти кліком.
   Панель відповідає на обидва питання в одному місці — «що показувати» і
   «що це означає», — і тому легенда стоїть саме тут, під перемикачами, а
   не окремою плашкою в іншому кутку.

   Постав у панелі дві. На великому екрані вона спливає біля своєї кнопки:
   місця вистачає, і мапа поруч лишається живою. На телефоні — приїжджає
   шторкою знизу, з великими рядками й затемненням: вікно біля кнопки в
   кутку накрило б половину країни, а цілитися пальцем у дрібні рядки
   однаково не вийшло б. Вибір постави лишається тут, а не тільки в
   медіазапиті: скрипт однаково мусить знати, куди ставити панель і чи
   тягнеться вона пальцем.

   Кнопку будує map-ui.js — там живе вся стопка контролів і її порядок.
   Сюди вона приходить готовою через mount(). */
(function () {
    'use strict';

    var map = window.sirensMap;
    if (!map || !window.L) return;

    // Межа між вікном і шторкою — та сама ширина, на якій mobile.css
    // перебирає решту мапи: одна сторінка не може ставати мобільною двічі
    // в різних місцях.
    var SHEET = window.matchMedia('(max-width: 600px)');

    // Скільки треба протягнути шторку вниз, щоб вона поїхала закриватися.
    // Менше — і панель зачинялася б від випадкового ковзання пальцем по
    // шапці; більше — і жест довелося б доводити до кінця екрана.
    var DRAG_CLOSE = 64;

    // Панель ставиться відносно контейнера мапи, тож відступ від краю й
    // проміжок до кнопки беруться з тих самих токенів, якими живе стопка
    // контролів: інакше вікно з'їхало б із лінії кнопок на першій же
    // правці системи.
    function token(name, fallback) {
        var raw = getComputedStyle(document.documentElement).getPropertyValue(name);
        var value = parseFloat(raw);
        return isFinite(value) ? value : fallback;
    }

    /* ── Що вмикають ────────────────────────────────────────────────── */

    /* Шар зникає класом на контейнері мапи, а не зняттям шару з Leaflet:
       області й маркери будуються один раз і живуть далі своїм життям —
       з попапами, станами й порядком меж (див. oblasts.js і cities.js).
       Знімати й повертати їх означало б відбудовувати все це щоразу.

       Назва шару каже, що це, підказка — що з нього видно на мапі:
       «Області» самі по собі не пояснюють, що фарбує їх саме тривога. */
    var LAYERS = [
        {
            id: 'oblasts',
            name: 'Області',
            hint: 'Заливка за станом тривоги',
            css: 'oblasts-hidden'
        },
        {
            id: 'markers',
            name: 'Маркери громад',
            hint: markersHint(),
            css: 'markers-hidden'
        }
    ];

    /* Легенда називає стани тими самими словами, що й картки на мапі
       (PILL_VARIANTS у districts.js), лише коротше: у картці слово стоїть
       саме по собі, а тут поруч із позначкою, і повне «Жовтий рівень
       тривоги» тричі поспіль перетворило б список на стовпчик тривог.

       Груп дві, бо мов на мапі теж дві: область говорить плямою, громада —
       крапкою. Один список без поділу змусив би читача самого здогадатися,
       що жовта пляма й жовта крапка — це різні знаки одного стану.

       Штрихування в списку одне — жовте, хоч на мапі воно буває і
       червоним, і подвійним. Пояснити треба сам прийом: смуги замість
       суцільної заливки означають, що тривога не в усіх районах. Далі
       колір смуги читається тим самим ключем, що й колір плями. */
    var LEGEND = [
        {
            layer: 'oblasts',
            caption: 'Області',
            keys: [
                ['area idle', 'Тривоги немає'],
                ['area yellow', 'Жовтий рівень'],
                ['area red', 'Червоний рівень'],
                ['area yellow hatch', 'Тривога не в усіх районах']
            ]
        },
        {
            layer: 'markers',
            caption: 'Маркери громад',
            keys: [
                ['pin pin-idle', 'Тривоги немає'],
                ['pin pin-yellow', 'Жовтий рівень'],
                ['pin pin-shelling', 'Загроза артобстрілу'],
                ['pin pin-red', 'Червоний рівень']
            ]
        }
    ];

    // Скільки громад стоїть на мапі, рахує сам перелік маркерів: цифру,
    // переписану сюди руками, забули б оновити на першому ж новому місті.
    function markersHint() {
        // Перелік оголошений через const у districts.js, тож на window він
        // не лягає — його видно лише як спільну глобальну назву. Сторінку
        // могли віддати й без того файлу: тоді підказки просто не буде.
        var known = typeof DISTRICT_MARKERS !== 'undefined' ? DISTRICT_MARKERS : null;
        var count = known ? known.length : 0;
        if (!count) return '';

        var tail = count % 10;
        var teen = count % 100;
        var word = 'населених пунктів';
        if (teen < 11 || teen > 14) {
            if (tail === 1) word = 'населений пункт';
            else if (tail > 1 && tail < 5) word = 'населені пункти';
        }

        return count + ' ' + word;
    }

    /* ── Розмітка ───────────────────────────────────────────────────── */

    var panel = null;
    var scrim = null;
    var trigger = null;
    var groups = {};
    var open = false;

    function create(tag, className, parent) {
        return L.DomUtil.create(tag, className, parent);
    }

    function layerRow(layer, parent) {
        var row = create('label', 'map-layers__item', parent);

        var text = create('span', 'map-layers__text', row);
        create('span', 'map-layers__name', text).textContent = layer.name;
        if (layer.hint) {
            create('span', 'map-layers__hint', text).textContent = layer.hint;
        }

        // Під намальованим перемикачем лежить справжній чекбокс: стан,
        // клавіатура й скрінрідер дістаються задарма, а сам він ховається
        // тим самим .sr-only, що й заголовок сторінки.
        var input = create('input', 'map-layers__input sr-only', row);
        input.type = 'checkbox';
        input.checked = true;

        var track = create('span', 'map-layers__switch', row);
        track.setAttribute('aria-hidden', 'true');
        create('span', 'map-layers__knob', track);

        L.DomEvent.on(input, 'change', function () {
            apply(layer, input.checked);
        });

        return row;
    }

    function legend(parent) {
        var box = create('div', 'map-layers__legend', parent);
        create('div', 'map-layers__legend-title', box).textContent = 'Позначення';

        for (var i = 0; i < LEGEND.length; i++) {
            var group = LEGEND[i];
            var node = create('div', 'map-layers__group', box);
            create('div', 'map-layers__group-name', node).textContent = group.caption;

            for (var k = 0; k < group.keys.length; k++) {
                var key = create('div', 'map-layers__key', node);
                var modifiers = group.keys[k][0].split(' ');
                var mark = 'map-layers__swatch';
                for (var m = 0; m < modifiers.length; m++) {
                    mark += ' map-layers__swatch--' + modifiers[m];
                }

                create('span', mark, key).setAttribute('aria-hidden', 'true');
                create('span', 'map-layers__key-name', key).textContent = group.keys[k][1];
            }

            groups[group.layer] = node;
        }

        return box;
    }

    function build() {
        var host = map.getContainer();

        scrim = create('div', 'map-layers-scrim', host);
        scrim.setAttribute('aria-hidden', 'true');

        panel = create('div', 'map-layers', host);
        panel.id = 'map-layers';
        panel.setAttribute('role', 'dialog');
        panel.setAttribute('aria-label', 'Шари мапи');

        // Панель забирає фокус на себе, коли відкривається: інакше
        // клавіатура лишалася б на кнопці, а стрілка й таб гортали б те,
        // що під панеллю. Своєї рамки фокуса вона не малює — рамку носять
        // перемикачі всередині.
        panel.tabIndex = -1;

        var handle = create('div', 'map-layers__handle', panel);
        create('div', 'map-layers__grip', handle).setAttribute('aria-hidden', 'true');
        create('div', 'map-layers__title', handle).textContent = 'Шари';

        var body = create('div', 'map-layers__body', panel);
        for (var i = 0; i < LAYERS.length; i++) layerRow(LAYERS[i], body);
        legend(body);

        // Мапа під панеллю не має ні їздити, ні зумитися від дотику по
        // ній. Клік при цьому й далі спливає до документа — саме ним
        // ловиться «натиснули повз».
        L.DomEvent.disableClickPropagation(panel);
        L.DomEvent.disableScrollPropagation(panel);
        L.DomEvent.disableClickPropagation(scrim);
        L.DomEvent.disableScrollPropagation(scrim);
        L.DomEvent.on(scrim, 'click', close);

        drag(handle);
        pose();
        syncLegend();
    }

    /* ── Стан шарів ─────────────────────────────────────────────────── */

    function apply(layer, visible) {
        L.DomUtil[visible ? 'removeClass' : 'addClass'](map.getContainer(), layer.css);

        // Попап відкритої області лишався б висіти над мапою, з якої щойно
        // прибрали саму область.
        if (!visible) map.closePopup();

        syncLegend();

        if (window.track) window.track('layer_toggle', {
            layer_name: layer.id,
            layer_visible: String(visible)
        });
    }

    function shown(layer) {
        return !L.DomUtil.hasClass(map.getContainer(), layer.css);
    }

    // Легенда говорить лише про те, що зараз намальовано: пояснювати
    // колір, якого на мапі немає, — це вчити розрізняти невидиме.
    function syncLegend() {
        var any = false;

        for (var i = 0; i < LAYERS.length; i++) {
            var visible = shown(LAYERS[i]);
            var group = groups[LAYERS[i].id];
            if (group) group.hidden = !visible;
            if (visible) any = true;
        }

        var box = panel.querySelector('.map-layers__legend');
        if (box) box.hidden = !any;
    }

    /* ── Постава й місце ────────────────────────────────────────────── */

    function sheet() {
        return SHEET.matches;
    }

    function pose() {
        L.DomUtil[sheet() ? 'addClass' : 'removeClass'](panel, 'map-layers--sheet');
        L.DomUtil[sheet() ? 'removeClass' : 'addClass'](panel, 'map-layers--popover');

        // Затемнення належить шторці, а не панелі взагалі: якщо екран
        // поширшав, поки панель відкрита, гасити мапу вже нема за чим.
        if (open) L.DomUtil[sheet() ? 'addClass' : 'removeClass'](scrim, 'is-open');

        place();
    }

    /* Вікно стає праворуч від своєї кнопки й на її висоті — так, щоб
       зв'язок читався без стрілок і хвостиків. Верх при цьому не
       опускається нижче, ніж дозволяє мапа: висока панель біля нижньої
       кнопки поїхала б за край екрана, тож вона підтягується вгору й
       далі гортається всередині.

       Шторці рахувати нічого: її тримають три краї екрана, і будь-яке
       вціліле inline-значення з десктопної постави тут лише заважало б. */
    function place() {
        if (sheet() || !trigger) {
            panel.style.top = '';
            panel.style.left = '';
            return;
        }

        var host = map.getContainer().getBoundingClientRect();
        var button = trigger.getBoundingClientRect();
        var inset = token('--map-inset', 12);
        var gap = token('--gap', 8);

        var limit = host.height - inset - panel.offsetHeight;
        var top = Math.min(button.top - host.top, Math.max(inset, limit));

        panel.style.top = Math.max(inset, top) + 'px';
        panel.style.left = (button.right - host.left + gap) + 'px';
    }

    /* ── Відкриття ──────────────────────────────────────────────────── */

    function show() {
        if (open) return;
        open = true;

        // Місце рахується до показу: панель уже має розміри — закрита вона
        // прихована видимістю, а не викинута з розкладки.
        place();

        L.DomUtil.addClass(panel, 'is-open');
        if (sheet()) L.DomUtil.addClass(scrim, 'is-open');
        if (trigger) trigger.setAttribute('aria-expanded', 'true');

        panel.focus({ preventScroll: true });

        if (window.track) window.track('layers_menu_open', {
            layout: sheet() ? 'sheet' : 'popover'
        });
    }

    function close() {
        if (!open) return;
        open = false;

        L.DomUtil.removeClass(panel, 'is-open');
        L.DomUtil.removeClass(scrim, 'is-open');
        if (trigger) trigger.setAttribute('aria-expanded', 'false');

        // Фокус повертається на кнопку лише тоді, коли він лишався в
        // панелі: інакше закриття клацанням по мапі відбирало б фокус у
        // того, з ким читач саме працює.
        if (trigger && panel.contains(document.activeElement)) {
            trigger.focus({ preventScroll: true });
        }
    }

    function toggle() {
        if (open) close();
        else show();
    }

    /* ── Жест ───────────────────────────────────────────────────────── */

    /* Шторку закривають не лише кнопкою: її тягнуть униз за шапку — так
       само, як будь-яку шторку в телефоні. Тягнеться саме шапка, а не вся
       панель: усередині гортається список, і два жести на одному полі
       заважали б один одному.

       Поки палець на екрані, перехід вимкнено — панель мусить іти рівно
       за пальцем. На відпусканні перехід повертається, і панель або їде
       на місце, або доїжджає вниз уже сама. */
    function drag(handle) {
        if (!window.PointerEvent) return;

        var start = null;
        var shift = 0;

        L.DomEvent.on(handle, 'pointerdown', function (event) {
            if (!sheet() || !open || event.button) return;
            start = event.clientY;
            shift = 0;
            panel.style.transition = 'none';
            if (handle.setPointerCapture) handle.setPointerCapture(event.pointerId);
        });

        L.DomEvent.on(handle, 'pointermove', function (event) {
            if (start === null) return;

            // Тягнеться шторка тільки вниз: угору їй нікуди, там край
            // екрана, а гумовий хід з нього лише збивав би з пантелику.
            shift = Math.max(0, event.clientY - start);
            panel.style.transform = 'translateY(' + shift + 'px)';
        });

        function release() {
            if (start === null) return;
            start = null;

            // Перехід повертається до того, як зникне зсув: браузер має
            // побачити панель зміщеною й уже з переходом, інакше вона
            // стрибне на місце без руху.
            panel.style.transition = '';
            void panel.offsetHeight;
            panel.style.transform = '';

            if (shift > DRAG_CLOSE) close();
        }

        L.DomEvent.on(handle, 'pointerup', release);
        L.DomEvent.on(handle, 'pointercancel', release);
    }

    /* ── Зв'язок зі світом ──────────────────────────────────────────── */

    // Натиснули повз панель — вона зачиняється. Кнопка сюди не входить:
    // її власний обробник уже перемкнув панель, і закриття слідом за ним
    // відкривало б її назавжди одним кліком.
    L.DomEvent.on(document, 'click', function (event) {
        if (!open) return;
        var target = event.target;
        if (panel.contains(target) || (trigger && trigger.contains(target))) return;
        close();
    });

    L.DomEvent.on(document, 'keydown', function (event) {
        if (open && event.key === 'Escape') close();
    });

    // Поворот телефона чи зміна розміру вікна міняє поставу під панеллю:
    // вікно, що лишилося вікном на вузькому екрані, стало б смугою
    // посеред мапи.
    if (SHEET.addEventListener) SHEET.addEventListener('change', pose);
    else if (SHEET.addListener) SHEET.addListener(pose);

    L.DomEvent.on(window, 'resize', function () {
        if (open) place();
    });

    /* ── Вхід ───────────────────────────────────────────────────────── */

    window.SirensLayersMenu = {
        mount: function (button) {
            trigger = button;
            button.setAttribute('aria-expanded', 'false');
            button.setAttribute('aria-controls', 'map-layers');
            if (!panel) build();
            L.DomEvent.on(button, 'click', toggle);
        }
    };
})();

/* Навігаційні кнопки, свіжість даних і стан сервісу на мапі.
   Стопка зуму (+/−) живе у верхньому лівому куті. Плитка часу та оновлення даних
   і кнопка повідомлення про збій стоять у нижньому лівому куті в єдиній лінії. */
(function () {
    'use strict';

    var map = window.sirensMap;
    if (!map || !window.L) return;

    // Статус-сторінка кешує свій JSON на 60 секунд, тож частіше питати
    // нема сенсу: відповідь усе одно буде та сама.
    var STATUS_URL = 'https://status.sirens.live/status.json';
    var STATUS_PAGE = 'https://status.sirens.live';
    var POLL_MS = 60000;

    // Оберт іконки оновлення триває стільки ж, скільки однойменна анімація
    // в map-ui.css: кнопку гасимо лише на цілому колі, тож код мусить
    // знати його тривалість.
    var SPIN_MS = 900;

    // Читач, який просив менше руху, оберту не бачить — тоді й доганяти
    // ціле коло нема чого.
    var calm = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)');

    // Відставання даних на бекенді вважається застиганням після 20 хвилин
    var STALE_MS = 20 * 60 * 1000;

    var isClientOnline = typeof navigator !== 'undefined' ? navigator.onLine !== false : true;
    var showRestoredUntil = 0;
    var restoredTimer = null;
    var statusData = null;

    // indicator зі status.json → стан крапки, слово для скрінрідера й те,
    // чи має сервіс говорити вголос. Крапка каже стан кольором, тож слово
    // читається лише з підказки — але без нього доступна назва лишила б
    // стан невідомим. Слова ті самі, що в STATUS_WORDS на статус-сторінці.
    var STATES = {
        none: { state: 'ok', word: 'Все працює', loud: false },
        minor: { state: 'minor', word: 'Часткові збої', loud: false },
        major: { state: 'down', word: 'Не працює', loud: true },
        critical: { state: 'down', word: 'Не працює', loud: true },
        maintenance: { state: 'mnt', word: 'Планові роботи', loud: false },
        unknown: { state: 'nodata', word: 'Немає даних', loud: true }
    };
    var UNKNOWN = STATES.unknown;

    // Час завжди київський: сервіс говорить про Україну, тож «13:54» має
    // означати те саме і для читача з Варшави.
    var kyivTime = new Intl.DateTimeFormat('uk-UA', {
        timeZone: 'Europe/Kyiv',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false
    });

    var tile = null;
    var chip = null;
    var currentInfo = UNKNOWN;

    function updateLabel(at) {
        if (!tile) return;
        if (at === undefined) {
            var moment = window.SirensThreats ? SirensThreats.at() : null;
            at = moment ? kyivTime.format(moment) : null;
        }

        var text = 'Оновити дані';
        if (at) text = 'Дані станом на ' + at + '. Натисніть, щоб оновити';
        tile.title = text;
        tile.setAttribute('aria-label', text);
    }

    // Елемент будується один раз і запам'ятовується: setPosition знімає
    // контрол і додає знову, тож інакше плитка щоразу поверталася б з
    // чистим полем і без обробників.
    function control(position, build) {
        var element = null;

        var Control = L.Control.extend({
            options: { position: position },
            onAdd: function () {
                if (!element) {
                    element = build();
                    L.DomEvent.disableClickPropagation(element);
                    L.DomEvent.disableScrollPropagation(element);
                }

                return element;
            }
        });

        return new Control();
    }

    // Назва кнопки потрібна і в тултипі, і скрінрідеру: іконка сама по
    // собі не називає нічого.
    function label(element, text) {
        element.title = text;
        element.setAttribute('aria-label', text);
    }

    function icon(parent, modifier) {
        var element = L.DomUtil.create('span', 'map-ctl-icon map-ctl-icon--' + modifier, parent);
        element.setAttribute('aria-hidden', 'true');
        return element;
    }

    // Кнопки зума Leaflet будує сам і кладе цей рядок усередину як HTML.
    // Плюс і мінус — такі самі іконки-маски, як в інших кнопок: уся стопка
    // малюється однаково й не залежить від того, чи приїхав шрифт.
    function iconMarkup(modifier) {
        return '<span class="map-ctl-icon map-ctl-icon--' + modifier + '" aria-hidden="true"></span>';
    }

    // Коротка анімація вмикається класом, а знімає його кінець самої
    // анімації: тривалість лишається в CSS і не дублюється таймером. Клас
    // спершу знімається, тож повторний виклик починає рух з нуля — інакше
    // другий натиск поспіль не відгукнувся б нічим.
    function flash(element, name) {
        // Під reduce анімації немає — а тоді нема й класу, який нікому було
        // б зняти: без animationend він лишався б на елементі назавжди.
        if (calm && calm.matches) return;

        if (!element.sirensFlash) {
            element.sirensFlash = {};

            // Анімація може бути на дитині — іконці всередині кнопки. Подія
            // спливає, тож слухати досить сам елемент із класом.
            L.DomEvent.on(element, 'animationend', function () {
                for (var cls in element.sirensFlash) {
                    if (element.sirensFlash[cls]) {
                        L.DomUtil.removeClass(element, cls);
                        element.sirensFlash[cls] = false;
                    }
                }
            });
        }

        L.DomUtil.removeClass(element, name);
        element.sirensFlash[name] = true;

        // Читання розкладки між зняттям і поверненням класу — те, що змушує
        // браузер побачити зміну й запустити анімацію заново.
        void element.offsetWidth;
        L.DomUtil.addClass(element, name);
    }

    // Скільки лишилося до кінця поточного оберту. Зупиняти іконку раніше
    // не можна: відповідь із кешу приходить за десяток мілісекунд, і
    // стрілка застигала б боком.
    function spinTail(since) {
        if (calm && calm.matches) return 0;
        var elapsed = Date.now() - since;
        var rem = elapsed % SPIN_MS;
        return (rem === 0 && elapsed > 0) ? 0 : SPIN_MS - rem;
    }


    // Єдина плитка з текстом: свіжість даних та дія оновлення.
    // Кругла стрілка запускає перезавантаження даних, а час показує момент останньої успішної відповіді /api.
    function timeTile() {
        var button = L.DomUtil.create('button', 'map-ctl map-ctl--time');
        button.type = 'button';

        icon(button, 'refresh');

        var stamp = L.DomUtil.create('span', 'map-sync-time', button);

        tile = button;

        function say() {
            var moment = window.SirensThreats ? SirensThreats.at() : null;
            var at = moment ? kyivTime.format(moment) : null;

            // Поки сервер не відповів жодного разу, часу немає — і прочерк
            // чесніший за чужий час.
            var text = at || '--:--';
            updateLabel(at);

            // Відповіді приходять щокілька секунд, а хвилина на плитці
            // міняється рідше: проявляємо лише справжню зміну, інакше час
            // блимав би в такт опитувань, нічого не кажучи.
            if (stamp.textContent === text) return;
            stamp.textContent = text;
            flash(stamp, 'is-fresh');
        }

        L.DomEvent.on(button, 'click', function (e) {
            L.DomEvent.stop(e);
            if (button.getAttribute('aria-busy') === 'true') return;
            button.setAttribute('aria-busy', 'true');

            var since = Date.now();

            function done() {
                setTimeout(function () {
                    button.removeAttribute('aria-busy');
                }, spinTail(since));
            }

            if (window.SirensThreats && window.SirensThreats.load) {
                SirensThreats.load(true).then(done, done);
            } else {
                done();
            }
        });

        if (window.SirensThreats) {
            SirensThreats.onPaint(say);
        }
        say();

        return button;
    }

    // Окрема кнопка повідомлення про збій поруч із плиткою часу.
    function issueTile() {
        var link = L.DomUtil.create('a', 'map-ctl map-ctl--issue');
        link.href = '/issue';
        label(link, 'Повідомити про збій');
        var flag = L.DomUtil.create('span', 'map-ctl-icon map-ctl-icon--flag material-symbols-rounded', link);
        flag.setAttribute('aria-hidden', 'true');
        flag.textContent = 'flag';
        return link;
    }

    // Чіп не стоїть у кутовій стопці, тож і не є контролом Leaflet: його
    // тримає сам контейнер мапи. Обгортка з aria-live лишається в DOM
    // назавжди — порожній регіон має існувати заздалегідь, інакше поява
    // тексту в ньому не озвучиться.
    var chipHideTimer = null;

    function statusChip() {
        var live = L.DomUtil.create('div', 'map-chip-live', map.getContainer());
        live.setAttribute('aria-live', 'polite');

        var link = L.DomUtil.create('a', 'map-chip', live);
        link.rel = 'noopener';
        link.hidden = true;

        var dot = L.DomUtil.create('span', 'map-chip-dot', link);
        dot.setAttribute('aria-hidden', 'true');

        var text = L.DomUtil.create('span', 'map-chip-text', link);

        L.DomEvent.disableClickPropagation(link);
        L.DomEvent.disableScrollPropagation(link);

        // Якщо зв'язку немає (offline) або він щойно відновився (ok) — не пускаємо
        // на зовнішню сторінку статусу, яка без інтернету однаково не завантажиться.
        // Клік натомість ініціює повторну перевірку зв'язку.
        L.DomEvent.on(link, 'click', function (e) {
            if (link.dataset.state === 'offline' || link.dataset.state === 'ok') {
                L.DomEvent.stop(e);
                if (link.dataset.state === 'offline') {
                    poll();
                    if (window.SirensThreats && window.SirensThreats.load) {
                        SirensThreats.load(true).catch(function () {});
                    }
                }
            }
        });

        chip = { root: link, text: text, said: null };
    }

    function showChip(alarm) {
        if (!chip) return;
        if (chipHideTimer) {
            clearTimeout(chipHideTimer);
            chipHideTimer = null;
        }

        chip.root.dataset.state = alarm.state;
        chip.text.textContent = alarm.text;

        if (alarm.state === 'offline' || alarm.state === 'ok') {
            chip.root.removeAttribute('href');
            chip.root.setAttribute('role', 'status');
        } else {
            chip.root.href = STATUS_PAGE;
            chip.root.setAttribute('role', 'link');
        }

        if (chip.root.hidden) {
            chip.root.hidden = false;
            L.DomUtil.removeClass(chip.root, 'is-leaving');
            L.DomUtil.removeClass(chip.root, 'is-visible');
            void chip.root.offsetWidth;
            L.DomUtil.addClass(chip.root, 'is-visible');
        } else {
            L.DomUtil.removeClass(chip.root, 'is-leaving');
            L.DomUtil.addClass(chip.root, 'is-visible');
        }
    }

    function hideChip() {
        if (!chip || chip.root.hidden) return;
        if (chip.root.classList.contains('is-leaving')) return;

        if (calm && calm.matches) {
            chip.root.hidden = true;
            L.DomUtil.removeClass(chip.root, 'is-visible');
            L.DomUtil.removeClass(chip.root, 'is-leaving');
            chip.text.textContent = '';
            chip.said = null;
            return;
        }

        L.DomUtil.removeClass(chip.root, 'is-visible');
        L.DomUtil.addClass(chip.root, 'is-leaving');

        if (chipHideTimer) clearTimeout(chipHideTimer);
        chipHideTimer = setTimeout(function () {
            chipHideTimer = null;
            if (chip && chip.root.classList.contains('is-leaving')) {
                chip.root.hidden = true;
                L.DomUtil.removeClass(chip.root, 'is-leaving');
                chip.text.textContent = '';
                chip.said = null;
            }
        }, 250);
    }

    function render(info, alarm) {
        currentInfo = info;
        if (tile) {
            tile.dataset.state = info.state;

            // Тултип називає об'єкт, а не переказує стан: під указівником
            // читач і так бачить крапку, а переказ щохвилини змінював би
            // підказку тієї самої кнопки. Скрінрідеру кольору не видно,
            // тож стан лишається в доступній назві.
            updateLabel();
        }

        if (!chip) return;

        // Та сама новина щохвилини — не новина: DOM чіпаємо лише коли
        // текст справді змінився, інакше aria-live озвучував би її знову.
        var said = alarm ? alarm.state + '|' + alarm.text : null;
        if (said === chip.said && !chip.root.hidden && !chip.root.classList.contains('is-leaving')) return;
        chip.said = said;

        if (!alarm) {
            hideChip();
            return;
        }

        showChip(alarm);
    }

    function setClientOnline(online) {
        if (!online) {
            var wasOnline = isClientOnline;
            var hadRestored = showRestoredUntil > 0;
            isClientOnline = false;
            showRestoredUntil = 0;
            if (restoredTimer) {
                clearTimeout(restoredTimer);
                restoredTimer = null;
            }
            if (wasOnline || hadRestored) {
                updateState();
            }
        } else {
            if (!isClientOnline) {
                isClientOnline = true;
                showRestoredUntil = Date.now() + 4000;
                if (restoredTimer) clearTimeout(restoredTimer);
                restoredTimer = setTimeout(function () {
                    restoredTimer = null;
                    updateState();
                }, 4000);
                updateState();
            }
        }
    }

    // Каскад статусних плашок:
    // 1. Пріоритет 1 (Проблема з інтернетом у клієнта): НЕМАЄ ЗВ'ЯЗКУ / ЗВ'ЯЗОК ВІДНОВЛЕНО
    // 2. Пріоритет 2 (Застигання даних на бекенді): ДАНІ НЕ ОНОВЛЮЮТЬСЯ
    function alarmFor(info) {
        if (!isClientOnline) {
            return { state: 'offline', text: 'НЕМАЄ ЗВ\'ЯЗКУ' };
        }

        if (Date.now() < showRestoredUntil) {
            return { state: 'ok', text: 'ЗВ\'ЯЗОК ВІДНОВЛЕНО' };
        }

        var syncIso = telemetryAt(statusData);
        if (isStale(syncIso)) {
            return { state: 'down', text: 'ДАНІ НЕ ОНОВЛЮЮТЬСЯ' };
        }

        if (info.loud) {
            var headline = statusData && statusData.status ? statusData.status.headline : null;
            return { state: info.state, text: headline || info.word };
        }

        return null;
    }

    function isStale(iso) {
        if (!iso) return false;
        var date = new Date(iso);
        return !isNaN(date.getTime()) && Date.now() - date.getTime() > STALE_MS;
    }

    // Час пишеться, коли бот востаннє клав телеметрію в KV. Саме він і
    // застигає, якщо збір даних став.
    function telemetryAt(data) {
        if (!data || !data.telemetry) return null;
        return data.telemetry.synced_at || data.telemetry.last_source_sync_at || data.telemetry.updated_at || null;
    }

    function updateState() {
        var indicator = statusData && statusData.status ? statusData.status.indicator : null;
        var info = STATES[indicator] || UNKNOWN;
        render(info, alarmFor(info));
    }

    var POLL_TIMEOUT_MS = 6000;

    function poll() {
        if (typeof navigator !== 'undefined' && navigator.onLine === false) {
            setClientOnline(false);
            return;
        }

        var controller = window.AbortController ? new AbortController() : null;
        var timeoutId = controller
            ? setTimeout(function () { controller.abort(); }, POLL_TIMEOUT_MS)
            : null;

        fetch(STATUS_URL, {
            cache: 'no-store',
            signal: controller ? controller.signal : undefined
        })
            .then(function (response) {
                if (!response.ok) throw new Error('status ' + response.status);
                return response.json();
            })
            .then(function (data) {
                statusData = data;
                setClientOnline(true);
                updateState();
            })
            .catch(function (err) {
                if (!navigator.onLine || (err && (err.name === 'TypeError' || err.name === 'AbortError' || String(err).indexOf('fetch') !== -1 || String(err).indexOf('NetworkError') !== -1 || String(err).indexOf('Load failed') !== -1))) {
                    setClientOnline(false);
                } else {
                    updateState();
                }
            })
            .finally(function () {
                if (timeoutId) clearTimeout(timeoutId);
            });
    }

    // Натиск на «+» чи «−» відгукується поштовхом іконки — рівно поки їде
    // мапа. Вимкнена кнопка мовчить: далі нікуди, і рух казав би, що щось
    // сталося.
    function respondToPress(button) {
        L.DomEvent.on(button, 'click', function () {
            if (L.DomUtil.hasClass(button, 'leaflet-disabled')) return;
            flash(button, 'is-pressed');
        });
    }

    var zoomControl = L.control.zoom({
        position: 'topleft',
        zoomInText: iconMarkup('zoom-in'),
        zoomInTitle: 'Наблизити',
        zoomOutText: iconMarkup('zoom-out'),
        zoomOutTitle: 'Віддалити'
    }).addTo(map);

    var zoomContainer = zoomControl.getContainer();
    if (zoomContainer) {
        var zoomButtons = zoomContainer.querySelectorAll('a');
        for (var i = 0; i < zoomButtons.length; i++) respondToPress(zoomButtons[i]);
    }

    // Плитка часу та оновлення і кнопка повідомлення про збій стоять у нижньому лівому куті.
    // issueTile додається першою, щоб timeTile стала перед нею (Leaflet додає
    // bottom-контроли через insertBefore firstChild).
    control('bottomleft', issueTile).addTo(map);
    control('bottomleft', timeTile).addTo(map);

    statusChip();

    // Поки перша відповідь не прийшла: якщо браузер уже знає про відсутність інтернету —
    // одразу показуємо плашку; інакше мовчки, щоб не кричати про аварію без даних.
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
        isClientOnline = false;
        render(UNKNOWN, alarmFor(UNKNOWN));
    } else {
        render(UNKNOWN, null);
    }

    poll();
    setInterval(poll, POLL_MS);

    // Вкладку могли лишити відкритою на ніч: щойно на неї повернулись,
    // плашка перевіряє стан, не чекаючи наступного такту.
    document.addEventListener('visibilitychange', function () {
        if (!document.hidden) {
            if (typeof navigator !== 'undefined' && navigator.onLine === false) {
                setClientOnline(false);
            } else {
                poll();
            }
        }
    });

    // Навігація в історії (наприклад, повернення назад після помилки завантаження
    // зовнішньої сторінки статусу або відновлення з bfcache).
    window.addEventListener('pageshow', function () {
        if (typeof navigator !== 'undefined' && navigator.onLine === false) {
            setClientOnline(false);
        } else {
            poll();
        }
    });

    // Подія 'online' свідчить про зміну інтерфейсу, але не гарантує зв'язок.
    // Замість сліпого відновлення робимо poll(), який перевірить реальний статус.
    window.addEventListener('online', function () {
        if (typeof navigator !== 'undefined' && navigator.onLine === false) {
            setClientOnline(false);
        } else {
            poll();
        }
    });
    window.addEventListener('offline', function () { setClientOnline(false); });

    if (window.SirensThreats) {
        window.SirensThreats.onSuccess(function () {
            if (typeof navigator !== 'undefined' && navigator.onLine === false) {
                setClientOnline(false);
            } else if (!isClientOnline) {
                poll();
            }
        });
        window.SirensThreats.onError(function (err) {
            if (!navigator.onLine || (err && (err.name === 'TypeError' || err.name === 'AbortError' || String(err).indexOf('fetch') !== -1 || String(err).indexOf('NetworkError') !== -1 || String(err).indexOf('Load failed') !== -1))) {
                setClientOnline(false);
            }
        });
    }
})();

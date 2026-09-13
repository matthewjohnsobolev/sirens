/* Відповідь /api в одному місці.
   Мапу малюють два файли — області й маркери міст, — і донедавна кожен
   ходив на сервер сам. Дві відповіді на одну мапу означали дві правди й
   два різні «оновлено о», тож запит тепер один, а результат спільний.

   Звідси ж береться час, який показує плитка оновлення: момент, коли
   сервер востаннє відповів, а не коли востаннє була тривога.

   І звідси ж мапа оновлюється сама. Тривогу оголошують раз — вкладку з
   мапою лишають відкритою на годину, тож дані мають приходити без
   перезавантаження. Сторінка при цьому не перебудовується: області й
   маркери вже побудовані й лише перефарбовуються, тож зум, положення й
   відкритий попап лишаються там, де їх лишив читач. */
const SirensThreats = (function () {
    'use strict';

    const TIMEOUT_MS = 15000;

    let data = null;
    let at = null;
    let pending = null;
    const painters = [];
    const successListeners = [];
    const errorListeners = [];

    function paint() {
        for (const painter of painters) painter(data);
    }

    function notifySuccess() {
        for (const fn of successListeners) {
            try { fn(); } catch (_) {}
        }
    }

    function notifyError(err) {
        for (const fn of errorListeners) {
            try { fn(err); } catch (_) {}
        }
    }

    return {
        // Попапи читають дані при відкритті, а не при створенні: після
        // оновлення картка розповідає нове, і перепідв'язувати її не треба.
        get() {
            return data;
        },

        // Час останньої успішної відповіді. Поки її не було — null:
        // показувати чужий час гірше, ніж не показувати жодного.
        at() {
            return at;
        },

        // Малювальник викликається на кожній відповіді — і на тій, що вже
        // прийшла до його реєстрації. Інакше порядок завантаження скриптів
        // вирішував би, чи намалюється мапа.
        onPaint(painter) {
            painters.push(painter);
            if (data) painter(data);
        },

        onSuccess(fn) {
            successListeners.push(fn);
        },

        onError(fn) {
            errorListeners.push(fn);
        },

        // Поки один запит іде, решта чекають на ту саму обіцянку: кнопку
        // можна тиснути скільки завгодно, сервер побачить один запит.
        // force вимикає кеш браузера — примусове оновлення на те й
        // примусове, щоб не отримати у відповідь власну хвилинну копію.
        //
        // Запит, який завис, обривається за TIMEOUT_MS: інакше одна
        // відповідь, що так і не прийшла, замкнула б pending назавжди — і
        // мапа більше не оновилася б ані сама, ані з кнопки.
        load(force) {
            if (pending) return pending;

            const controller = window.AbortController ? new AbortController() : null;
            const cutoff = controller
                ? setTimeout(() => controller.abort(), TIMEOUT_MS)
                : null;

            pending = fetch('/api', {
                cache: force ? 'no-store' : 'no-cache',
                signal: controller ? controller.signal : undefined
            })
                .then(response => {
                    if (!response.ok) throw new Error('api ' + response.status);
                    return response.json();
                })
                .then(fresh => {
                    data = fresh;
                    at = new Date();
                    paint();
                    notifySuccess();
                    return fresh;
                })
                .catch(err => {
                    notifyError(err);
                    throw err;
                })
                .finally(() => {
                    clearTimeout(cutoff);
                    pending = null;
                });

            return pending;
        }
    };
})();

window.SirensThreats = SirensThreats;

(function () {
    'use strict';

    // /api віддає Cache-Control: max-age=2, тож такт частіший за пару
    // секунд однаково впирався б у той самий кеш. П'ятнадцять — компроміс
    // між «майже одразу» і чергою запитів від кожної відкритої вкладки.
    const ACTIVE_POLL_MS = 15000;

    // У фоні питаємо рідше — раз на 90 секунд: це заощаджує батарею та трафік,
    // але не дає даним застигнути, щоб після 10–15 хвилин простою не з'являлася
    // помилкова плашка «Дані не оновлюються».
    const BACKGROUND_POLL_MS = 90000;

    let timer = null;

    // Провал не показуємо: час на плитці просто не зрушить, і це вже
    // відповідь. Наступний такт спробує ще раз.
    function poll() {
        SirensThreats.load().catch(() => {});
    }

    function schedule(delay) {
        if (timer) clearTimeout(timer);
        const ms = delay !== undefined
            ? delay
            : (document.hidden ? BACKGROUND_POLL_MS : ACTIVE_POLL_MS);
        timer = setTimeout(tick, ms);
    }

    function tick() {
        poll();
        schedule();
    }

    // Позачергові приводи — повернення на вкладку, зміна видимості й повернення мережі.
    // Якщо минуло більше за цільовий такт — питаємо одразу; інакше плануємо на залишок.
    function onStateChange() {
        const at = SirensThreats.at();
        const elapsed = at ? Date.now() - at.getTime() : Infinity;
        const targetInterval = document.hidden ? BACKGROUND_POLL_MS : ACTIVE_POLL_MS;

        if (elapsed >= targetInterval) {
            poll();
            schedule(targetInterval);
        } else {
            schedule(targetInterval - elapsed);
        }
    }

    schedule(ACTIVE_POLL_MS);

    document.addEventListener('visibilitychange', onStateChange);

    // Зв'язок міг зникнути надовго — тоді дані застаріли рівно на весь час
    // без мережі, і чекати такту нема чого.
    window.addEventListener('online', onStateChange);
})();

SirensThreats.load().catch(error => { console.error('Error fetching data:', error); });

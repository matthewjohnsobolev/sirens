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

    function paint() {
        for (const painter of painters) painter(data);
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
                cache: force ? 'no-store' : 'default',
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
                    return fresh;
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
    const POLL_MS = 15000;

    // Провал не показуємо: час на плитці просто не зрушить, і це вже
    // відповідь. Наступний такт спробує ще раз.
    function poll() {
        SirensThreats.load().catch(() => {});
    }

    // Позачергові приводи — повернення на вкладку і повернення мережі —
    // трапляються пачками: між двома вікнами перемикаються по кілька разів
    // поспіль. Тож питаємо лише те, чого ще не питали цього такту.
    function pollIfDue() {
        const at = SirensThreats.at();
        if (!at || Date.now() - at.getTime() >= POLL_MS) poll();
    }

    // У фоні не питаємо: невидима вкладка нікому не показує нову
    // відповідь, а на телефоні за неї платить батарея. Зате щойно на
    // вкладку повернулись — питаємо одразу, не чекаючи такту: побачити на
    // екрані годинну правду гірше, ніж не побачити жодної.
    setInterval(() => { if (!document.hidden) poll(); }, POLL_MS);

    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) pollIfDue();
    });

    // Зв'язок міг зникнути надовго — тоді дані застаріли рівно на весь час
    // без мережі, і чекати такту нема чого.
    window.addEventListener('online', pollIfDue);
})();

SirensThreats.load().catch(error => { console.error('Error fetching data:', error); });

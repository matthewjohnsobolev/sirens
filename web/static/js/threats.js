/* Відповідь /api в одному місці.
   Мапу малюють два файли — області й маркери міст, — і донедавна кожен
   ходив на сервер сам. Дві відповіді на одну мапу означали дві правди й
   два різні «оновлено о», тож запит тепер один, а результат спільний.

   Звідси ж береться час, який показує плитка оновлення: момент, коли
   сервер востаннє відповів, а не коли востаннє була тривога. */
const SirensThreats = (function () {
    'use strict';

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
        load(force) {
            if (pending) return pending;

            pending = fetch('/api', force ? { cache: 'no-store' } : undefined)
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
                .finally(() => { pending = null; });

            return pending;
        }
    };
})();

window.SirensThreats = SirensThreats;

SirensThreats.load().catch(error => { console.error('Error fetching data:', error); });

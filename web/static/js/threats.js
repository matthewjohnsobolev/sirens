
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
        
        
        get() {
            return data;
        },

        
        
        at() {
            return at;
        },

        
        
        
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

    
    
    
    const ACTIVE_POLL_MS = 15000;

    
    
    
    const BACKGROUND_POLL_MS = 90000;

    let timer = null;

    
    
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

    
    
    window.addEventListener('online', onStateChange);
})();

SirensThreats.load().catch(error => { console.error('Error fetching data:', error); });

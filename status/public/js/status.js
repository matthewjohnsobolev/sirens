(function() {
  'use strict';

  // Сторінка оновлюється сама, але не перезавантажується: з відповіді
  // беремо саму картку й міняємо її на місці. Тож прокрутка, фокус і
  // масштаб лишаються там, де їх лишив читач, — рівно як на мапі, де те
  // саме робить SirensThreats.
  const REFRESH_MS = 60000;

  // Такт частий навмисне: він лише дивиться на годинник, а справжній
  // запит іде раз на REFRESH_MS. Дрібний крок потрібен, щоб оновлення не
  // спізнювалось на пів такту після повернення на вкладку.
  const TICK_MS = 5000;

  // Поки читач тримає тултип, підмінити під ним смужки не можна: він
  // показує годину, якої в новому DOM уже не буде. Чекаємо, поки відпустить.
  const BUSY_MS = 10000;

  // Запит, що завис, не має гасити оновлення назавжди: без цієї межі одна
  // відповідь, яка так і не прийшла, лишила б сторінку застиглою до
  // перезавантаження — рівно те, від чого ми й пішли.
  const TIMEOUT_MS = 15000;

  let tip = null;
  let hideTimer = null;
  let currentBar = null;
  let activeTouchBars = null;
  let activePointerId = null;

  function ensureTip() {
    if (tip && tip.parentElement) return tip;
    if (!tip) {
      tip = document.createElement('div');
      tip.className = 'tip';
      tip.setAttribute('role', 'tooltip');
      tip.hidden = true;
      tip.innerHTML = '<span class="tip-time"></span><span class="tip-state"><span class="tip-dot" data-state="ok"></span><span class="tip-text"></span></span>';
    }
    const root = document.body || document.documentElement;
    if (root && tip.parentElement !== root) {
      root.appendChild(tip);
    }
    return tip;
  }

  const FALLBACK_METRICS = { arrow: 6, gap: 5, lift: 3, radius: 6 };
  const reducedMotion = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
  let tipMetricsCache = null;

  // --tip-arrow / --tip-gap / --bar-lift живуть у CSS і однакові на всіх
  // екранах, тому відступ до вістря вказівника не залежить від пристрою.
  function tipMetrics() {
    if (tipMetricsCache) return tipMetricsCache;
    const styles = window.getComputedStyle(ensureTip());
    const arrow = parseFloat(styles.getPropertyValue('--tip-arrow'));
    const gap = parseFloat(styles.getPropertyValue('--tip-gap'));
    const lift = parseFloat(styles.getPropertyValue('--bar-lift'));
    const radius = parseFloat(styles.borderTopLeftRadius);
    if (!isFinite(arrow) || !isFinite(gap) || !isFinite(lift) || !isFinite(radius)) {
      return FALLBACK_METRICS;
    }
    tipMetricsCache = { arrow: arrow, gap: gap, lift: lift, radius: radius };
    return tipMetricsCache;
  }

  // Під reduced-motion смужка не піднімається, тож підйом не компенсуємо.
  function barLift(metrics) {
    return reducedMotion && reducedMotion.matches ? 0 : metrics.lift;
  }

  function initBars() {
    ensureTip();
    const bars = document.querySelectorAll('.bar');
    bars.forEach(function(bar) {
      if (bar.getAttribute('title')) {
        if (!bar.dataset.title) bar.dataset.title = bar.getAttribute('title');
        bar.removeAttribute('title');
      }
      if (!bar.hasAttribute('tabindex')) {
        bar.setAttribute('tabindex', '0');
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initBars);
  } else {
    initBars();
  }

  function hideTip() {
    if (!tip) return;
    tip.classList.remove('is-visible');
    window.clearTimeout(hideTimer);
    hideTimer = window.setTimeout(function() {
      if (tip && !tip.classList.contains('is-visible')) {
        tip.hidden = true;
      }
    }, 150);

    if (currentBar) {
      currentBar.classList.remove('is-active');
      if (currentBar.parentElement) {
        currentBar.parentElement.classList.remove('has-active');
      }
      currentBar = null;
    }

    const activeBars = document.querySelectorAll('.bar.is-active');
    for (let i = 0; i < activeBars.length; i++) {
      activeBars[i].classList.remove('is-active');
    }
    const activeContainers = document.querySelectorAll('.bars.has-active');
    for (let i = 0; i < activeContainers.length; i++) {
      activeContainers[i].classList.remove('has-active');
    }

    if (document.activeElement && document.activeElement.classList && document.activeElement.classList.contains('bar')) {
      if (typeof document.activeElement.blur === 'function') {
        document.activeElement.blur();
      }
    }

    activeTouchBars = null;
    activePointerId = null;
  }

  function showTip(bar) {
    if (!bar) return;
    const text = bar.dataset.title || bar.getAttribute('data-title') || bar.getAttribute('aria-label');
    if (!text && !bar.dataset.time) return;

    ensureTip();

    // Знімаємо геометрію до .is-active: інакше в рект потрапляє незавершений
    // підйом смужки і відступ виходить різним при кожному показі.
    const barBox = bar.getBoundingClientRect();

    if (document.activeElement && document.activeElement !== bar && document.activeElement.classList && document.activeElement.classList.contains('bar')) {
      if (typeof document.activeElement.blur === 'function') {
        document.activeElement.blur();
      }
    }

    if (currentBar === bar && tip.classList.contains('is-visible')) {
      return;
    }

    const allActive = document.querySelectorAll('.bar.is-active');
    for (let i = 0; i < allActive.length; i++) {
      if (allActive[i] !== bar) allActive[i].classList.remove('is-active');
    }

    const allContainers = document.querySelectorAll('.bars.has-active');
    for (let i = 0; i < allContainers.length; i++) {
      if (allContainers[i] !== bar.parentElement) allContainers[i].classList.remove('has-active');
    }

    if (bar.parentElement) {
      bar.parentElement.classList.add('has-active');
    }

    currentBar = bar;
    bar.classList.add('is-active');

    const state = bar.dataset.state || bar.getAttribute('data-state') || 'ok';
    let timeText = bar.dataset.time || '';
    let stateText = bar.dataset.statusText || '';

    if (!timeText || !stateText) {
      const parts = (text || '').split(/\s*[—–-]\s*/);
      timeText = (parts[0] || '').trim();
      stateText = (parts[1] || '').trim();
    }

    const timeEl = tip.querySelector('.tip-time');
    const dotEl = tip.querySelector('.tip-dot');
    const textEl = tip.querySelector('.tip-text');

    if (timeEl && dotEl && textEl && (timeText || stateText)) {
      timeEl.textContent = timeText;
      textEl.textContent = stateText;
      dotEl.dataset.state = state;
    } else {
      if (timeEl) timeEl.textContent = text || '';
    }

    tip.hidden = false;

    const tipBox = tip.getBoundingClientRect();
    const metrics = tipMetrics();
    const margin = 8;

    const barCenterX = barBox.left + barBox.width / 2;
    const tipWidth = Math.round(tipBox.width);
    const tipHeight = Math.round(tipBox.height);

    let left = Math.round(barCenterX - tipWidth / 2);
    left = Math.max(margin, Math.min(left, window.innerWidth - tipWidth - margin));

    // --arrow-x відлічується від padding-box, як і сам вказівник;
    // він не заходить на заокруглені кути.
    const borderLeft = tip.clientLeft;
    const tipInnerWidth = tipWidth - borderLeft * 2;
    const arrowEdge = metrics.arrow + metrics.radius;
    const rawArrowX = barCenterX - left - borderLeft;
    const arrowX = Math.max(arrowEdge, Math.min(tipInnerWidth - arrowEdge, rawArrowX));
    tip.style.setProperty('--arrow-x', arrowX.toFixed(2) + 'px');

    // Вказівник виступає за рамку рівно на --tip-arrow, далі йде --tip-gap.
    // barBox знято до підйому смужки, тому додаємо його вручну — інакше
    // просвіт над смужкою й під нею вийшов би різним.
    const verticalOffset = metrics.arrow + metrics.gap + barLift(metrics);
    let top = Math.round(barBox.top - tipHeight - verticalOffset);

    if (top < margin) {
      top = Math.round(barBox.bottom + metrics.arrow + metrics.gap - barLift(metrics));
      tip.classList.add('tip--below');
    } else {
      tip.classList.remove('tip--below');
    }

    tip.style.left = left + 'px';
    tip.style.top = top + 'px';

    window.clearTimeout(hideTimer);
    if (!tip.classList.contains('is-visible')) {
      requestAnimationFrame(function() {
        tip.classList.add('is-visible');
      });
    }
  }

  function getBarFromCoordinates(barsEl, clientX) {
    const visibleBars = Array.from(barsEl.querySelectorAll('.bar')).filter(function(b) {
      return b.offsetParent !== null;
    });
    if (!visibleBars.length) return null;
    const rect = barsEl.getBoundingClientRect();
    const relX = clientX - rect.left;
    const ratio = Math.max(0, Math.min(0.9999, relX / rect.width));
    const index = Math.floor(ratio * visibleBars.length);
    return visibleBars[index] || null;
  }

  function onPointerMove(event) {
    if (event.pointerType === 'touch' || event.pointerType === 'pen') return;
    const bars = event.target && event.target.closest ? event.target.closest('.bars') : null;
    if (bars) {
      const bar = event.target.closest('.bar') || getBarFromCoordinates(bars, event.clientX);
      if (bar) {
        window.clearTimeout(hideTimer);
        showTip(bar);
      }
    }
  }

  function onPointerOut(event) {
    if (event.pointerType === 'touch' || event.pointerType === 'pen') return;
    const bars = event.target && event.target.closest ? event.target.closest('.bars') : null;
    if (bars) {
      const related = event.relatedTarget && event.relatedTarget.closest ? event.relatedTarget.closest('.bars') : null;
      if (!related) {
        hideTip();
      }
    }
  }

  document.addEventListener('pointermove', onPointerMove, true);
  document.addEventListener('pointerout', onPointerOut, true);

  document.addEventListener('pointerdown', function(event) {
    const isTouch = event.pointerType === 'touch' || event.pointerType === 'pen';
    const bars = event.target && event.target.closest ? event.target.closest('.bars') : null;

    if (bars) {
      const bar = event.target.closest('.bar') || getBarFromCoordinates(bars, event.clientX);
      if (bar) {
        window.clearTimeout(hideTimer);
        showTip(bar);
        if (isTouch) {
          activeTouchBars = bars;
          activePointerId = event.pointerId;
        }
      }
    } else {
      hideTip();
    }
  }, true);

  document.addEventListener('pointermove', function(event) {
    if (activeTouchBars && event.pointerId === activePointerId) {
      const bar = getBarFromCoordinates(activeTouchBars, event.clientX);
      if (bar && bar !== currentBar) {
        window.clearTimeout(hideTimer);
        showTip(bar);
      }
    }
  }, true);

  function onTouchEnd(event) {
    if (event.pointerId === activePointerId) {
      activeTouchBars = null;
      activePointerId = null;
      window.clearTimeout(hideTimer);
      hideTimer = window.setTimeout(hideTip, 2500);
    }
  }

  function onTouchCancel(event) {
    if (event.pointerId === activePointerId) {
      activeTouchBars = null;
      activePointerId = null;
      window.clearTimeout(hideTimer);
      hideTip();
    }
  }

  document.addEventListener('pointerup', onTouchEnd, true);
  document.addEventListener('pointercancel', onTouchCancel, true);

  // Дотик і клік самі наводять фокус на смужку вже після того, як тултип
  // показано. Повторний showTip на ту саму смужку не встигав вийти по
  // ранньому return (клас .is-visible ставиться лише в наступному кадрі)
  // і скидав таймер автоприховування — тултип на дотику лишався висіти,
  // а разом з ним завмирав і пульс. Фокус показує тултип тільки тоді,
  // коли він справді переїхав на іншу смужку — з клавіатури.
  document.addEventListener('focusin', function(event) {
    const bar = event.target && event.target.closest ? event.target.closest('.bar') : null;
    if (bar && bar !== currentBar) {
      showTip(bar);
    }
  }, true);

  document.addEventListener('focusout', function(event) {
    const bar = event.target && event.target.closest ? event.target.closest('.bar') : null;
    if (bar) {
      hideTip();
    }
  }, true);

  document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape' || event.key === 'Esc') {
      hideTip();
    } else if ((event.key === 'ArrowLeft' || event.key === 'ArrowRight') && currentBar) {
      const barsEl = currentBar.parentElement;
      if (barsEl) {
        const visibleBars = Array.from(barsEl.querySelectorAll('.bar')).filter(function(b) {
          return b.offsetParent !== null;
        });
        const currentIndex = visibleBars.indexOf(currentBar);
        if (currentIndex !== -1) {
          const nextIndex = event.key === 'ArrowLeft' ? currentIndex - 1 : currentIndex + 1;
          if (nextIndex >= 0 && nextIndex < visibleBars.length) {
            event.preventDefault();
            visibleBars[nextIndex].focus();
            showTip(visibleBars[nextIndex]);
          }
        }
      }
    }
  });

  window.addEventListener('scroll', hideTip, { passive: true });
  window.addEventListener('resize', hideTip);

  let due = Date.now() + REFRESH_MS;
  let loading = false;

  // Стан читається з класу плашки — того самого, яким сервер його й
  // намалював. Окремого поля для аналітики заводити нема потреби: якщо
  // плашка змінилась, змінився і стан.
  function systemState() {
    const notice = document.querySelector('.notice');
    const found = notice && /notice--([a-z]+)/.exec(notice.className);
    return found ? found[1] : 'unknown';
  }

  // Міняємо вміст картки, а не всю сторінку: <head>, шапка й підвал на
  // статус-сторінці не змінюються ніколи, а перемальовувати їх означало б
  // на кадр згасити логотип і збити прокрутку.
  function swap(html) {
    const fresh = new DOMParser().parseFromString(html, 'text/html');
    const card = fresh.getElementById('card');
    const current = document.getElementById('card');
    if (!card || !current) return false;

    // Смужки, на які показує тултип, зараз зникнуть з DOM — інакше він
    // лишиться висіти над порожнім місцем.
    hideTip();
    current.innerHTML = card.innerHTML;
    initBars();
    return true;
  }

  function refresh() {
    if (loading) return;
    loading = true;

    const controller = window.AbortController ? new AbortController() : null;
    const cutoff = controller
      ? window.setTimeout(function() { controller.abort(); }, TIMEOUT_MS)
      : null;

    // no-store: питати сервер і отримати у відповідь власну хвилинну копію
    // — те саме, що не питати.
    fetch(window.location.href, {
      cache: 'no-store',
      signal: controller ? controller.signal : undefined
    })
      .then(function(response) {
        if (!response.ok) throw new Error('status ' + response.status);
        return response.text();
      })
      .then(function(html) {
        if (swap(html) && window.track) {
          window.track('status_auto_refresh', { system_state: systemState() });
        }
      })
      .catch(function() {
        // Провал не показуємо: сторінка лишається тією, що була, а
        // наступний такт спробує ще раз. Кричати про мережу на сторінці
        // про збої — сказати про збій, якого може й не бути.
      })
      .finally(function() {
        window.clearTimeout(cutoff);
        loading = false;
        due = Date.now() + REFRESH_MS;
      });
  }

  const tick = function() {
    if (document.visibilityState !== 'visible') return;
    if (Date.now() < due) return;
    if (currentBar || activeTouchBars) {
      due = Date.now() + BUSY_MS;
      return;
    }
    refresh();
  };

  window.setInterval(tick, TICK_MS);

  // Вкладку могли лишити відкритою на ніч: щойно на неї повернулись,
  // сторінка питає стан, не чекаючи наступного такту.
  document.addEventListener('visibilitychange', tick);
})();

/*
 * Сторінка стану: плавна підказка по наведенню/дотику з чітким виділенням
 * обраної години, підтримка тач-скрабінгу (touch scrubbing) та автоматичне фонове оновлення.
 */
(function() {
  'use strict';

  const REFRESH_MS = 60000;

  // --- підказка по ховеру / дотику / фокусу ----------------------------------

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
      tip.innerHTML = '<span class="tip-time"></span><span class="tip-state"><span class="tip-dot" data-state="ok"></span><span class="tip-text"></span></span><svg class="tip-arrow" width="10" height="6" viewBox="0 0 10 6" aria-hidden="true"><path d="M 0.5 0 L 5 5 L 9.5 0" fill="#fff" stroke="#B0B0B0" stroke-width="1" stroke-linecap="square" stroke-linejoin="miter"></path><path d="M 0 0 L 10 0" stroke="#fff" stroke-width="2"></path></svg>';
    }
    const root = document.body || document.documentElement;
    if (root && tip.parentElement !== root) {
      root.appendChild(tip);
    }
    return tip;
  }

  // Прибираємо стандартний спливаючий атрибут title браузера, якщо він десь залишився
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

    // Гарантоване очищення активних класів з усіх смужок та контейнерів
    const activeBars = document.querySelectorAll('.bar.is-active');
    for (let i = 0; i < activeBars.length; i++) {
      activeBars[i].classList.remove('is-active');
    }
    const activeContainers = document.querySelectorAll('.bars.has-active');
    for (let i = 0; i < activeContainers.length; i++) {
      activeContainers[i].classList.remove('has-active');
    }

    // Знімаємо фокус з активної смужки, щоб при скролі не залишалася обводка фокусу
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

    // Якщо фокус був на іншій смужці після тапу, знімаємо фокус, щоб не залишалося старої обводки
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

    // Позиціонування підказки точно над/під центром смужки зі стрілкою (цілі пікселі для чіткості стиків)
    const barBox = bar.getBoundingClientRect();
    const tipBox = tip.getBoundingClientRect();
    const margin = 8;

    const barCenterX = Math.round(barBox.left + barBox.width / 2);
    const tipWidth = Math.round(tipBox.width);
    const tipHeight = Math.round(tipBox.height);

    let left = Math.round(barCenterX - tipWidth / 2);
    left = Math.max(margin, Math.min(left, window.innerWidth - tipWidth - margin));

    // Стрілка центрується точно по смужці з безпечним відступом від кутів
    const arrowX = Math.round(Math.max(10, Math.min(tipWidth - 10, barCenterX - left)));
    tip.style.setProperty('--arrow-x', arrowX + 'px');

    const verticalOffset = 7;
    let top = Math.round(barBox.top - tipHeight - verticalOffset);

    if (top < margin) {
      top = Math.round(barBox.bottom + verticalOffset);
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

  // --- Миша (плавний трекінг без мерехтіння на проміжках) -------------------
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
      // Ховаємо підказку лише тоді, коли курсор повністю залишив компонент .bars
      if (!related) {
        hideTip();
      }
    }
  }

  document.addEventListener('pointermove', onPointerMove, true);
  document.addEventListener('pointerout', onPointerOut, true);

  // --- Тач-взаємодія та скрабінг -------------------------------------------
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

  // --- Фокус та клавіатура --------------------------------------------------
  document.addEventListener('focusin', function(event) {
    const bar = event.target && event.target.closest ? event.target.closest('.bar') : null;
    if (bar) {
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

  // --- оновлення (з безпечним відкладенням під час взаємодії) ----------------
  let due = Date.now() + REFRESH_MS;

  const tick = function() {
    if (document.visibilityState !== 'visible') return;
    if (Date.now() < due) return;
    // Якщо користувач прямо зараз вивчає графік, відкладаємо релоад на 10 секунд
    if (currentBar || activeTouchBars) {
      due = Date.now() + 10000;
      return;
    }
    window.location.reload();
  };

  window.setInterval(tick, 5000);
  document.addEventListener('visibilitychange', tick);
})();

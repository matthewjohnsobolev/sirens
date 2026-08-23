/*
 * Сторінка стану рендериться на сервері й повністю читається без цього файлу.
 * Тут лише те, чого не вміє розмітка: підказка по дотику (атрибут title на
 * сенсорному екрані не показується ніяк) і оновлення сторінки, поки на неї
 * дивляться.
 */
(function() {
  'use strict';

  const REFRESH_MS = 60000;

  // --- підказка по дотику ---------------------------------------------------

  const tip = document.createElement('div');
  tip.className = 'tip';
  tip.setAttribute('role', 'status');
  tip.hidden = true;
  document.body.appendChild(tip);

  let hideTimer = null;

  const hideTip = function() {
    tip.hidden = true;
    window.clearTimeout(hideTimer);
  };

  const showTip = function(bar) {
    const text = bar.dataset.title;
    if (!text) return;

    tip.textContent = text;
    tip.hidden = false;

    // Позиціонуємо після показу: до цього ширини підказки ще немає.
    const barBox = bar.getBoundingClientRect();
    const tipBox = tip.getBoundingClientRect();
    const margin = 8;
    let left = barBox.left + barBox.width / 2 - tipBox.width / 2;
    left = Math.max(margin, Math.min(left, window.innerWidth - tipBox.width - margin));

    let top = barBox.top - tipBox.height - margin;
    if (top < margin) top = barBox.bottom + margin;

    tip.style.left = left + 'px';
    tip.style.top = top + 'px';

    window.clearTimeout(hideTimer);
    hideTimer = window.setTimeout(hideTip, 2500);
  };

  document.addEventListener('pointerdown', function(event) {
    const bar = event.target.closest ? event.target.closest('.bar') : null;
    if (bar) {
      showTip(bar);
    } else {
      hideTip();
    }
  });

  window.addEventListener('scroll', hideTip, { passive: true });
  window.addEventListener('resize', hideTip);

  // --- оновлення ------------------------------------------------------------

  // Кеш на бекенді живе хвилину, тож частіше питати нема сенсу. Вкладку, на яку
  // не дивляться, не чіпаємо: перезавантажуємо її, коли до неї повернуться.
  let due = Date.now() + REFRESH_MS;

  const tick = function() {
    if (document.visibilityState !== 'visible') return;
    if (Date.now() < due) return;
    window.location.reload();
  };

  window.setInterval(tick, 5000);
  document.addEventListener('visibilitychange', tick);
})();

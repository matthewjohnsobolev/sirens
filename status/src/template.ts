function getStateInfo(headline: string) {
    if (headline === 'Сповіщення не надходять') {
        return {
            cls: 'error',
            icon: '/img/icons/explosion-icon.svg'
        };
    }
    if (headline.includes('— ні') || headline.includes('перебо')) {
        return {
            cls: 'warning',
            icon: '/img/icons/air-raid-alert-icon.svg'
        };
    }
    if (headline === 'Планові роботи') {
        return {
            cls: 'mnt',
            icon: '/img/icons/mnt-icon.svg'
        };
    }
    if (headline === 'Стан невідомий') {
        return {
            cls: 'nodata',
            icon: '/img/icons/no-data-icon.svg'
        };
    }
    return {
        cls: 'ok',
        icon: '/img/icons/air-raid-alert-cancelled-icon.svg'
    };
}

export function renderHtml(data: any): string {
    const formatUptime = (uptime: number | null) => {
        if (uptime === null) return '—';
        if (uptime >= 100) return '100%';
        const formatted = (uptime > 99.9 && uptime < 100) ? '99,9' : uptime.toFixed(1).replace('.', ',');
        return formatted + '%';
    };

    const stateInfo = getStateInfo(data.headline);
    const getSummary = data.hours_summary || (() => 'немає даних');
    const getTitle = data.hour_title || ((date: string, state: string) => state);

    const componentsHtml = data.components.map((comp: any) => {
        const hoursList = comp.hours || [];
        const summaryText = getSummary(hoursList);
        
        return `
      <section class="comp" data-key="${comp.key}" data-monitored="${comp.monitored ? 'true' : 'false'}">
        <div class="comp-head">
          <h2 class="comp-name">${comp.name}</h2>
          <span class="comp-val">
            ${!comp.monitored ? '<span class="val-full">моніторинг не налаштовано</span><span class="val-short">не налаштовано</span>' : formatUptime(comp.uptime)}
          </span>
        </div>
        ${comp.desc ? `<p class="comp-desc">${comp.desc}</p>` : ''}
        <div class="bars" role="group" aria-label="${comp.name}: ${summaryText}">
          ${hoursList.map((hour: any) => {
            const title = hour.title || getTitle(hour.date, hour.state);
            const timeAttr = hour.timeText ? ` data-time="${hour.timeText}"` : '';
            const statusAttr = hour.statusText ? ` data-status-text="${hour.statusText}"` : '';
            return `<div class="bar" role="button" tabindex="0" data-state="${hour.state}"${timeAttr}${statusAttr} data-title="${title}" aria-label="${title}"></div>`;
          }).join('')}
        </div>
        <div class="scale">
          <span class="scale-from">24 години тому</span>
          <span>Зараз</span>
        </div>
      </section>
    `;
    }).join('');

    const hasSpecificFailure = data.headline.includes('— ні') || data.headline === 'Сповіщення не надходять' || data.headline.includes('перебо');
    const formattedSubtitle = data.subtitle ? data.subtitle.replace(/(\b\d{1,2}:\d{2}\b)/g, '<time class="mono-time">$1</time>') : '';

    return `<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Стан системи | Сирени</title>
<meta name="description" content="Поточний стан та історія доступності компонентів системи «Сирени»: сповіщення в Telegram, джерела тривог, мапа тривог та API за останні 24 години.">
<meta name="theme-color" content="#F4F4F4">
<meta property="og:title" content="Стан системи | Сирени">
<meta property="og:description" content="Поточний стан та історія доступності компонентів системи «Сирени» за останні 24 години.">
<meta property="og:type" content="website">
<meta property="og:url" content="https://status.sirens.live">
<meta name="twitter:card" content="summary">
<link rel="shortcut icon" href="/favicon.ico">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/css/status.css">
<script src="/js/status.js" defer></script>
</head>

<body>
<div class="shell">

  <a href="https://sirens.live" class="logo" title="Сирени">
    <img src="/img/logo.svg" alt="Сирени" width="60" height="60">
  </a>

  <div class="card" id="card">
    <h1>Стан системи</h1>

    <div class="notice notice--${stateInfo.cls}">
      <div class="notice-pill">
        <div class="notice-icon" aria-hidden="true">
          <img src="${stateInfo.icon}" alt="" width="24" height="24">
        </div>
        <span class="notice-headline">${data.headline}</span>
      </div>
      ${formattedSubtitle ? `<p class="notice-desc">${formattedSubtitle}</p>` : ''}
    </div>

    <div class="list" id="list">
      ${componentsHtml}
    </div>

    <div class="card-action">
      <p class="card-action-text">${hasSpecificFailure ? 'Помітили інший збій або проблему в роботі?' : 'Не отримали сповіщення або помітили збій?'}</p>
      <a href="https://sirens.live/issue" class="btn-report">
        ${hasSpecificFailure ? 'Повідомити про інший збій' : 'Повідомити про збій'}
      </a>
    </div>
  </div>

  <footer class="foot">
    <div class="foot-main">
      <span class="foot-copy">© 2026 «Сирени»</span>
      <nav class="foot-nav" aria-label="Посилання">
        <a href="https://sirens.live">Мапа тривог</a>
        <span class="foot-sep" aria-hidden="true">·</span>
        <a href="https://sirens.live/issue">Повідомити про збій</a>
      </nav>
    </div>

    <div class="foot-disclaimer">
      <p>«Сирени» — незалежний агрегатор тривог. Сервіс не є офіційним джерелом оповіщення населення. Почувши сигнал тривоги, орієнтуйтесь на офіційні джерела та одразу прямуйте в укриття.</p>
    </div>
  </footer>

</div>
</body>
</html>`;
}

import { statusWord } from "./helpers";
import { analyticsHead } from "./analytics";

function getBadgeClass(state: string): string {
    if (state === 'ok') return 'ok';
    if (state === 'minor') return 'minor';
    if (state === 'down' || state === 'major') return 'down';
    if (state === 'mnt') return 'mnt';
    return 'nodata';
}

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
    if (headline === 'Немає даних') {
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

export function renderHtml(data: any, measurementId = ""): string {
    const stateInfo = getStateInfo(data.headline);
    const getSummary = data.hours_summary || (() => 'немає даних');
    const getTitle = data.hour_title || ((date: string, state: string) => state);

    const componentsHtml = data.components.map((comp: any) => {
        const hoursList = comp.hours || [];
        const summaryText = getSummary(hoursList);
        const badgeCls = getBadgeClass(comp.state);
        const badgeLabel = statusWord(comp.state);

        return `
      <section class="comp" data-key="${comp.key}" data-monitored="${comp.monitored ? 'true' : 'false'}">
        <div class="comp-head">
          <h2 class="comp-name">${comp.name}</h2>
          <span class="comp-val">
            ${!comp.monitored
                ? '<span class="val-full">моніторинг не налаштовано</span><span class="val-short">не налаштовано</span>'
                : `<span class="comp-badge comp-badge--${badgeCls}">${badgeLabel}</span>`}
          </span>
        </div>
        ${comp.desc ? `<p class="comp-desc">${comp.desc}</p>` : ''}
        <div class="bars" role="group" aria-label="${comp.name}: ${summaryText}">
          ${hoursList.map((hour: any, index: number) => {
            const title = hour.title || getTitle(hour.date, hour.state);
            const timeAttr = hour.timeText ? ` data-time="${hour.timeText}"` : '';
            const statusAttr = hour.statusText ? ` data-status-text="${hour.statusText}"` : '';
            // Остання смужка — година, яка ще триває: вона пульсує. Пульс
            // з'являється лише там, де є що показувати, — у ненастроєного
            // компонента й у години без даних він удавав би моніторинг.
            const isLive = comp.monitored && index === hoursList.length - 1 && hour.state !== 'nodata';
            return `<div class="bar${isLive ? ' bar--live' : ''}" role="button" tabindex="0" data-state="${hour.state}"${timeAttr}${statusAttr} data-title="${title}" aria-label="${title}"></div>`;
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
<meta name="robots" content="index, follow, max-image-preview:large">
<meta name="theme-color" content="#F4F4F4">
<link rel="canonical" href="https://status.sirens.live/">
${analyticsHead(measurementId, stateInfo.cls)}
<meta property="og:title" content="Стан системи | Сирени">
<meta property="og:description" content="Поточний стан та історія доступності компонентів системи «Сирени» за останні 24 години.">
<meta property="og:type" content="website">
<meta property="og:url" content="https://status.sirens.live">
<meta property="og:site_name" content="Сирени">
<meta property="og:locale" content="uk_UA">
<meta property="og:image" content="https://sirens.live/static/img/og-banner.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="Мапа повітряних тривог України «Сирени»">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Стан системи | Сирени">
<meta name="twitter:description" content="Поточний стан та історія доступності компонентів системи «Сирени» за останні 24 години.">
<meta name="twitter:image" content="https://sirens.live/static/img/og-banner.png">
<meta name="twitter:image:alt" content="Мапа повітряних тривог України «Сирени»">
<link rel="shortcut icon" href="/favicon.ico">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/css/status.css">
<script src="/js/status.js" defer></script>
<script src="/js/analytics.js" defer></script>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "WebPage",
  "name": "Стан системи | Сирени",
  "url": "https://status.sirens.live/",
  "description": "Поточний стан та історія доступності компонентів системи «Сирени» за останні 24 години.",
  "inLanguage": "uk-UA",
  "isPartOf": {"@type": "WebSite", "@id": "https://sirens.live/#website"}
}
</script>
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
      <p>«Сирени» — незалежний сервіс агрегації повітряних тривог. Це не заміна офіційної системи оповіщення.</p>
    </div>
  </footer>

</div>
</body>
</html>`;
}

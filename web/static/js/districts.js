/**
 * District markers, color constants, and threat dominance logic.
 */

const ALERT_COLORS = {
    IDLE: '#8A8A8A',
    ALERT: '#FF831A',
    EXPLOSION: '#FF1A1A',
    SHELLING: '#FFDA1A'
};

const FALLBACK_ORDER = ['explosion', 'alert', 'shelling']; // Fallback order when updated_at is equal

function pickDominant(threats) { // {alert, explosion, shelling} -> 'alert' | 'explosion' | 'shelling' | null
    if (!threats) return null;
    let best = null;
    for (const kind of FALLBACK_ORDER) {
        const t = threats[kind];
        if (!t || !t.status) continue;
        if (!best || (t.updated_at || 0) > (threats[best].updated_at || 0)) {
            best = kind;
        }
    }
    return best;
}

const PILL_VARIANTS = {
    idle:      { cls: 'green-oblast-button',   icon: 'air-raid-alert-cancelled-icon.svg', label: 'Відбій тривоги' },
    alert:     { cls: 'orange-oblast-button',  icon: 'air-raid-alert-icon.svg',           label: 'Повітряна тривога' },
    partial:   { cls: 'hatched-oblast-button', icon: 'air-raid-alert-icon.svg',           label: 'Тривога у районах' },
    shelling:  { cls: 'yellow-oblast-button',  icon: 'yellow-logo.svg',                   label: 'Загроза артобстрілу' },
    explosion: { cls: 'red-oblast-button',     icon: 'channel-red.svg',                   label: 'Чутно вибухи' },
    unknown:   { cls: 'gray-oblast-button',    icon: 'air-raid-alert-cancelled-icon.svg', label: 'Немає даних' }
};

const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

function formatDuration(updatedAt) {
    if (!updatedAt) return '';
    const seconds = Math.max(0, Math.floor(Date.now() / 1000) - updatedAt);

    if (seconds < MINUTE) return 'щойно';
    if (seconds < HOUR) return `${Math.floor(seconds / MINUTE)} хв`;
    if (seconds < DAY) {
        const hours = Math.floor(seconds / HOUR);
        const minutes = Math.floor((seconds % HOUR) / MINUTE);
        return minutes ? `${hours} год ${minutes} хв` : `${hours} год`;
    }
    const days = Math.floor(seconds / DAY);
    const hours = Math.floor((seconds % DAY) / HOUR);
    return hours ? `${days} дн ${hours} год` : `${days} дн`;
}

// compact - лише модифікатор розміру; він не залежить від кольорового класу
// і працює з будь-яким, включно зі штриховкою.
function renderPill({ variant, text, updatedAt, source, showTime = true, compact = false }) {
    const v = PILL_VARIANTS[variant] || PILL_VARIANTS.unknown;
    const cls = compact ? `${v.cls} oblast-button--compact` : v.cls;
    const duration = (showTime && updatedAt) ? formatDuration(updatedAt) : '';
    const timeHtml = duration ? `<div class="oblast-description-time">${duration}</div>` : '';
    const body = `
        <button class="${cls}">
            <div class="icon-container"><img class="icon" src="static/img/icons/${v.icon}"></div>
            <div class="oblast-description-text">${text || v.label}</div>
            ${timeHtml}
        </button>`;
    const wrapped = (source && source !== 'None')
        ? `<a href="${source}" class="oblast-button-link">${body}</a>`
        : body;
    return `<div class="info-block">${wrapped}</div>`;
}

function districtAlertStamps(oblastData, keys) {
    return keys
        .map(key => {
            const district = oblastData.districts && oblastData.districts[key];
            return district && district.alert ? district.alert.updated_at || 0 : 0;
        })
        .filter(stamp => stamp > 0);
}

function oblastSummary(oblastData) {
    const alert = (oblastData && oblastData.alert) || {};
    const tracked = alert.tracked_districts || [];
    const active = alert.active_districts || [];

    if (!tracked.length) {
        return { variant: 'unknown', text: 'Немає даних по районах', updatedAt: 0 };
    }

    // Головна таблетка показує стан області одним словом, без переліку районів -
    // деталі по кожному місту нижче, в акордеоні.
    if (alert.coverage === 'full') {
        return { variant: 'alert', text: 'Повітряна тривога', updatedAt: 0 };
    }
    if (alert.coverage === 'partial') {
        return { variant: 'partial', text: 'Часткова тривога', updatedAt: 0 };
    }

    return { variant: 'idle', text: 'Тривог немає', updatedAt: 0 };
}

function districtPillState(oblastData, key) {
    const district = (oblastData.districts && oblastData.districts[key]) || {};
    const threats = {
        alert: district.alert,
        shelling: district.shelling,
        explosion: oblastData.explosion
    };
    const dominant = pickDominant(threats) || 'idle';
    const winner = threats[dominant] || district.alert || {};

    return { variant: dominant, updatedAt: winner.updated_at, source: winner.source };
}

const DISTRICT_MARKERS = [
    { district: 'bilatserkva', oblast: 'kyiv_oblast', name: 'Біла Церква', lat: 49.7968, lng: 30.1311, channel: 'bilatserkva_alert' },
    { district: 'bucha', oblast: 'kyiv_oblast', name: 'Буча', lat: 50.5533, lng: 30.2135, channel: 'bucha_alert' },
    { district: 'fastiv', oblast: 'kyiv_oblast', name: 'Фастів', lat: 50.0638, lng: 29.9050, channel: 'fastiv_alert' },
    { district: 'cherkasy', oblast: 'cherkasy_oblast', name: 'Черкаси', lat: 49.4444, lng: 32.0598, channel: 'cherkasy_alert' },
    { district: 'chernihiv', oblast: 'chernihiv_oblast', name: 'Чернігів', lat: 51.4982, lng: 31.2893, channel: 'chernihiv_alert' },
    { district: 'chernivtsi', oblast: 'chernivtsi_oblast', name: 'Чернівці', lat: 48.2921, lng: 25.9358, channel: 'chernivtsi_alert' },
    { district: 'dnipro', oblast: 'dnipropetrovsk_oblast', name: 'Дніпро', lat: 48.4647, lng: 35.0462, channel: 'dnipro_alert' },
    { district: 'ivanofrankivsk', oblast: 'ivanofrankivsk_oblast', name: 'Івано-Франківськ', lat: 48.9226, lng: 24.7111, channel: 'ivanofrankivsk_alert' },
    { district: 'kamianske', oblast: 'dnipropetrovsk_oblast', name: "Кам'янське", lat: 48.5160, lng: 34.6129, channel: 'kamianske_alert' },
    { district: 'kharkiv', oblast: 'kharkiv_oblast', name: 'Харків', lat: 49.9935, lng: 36.2304, channel: 'kharkiv_alert' },
    { district: 'khmelnytskyi', oblast: 'khmelnytskyi_oblast', name: 'Хмельницький', lat: 49.4230, lng: 26.9871, channel: 'khmelnytskyi_alert' },
    { district: 'kovel', oblast: 'volyn_oblast', name: 'Ковель', lat: 51.2090, lng: 24.6980, channel: 'kovel_alert' },
    { district: 'kropyvnytskyi', oblast: 'kirovohrad_oblast', name: 'Кропивницький', lat: 48.5079, lng: 32.2623, channel: 'kropyvnytskyi_alert' },
    { district: 'kryvyirih', oblast: 'dnipropetrovsk_oblast', name: 'Кривий Ріг', lat: 47.9105, lng: 33.3918, channel: 'kryvyirih_alert' },
    { district: 'kyiv', oblast: 'kyiv', name: 'Київ', lat: 50.4501, lng: 30.5234, channel: 'kyiv_alert' },
    { district: 'lutsk', oblast: 'volyn_oblast', name: 'Луцьк', lat: 50.7472, lng: 25.3254, channel: 'lutsk_alert' },
    { district: 'lviv', oblast: 'lviv_oblast', name: 'Львів', lat: 49.8397, lng: 24.0297, channel: 'lviv_alert' },
    { district: 'mykolaiv', oblast: 'mykolaiv_oblast', name: 'Миколаїв', lat: 46.9750, lng: 31.9946, channel: 'mykolaiv_alert' },
    { district: 'odesa', oblast: 'odesa_oblast', name: 'Одеса', lat: 46.4825, lng: 30.7233, channel: 'odesa_alert' },
    { district: 'pervomaisk', oblast: 'mykolaiv_oblast', name: 'Первомайськ', lat: 48.0451, lng: 30.8884, channel: 'pervomaisk_alert' },
    { district: 'kremenchuk', oblast: 'poltava_oblast', name: 'Кременчук', lat: 49.0658, lng: 33.4100, channel: 'kremenchuk_alert' },
    { district: 'sumy', oblast: 'sumy_oblast', name: 'Суми', lat: 50.9077, lng: 34.7981, channel: 'sumy_alert' },
    { district: 'ternopil', oblast: 'ternopil_oblast', name: 'Тернопіль', lat: 49.5535, lng: 25.5948, channel: 'ternopil_alert' },
    { district: 'vinnytsia', oblast: 'vinnytsia_oblast', name: 'Вінниця', lat: 49.2331, lng: 28.4682, channel: 'vinnytsia_alert' },
    { district: 'uzhhorod', oblast: 'zakarpattia_oblast', name: 'Ужгород', lat: 48.6208, lng: 22.2879, channel: 'uzhhorod_alert' },
    { district: 'zaporizhzhia', oblast: 'zaporizhzhia_oblast', name: 'Запоріжжя', lat: 47.8388, lng: 35.1396, channel: 'zaporizhzhia_alert' },
    { district: 'zhytomyr', oblast: 'zhytomyr_oblast', name: 'Житомир', lat: 50.2547, lng: 28.6587, channel: 'zhytomyr_alert' },
    { district: 'rivne', oblast: 'rivne_oblast', name: 'Рівне', lat: 50.6199, lng: 26.2516, channel: 'rivne_sirens' },
    { district: 'uman', oblast: 'cherkasy_oblast', name: 'Умань', lat: 48.7494, lng: 30.2214, channel: 'uman_sirens' },
    { district: 'poltava', oblast: 'poltava_oblast', name: 'Полтава', lat: 49.5883, lng: 34.5514, channel: 'poltava_sirens' },
    { district: 'nikopol', oblast: 'dnipropetrovsk_oblast', name: 'Нікополь', lat: 47.5675, lng: 34.3948, channel: 'nikopol_alert' },
    { district: 'kherson', oblast: 'kherson_oblast', name: 'Херсон', lat: 46.6354, lng: 32.6169, channel: 'kherson_alert' },
    { district: 'izmail', oblast: 'odesa_oblast', name: 'Ізмаїл', lat: 45.3502, lng: 28.8502, channel: 'izmail_sirens' },
    { district: 'zolotonosha', oblast: 'cherkasy_oblast', name: 'Золотоноша', lat: 49.6618, lng: 32.0477, channel: 'zolotonosha_sirens' },
    { district: 'zvenyhorodka', oblast: 'cherkasy_oblast', name: 'Звенигородка', lat: 49.0762, lng: 30.9700, channel: 'zvenyhorodka_sirens' },
    // Немає каналу в config.py -> немає даних по району; красимо від агрегату області
    { district: null, oblast: 'zhytomyr_oblast', name: 'Звягель', lat: 50.5860, lng: 27.6364, channel: 'zviahel_sirens' },
    { district: null, oblast: 'zhytomyr_oblast', name: 'Коростень', lat: 50.9481, lng: 28.6412, channel: 'korosten_sirens' },
    { district: null, oblast: 'zhytomyr_oblast', name: 'Бердичів', lat: 49.9107, lng: 28.5900, channel: 'berdychiv_sirens' }
];

function getMarkerThreats(apiData, marker) {
    if (!apiData) return { alert: null, explosion: null, shelling: null };
    const oblastData = apiData[marker.oblast];
    if (!oblastData) {
        return { alert: null, explosion: null, shelling: null };
    }

    let alert = null;
    let shelling = null;

    if (marker.district && oblastData.districts && oblastData.districts[marker.district]) {
        alert = oblastData.districts[marker.district].alert;
        shelling = oblastData.districts[marker.district].shelling;
    } else {
        alert = oblastData.alert;
    }

    // Direct check if top-level entry exists for city (e.g. apiData.nikopol, apiData.kherson)
    if (marker.district && apiData[marker.district] && apiData[marker.district].shelling) {
        if (!shelling || !shelling.status) {
            if (apiData[marker.district].shelling.status) {
                shelling = apiData[marker.district].shelling;
            }
        }
    }

    // Обстріл, що потрапив у хеш тривог, сервер уже погасив (status=false для
    // threat_of_shelling*, web/db.py), тож pickDominant його не візьме. Мітку часу
    // при цьому лишаємо — з неї рахується тривалість відбою в попапі маркера.

    const explosion = oblastData.explosion;

    return { alert, explosion, shelling };
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        ALERT_COLORS,
        FALLBACK_ORDER,
        PILL_VARIANTS,
        pickDominant,
        formatDuration,
        renderPill,
        oblastSummary,
        districtPillState,
        DISTRICT_MARKERS,
        getMarkerThreats
    };
}

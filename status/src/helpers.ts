export const UK_MONTHS = [
    "", "січня", "лютого", "березня", "квітня", "травня", "червня",
    "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"
];

// [однина, множина] — форма підбирається під назву компонента:
// «Сповіщення в Telegram» — множина, решта — однина.
export const STATUS_WORDS: Record<string, [string, string]> = {
    "ok": ["працює", "працюють"],
    "minor": ["часткові збої", "часткові збої"],
    "major": ["не працює", "не працюють"],
    "down": ["не працює", "не працюють"],
    "mnt": ["планові роботи", "планові роботи"],
    "nodata": ["немає даних", "немає даних"],
};

const PLURAL_COMPONENTS = new Set(["broadcast"]);

export function statusWord(state: string, componentKey?: string): string {
    const forms = STATUS_WORDS[state];
    if (!forms) return state;
    return PLURAL_COMPONENTS.has(componentKey || "") ? forms[1] : forms[0];
}

export const LOCATION_LOCATIVE: Record<string, string> = {
    "bilatserkva": "у Білій Церкві",
    "bucha": "у Бучі",
    "cherkasy": "у Черкасах",
    "chernihiv": "у Чернігові",
    "chernivtsi": "у Чернівцях",
    "dnipro": "у Дніпрі",
    "fastiv": "у Фастові",
    "ivanofrankivsk": "в Івано-Франківську",
    "izmail": "в Ізмаїлі",
    "kamianske": "у Кам'янському",
    "kharkiv": "у Харкові",
    "kherson": "у Херсоні",
    "khmelnytskyi": "у Хмельницькому",
    "kovel": "у Ковелі",
    "kremenchuk": "у Кременчуці",
    "kropyvnytskyi": "у Кропивницькому",
    "kryvyirih": "у Кривому Розі",
    "kyiv": "у Києві",
    "lutsk": "у Луцьку",
    "lviv": "у Львові",
    "mykolaiv": "у Миколаєві",
    "nikopol": "у Нікополі",
    "odesa": "в Одесі",
    "pervomaisk": "у Первомайську",
    "poltava": "у Полтаві",
    "rivne": "у Рівному",
    "sumy": "у Сумах",
    "ternopil": "у Тернополі",
    "uman": "в Умані",
    "uzhhorod": "в Ужгороді",
    "vinnytsia": "у Вінниці",
    "zaporizhzhia": "у Запоріжжі",
    "zhytomyr": "у Житомирі",
    "zolotonosha": "у Золотоноші",
    "zvenyhorodka": "у Звенигородці",

    "boryspil": "у Борисполі",
    "brovary": "у Броварах",
    "vyshhorod": "у Вишгороді",
    "obukhiv": "в Обухові",
};

export function formatLocationLocative(
    districtKey?: string | null,
    locationName?: string | null,
    customLocative?: string | null
): string {
    if (customLocative) {
        return customLocative.startsWith("у ") || customLocative.startsWith("в ") ? customLocative : `у ${customLocative}`;
    }
    const cleanKey = districtKey ? districtKey.toLowerCase().replace(/[-_]/g, "") : "";
    if (cleanKey && LOCATION_LOCATIVE[cleanKey]) {
        return LOCATION_LOCATIVE[cleanKey];
    }
    if (!locationName) return "";
    const trimmed = locationName.trim();
    if (trimmed.endsWith(" район")) {
        const base = trimmed.slice(0, -6);
        let adj = base;
        if (base.endsWith("ий") || base.endsWith("ій")) {
            adj = base.slice(0, -2) + "ому";
        }
        const prep = /^[аеєиіїоуюя]/i.test(trimmed) ? "в" : "у";
        return `${prep} ${adj} районі`;
    }
    const prep = /^[аеєиіїоуюя]/i.test(trimmed) ? "в" : "у";
    return `${prep} ${trimmed}`;
}

const kyivFormatter = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Kyiv",
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "numeric",
    second: "numeric",
    hour12: false
});

export function getKyivParts(date: Date) {
    const parts = kyivFormatter.formatToParts(date);
    const map: Record<string, string> = {};
    for (const p of parts) {
        map[p.type] = p.value;
    }
    return {
        year: parseInt(map.year, 10),
        month: parseInt(map.month, 10),
        day: parseInt(map.day, 10),
        hour: parseInt(map.hour, 10) % 24,
        minute: parseInt(map.minute, 10),
        second: parseInt(map.second, 10)
    };
}

function kyivDayIndex(p: { year: number; month: number; day: number }): number {
    return Date.UTC(p.year, p.month - 1, p.day) / 86400000;
}

// Порівнює дві дати за календарним днем у Києві (а не за різницею в годинах),
// щоб подія з 23:59 і "зараз" о 00:05 наступної доби коректно ставали "вчора", а не "сьогодні".
export function relativeDayLabel(
    p: { year: number; month: number; day: number },
    nowP: { year: number; month: number; day: number }
): "сьогодні" | "вчора" | null {
    const diff = kyivDayIndex(nowP) - kyivDayIndex(p);
    if (diff === 0) return "сьогодні";
    if (diff === 1) return "вчора";
    return null;
}

export function pluralHours(count: number): string {
    if (count % 100 >= 11 && count % 100 <= 14) return "годин";
    const last = count % 10;
    if (last === 1) return "година";
    if (last >= 2 && last <= 4) return "години";
    return "годин";
}

export function formatHourParts(isoDate: string, state: string, componentKey?: string) {
    const word = statusWord(state, componentKey);
    try {
        const d = new Date(isoDate);
        const p = getKyivParts(d);
        const hh = p.hour.toString().padStart(2, '0');
        const mm = p.minute.toString().padStart(2, '0');
        const timeText = `${p.day} ${UK_MONTHS[p.month]}, ${hh}:${mm}`;
        return {
            timeText,
            statusText: word,
            fullTitle: `${timeText} — ${word}`
        };
    } catch {
        return {
            timeText: "",
            statusText: word,
            fullTitle: word
        };
    }
}

export function formatHourTitle(isoDate: string, state: string, componentKey?: string): string {
    return formatHourParts(isoDate, state, componentKey).fullTitle;
}

export function summarizeHours(items: any[]): string {
    const counts: Record<string, number> = {};
    for (const item of items) {
        const state = item.state === "major" ? "down" : (item.state || "nodata");
        counts[state] = (counts[state] || 0) + 1;
    }

    const order = [
        ["ok", "працює"],
        ["minor", "з частковими збоями"],
        ["down", "з тривалими збоями"],
        ["mnt", "планові роботи"],
        ["nodata", "без даних"],
    ];

    const parts = [];
    for (const [state, word] of order) {
        if (counts[state]) {
            parts.push(`${counts[state]} ${pluralHours(counts[state])} ${word}`);
        }
    }
    return parts.join(", ") || "немає даних";
}

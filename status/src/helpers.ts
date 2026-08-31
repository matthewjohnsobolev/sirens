export const UK_MONTHS = [
    "", "січня", "лютого", "березня", "квітня", "травня", "червня",
    "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"
];

export const STATUS_WORDS: Record<string, string> = {
    "ok": "працює",
    "minor": "часткові збої",
    "major": "тривалі збої",
    "down": "тривалі збої",
    "mnt": "планові роботи",
    "nodata": "немає даних",
};

export function formatLocationLocative(
    locationName?: string | null,
    customLocative?: string | null
): string {
    if (customLocative) {
        const trimmedCustom = customLocative.trim();
        return trimmedCustom.startsWith("у ") || trimmedCustom.startsWith("в ")
            ? trimmedCustom
            : `у ${trimmedCustom}`;
    }
    if (!locationName) return "";
    const trimmed = locationName.trim();
    const prep = /^[аеєиіїоуюя]/i.test(trimmed) ? "в" : "у";
    if (trimmed.endsWith(" район")) {
        const base = trimmed.slice(0, -6);
        const adj = base.endsWith("ий") || base.endsWith("ій") ? base.slice(0, -2) + "ому" : base;
        return `${prep} ${adj} районі`;
    }
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

export function pluralHours(count: number): string {
    if (count % 100 >= 11 && count % 100 <= 14) return "годин";
    const last = count % 10;
    if (last === 1) return "година";
    if (last >= 2 && last <= 4) return "години";
    return "годин";
}

export function formatHourParts(isoDate: string, state: string) {
    const word = STATUS_WORDS[state] || state;
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

export function formatHourTitle(isoDate: string, state: string): string {
    return formatHourParts(isoDate, state).fullTitle;
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

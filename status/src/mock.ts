import { COMPONENTS_SPEC } from "./api";
import { formatHourParts, formatHourTitle, summarizeHours, getKyivParts } from "./helpers";

export function getMockStatusData(scenario: string = "ok", now: Date = new Date()) {
    const WINDOW_HOURS = 24;
    const nowKyiv = getKyivParts(now);
    const currentHourStart = new Date(Math.floor(now.getTime() / (3600 * 1000)) * (3600 * 1000));
    const firstHourStart = new Date(currentHourStart.getTime() - (WINDOW_HOURS - 1) * 3600 * 1000);

    const normScenario = (scenario || "ok").toLowerCase();

    function generateComponentHours(specKey: string): { hours: any[], uptime: number | null, state: string, monitored: boolean } {
        if (normScenario === "unknown") {
            const hours = Array.from({ length: WINDOW_HOURS }, (_, i) => {
                const d = new Date(firstHourStart.getTime() + i * 3600 * 1000);
                const iso = d.toISOString();
                const parts = formatHourParts(iso, "nodata", specKey);
                return {
                    date: iso,
                    state: "nodata",
                    timeText: parts.timeText,
                    statusText: parts.statusText,
                    title: parts.fullTitle
                };
            });
            return { hours, uptime: null, state: "nodata", monitored: false };
        }

        if (normScenario === "mnt") {
            const hours = Array.from({ length: WINDOW_HOURS }, (_, i) => {
                const d = new Date(firstHourStart.getTime() + i * 3600 * 1000);
                const iso = d.toISOString();
                const state = i >= 22 ? "mnt" : "ok";
                const parts = formatHourParts(iso, state, specKey);
                return {
                    date: iso,
                    state,
                    timeText: parts.timeText,
                    statusText: parts.statusText,
                    title: parts.fullTitle
                };
            });
            return { hours, uptime: 99.8, state: "mnt", monitored: true };
        }

        const hours = [];
        let downCount = 0;
        let minorCount = 0;

        for (let i = 0; i < WINDOW_HOURS; i++) {
            const d = new Date(firstHourStart.getTime() + i * 3600 * 1000);
            const iso = d.toISOString();
            let state = "ok";

            if (normScenario === "ok") {
                if (specKey === "map" && i === 15) {
                    state = "minor";
                    minorCount++;
                }
            } else if (normScenario === "map_down") {
                if (specKey === "map" && i >= 22) {
                    state = "down";
                    downCount++;
                }
            } else if (normScenario === "map_api_down") {
                if ((specKey === "map" || specKey === "api") && i >= 21) {
                    state = "down";
                    downCount++;
                }
            } else if (normScenario === "service_down") {
                if ((specKey === "broadcast" || specKey === "source") && i >= 22) {
                    state = "down";
                    downCount++;
                }
            }

            const parts = formatHourParts(iso, state, specKey);
            hours.push({
                date: iso,
                state,
                timeText: parts.timeText,
                statusText: parts.statusText,
                title: parts.fullTitle
            });
        }

        const totalHours = WINDOW_HOURS;
        const healthyRatio = (totalHours - downCount - minorCount * 0.1) / totalHours;
        let uptime: number | null = Math.min(100, Math.max(0, healthyRatio * 100));
        if (downCount === 0 && minorCount === 0) {
            uptime = 100;
        } else if (specKey === "map" && normScenario === "ok") {
            uptime = 99.8;
        }

        const currentState = hours[hours.length - 1].state;
        return { hours, uptime, state: currentState, monitored: true };
    }

    const components = COMPONENTS_SPEC.map(spec => {
        const gen = generateComponentHours(spec.key);
        return {
            key: spec.key,
            name: spec.name,
            desc: spec.desc,
            uptime: gen.uptime,
            hours: gen.hours,
            monitored: gen.monitored,
            state: gen.state,
            outage_since: ["down", "minor"].includes(gen.state) ? new Date(now.getTime() - 2 * 3600 * 1000).toISOString() : null
        };
    });

    let headline = "Усе працює";
    const lastAlertHour = ((nowKyiv.hour - 4 + 24) % 24).toString().padStart(2, "0");
    const lastAlertMin = "12";
    let subtitle = `Усі наші системи працюють у штатному режимі. Останнє сповіщення ми надіслали сьогодні о ${lastAlertHour}:${lastAlertMin} у Білій Церкві. Нових тривог чи відбоїв відтоді не було.`;

    if (normScenario === "unknown") {
        headline = "Немає даних";
        subtitle = "";
    } else if (normScenario === "system_down") {
        headline = "Система не працює";
        subtitle = `Ми тимчасово не надсилаємо сповіщення й не оновлюємо дані. Не покладайтеся зараз на нашу систему — використовуйте застосунок "Повітряна тривога"`;
    } else if (normScenario === "service_down") {
        headline = "Телеграм-канали не працюють";
        subtitle = `Ми тимчасово не можемо надсилати сповіщення, але дані про тривоги ми отримуємо без перебоїв. Перевіряйте тривоги на нашій мапі або в застосунку "Повітряна тривога"`;
    } else if (normScenario === "map_api_down" || normScenario === "map_down") {
        headline = "Мапа тривог не працює";
        subtitle = `У нас тимчасово проблеми з сайтом: мапа тривог може не відкриватися або показувати застарілі дані. Сповіщення ми надсилаємо без перебоїв. Актуальну мапу тривог можна переглянути на alerts.in.ua`;
    } else if (normScenario === "mnt") {
        headline = "Технічні роботи";
        subtitle = "Тривають планові технічні роботи.";
    }

    const mockLastAlertIso = new Date(now.getTime() - 4 * 3600 * 1000).toISOString();
    const telemetry = {
        synced_at: now.toISOString(),
        last_broadcast_at: mockLastAlertIso,
        last_alert: {
            type: "air_raid_alert",
            oblast: "kyiv_oblast",
            district: "bilatserkva",
            city: "Біла Церква",
            locative: "у Білій Церкві",
            timestamp: mockLastAlertIso,
        },
        maintenance: null,
    };

    return {
        headline,
        subtitle,
        components,
        telemetry,
        hour_title: formatHourTitle,
        hours_summary: summarizeHours
    };
}

import { COMPONENTS_SPEC, Severity, StatusData } from "./api";
import { formatHourParts, getKyivParts } from "./helpers";

export function getMockStatusData(scenario: string = "ok", now: Date = new Date()): StatusData {
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
                const parts = formatHourParts(iso, "nodata");
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
                const parts = formatHourParts(iso, state);
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

            const parts = formatHourParts(iso, state);
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
            uptime: gen.uptime,
            hours: gen.hours,
            monitored: gen.monitored,
            state: gen.state,
            outage_since: ["down", "minor"].includes(gen.state) ? new Date(now.getTime() - 2 * 3600 * 1000).toISOString() : null
        };
    });

    let severity: Severity = "none";
    let headline = "Сповіщення працюють";
    const lastAlertHour = ((nowKyiv.hour - 4 + 24) % 24).toString().padStart(2, "0");
    const lastAlertMin = "12";
    let subtitle = `Останнє сповіщення — сьогодні о ${lastAlertHour}:${lastAlertMin} у Білій Церкві. Відтоді тривог не було.`;

    const outageTimeStr = `з ${((nowKyiv.hour - 2 + 24) % 24).toString().padStart(2, "0")}:00`;

    if (normScenario === "unknown") {
        severity = "unknown";
        headline = "Стан невідомий";
        subtitle = "Моніторинг тимчасово не відповідає";
    } else if (normScenario === "service_down") {
        severity = "major";
        headline = "Сервіс не працює";
        subtitle = `Сповіщення не надходять ${outageTimeStr}. Перевіряйте офіційний канал вашої області.`;
    } else if (normScenario === "map_api_down") {
        severity = "minor";
        headline = "Сповіщення працюють, мапа й API — ні";
        subtitle = `Мапа та API недоступні ${outageTimeStr}. Сповіщення в Telegram надходять як зазвичай.`;
    } else if (normScenario === "map_down") {
        severity = "minor";
        headline = "Сповіщення працюють, мапа — ні";
        subtitle = `Мапа недоступна ${outageTimeStr}. Сповіщення в Telegram надходять як зазвичай.`;
    } else if (normScenario === "mnt") {
        severity = "maintenance";
        headline = "Планові роботи";
        subtitle = "Тривають планові технічні роботи.";
    }

    const mockLastAlertIso = new Date(now.getTime() - 4 * 3600 * 1000).toISOString();
    const telemetry = {
        last_broadcast_at: mockLastAlertIso,
        last_alert: {
            type: "air_raid_alert",
            region: "kyiv_oblast",
            district: "bilatserkva",
            district_name: "Біла Церква",
            city_name: "Біла Церква",
            timestamp: mockLastAlertIso,
            message_id: 12345,
            message_link: "https://t.me/sirens_kyiv_obl/12345"
        },
        last_source_message_at: new Date(now.getTime() - 2 * 60 * 1000).toISOString(),
        active_alerts_count: 0,
        source_connected: true,
        updated_at: now.toISOString()
    };

    const outageSince = components.map(c => c.outage_since).filter(Boolean).sort()[0] || null;

    return { headline, subtitle, severity, outage_since: outageSince, components, telemetry };
}

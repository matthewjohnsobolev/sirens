import { Env, COMPONENTS_SPEC, fetchHealthchecks, fetchHealthcheckFlips, fetchUptimeRobot, fetchTelemetry } from "./api";
import { UK_MONTHS, formatHourParts, formatHourTitle, summarizeHours, getKyivParts, formatLocationLocative } from "./helpers";

const WINDOW_HOURS = 24;
const THRESHOLD_MAJOR = 900; // seconds (15 minutes in an hour: long outage / тривалі збої)

function getHourStart(d: Date): Date {
    return new Date(Math.floor(d.getTime() / (3600 * 1000)) * (3600 * 1000));
}

function overlapSeconds(aStart: Date, aEnd: Date, bStart: Date, bEnd: Date): number {
    const start = Math.max(aStart.getTime(), bStart.getTime());
    const end = Math.min(aEnd.getTime(), bEnd.getTime());
    return Math.max(0, (end - start) / 1000);
}

function stateAt(flips: {timestamp: Date, up: number}[], moment: Date, fallbackUp: boolean): boolean {
    let last: number | null = null;
    for (const flip of flips) {
        if (flip.timestamp > moment) break;
        last = flip.up;
    }
    if (last !== null) return last === 1;

    if (flips.length > 0) {
        return flips[0].up === 0 ? true : fallbackUp;
    }
    return fallbackUp;
}

function getDownIntervals(flips: {timestamp: Date, up: number}[], windowStart: Date, now: Date, initialUp: boolean) {
    const intervals: {start: Date, end: Date}[] = [];
    let downSince = initialUp ? null : windowStart;

    for (const flip of flips) {
        if (flip.timestamp <= windowStart) continue;
        if (flip.timestamp > now) break;

        if (flip.up === 0) {
            if (!downSince) downSince = flip.timestamp;
        } else {
            if (downSince) {
                intervals.push({start: downSince, end: flip.timestamp});
                downSince = null;
            }
        }
    }
    if (downSince) {
        intervals.push({start: downSince, end: now});
    }
    return intervals;
}

export async function computeStatusData(env: Env) {
    const now = new Date();
    const nowKyiv = getKyivParts(now);

    // Fetch telemetry from Cloudflare KV
    const telemetry = await fetchTelemetry(env);

    // We anchor 72 hours to the start of the current hour
    const currentHourStart = getHourStart(now);
    const firstHourStart = new Date(currentHourStart.getTime() - (WINDOW_HOURS - 1) * 3600 * 1000);

    const probes: Record<string, any> = {};

    // 1. Fetch Healthchecks
    const checksList = await fetchHealthchecks(env);
    if (checksList) {
        const specs = COMPONENTS_SPEC.filter(c => c.source === "healthchecks");
        for (const spec of specs) {
            let found = null;
            const override = spec.key === "alerts" ? env.HEALTHCHECKS_SLUG_ALERTS_SOURCE : env.HEALTHCHECKS_SLUG_ALERTS_BROADCAST;
            
            if (override) {
                found = checksList.find((c: any) => c.slug?.toLowerCase() === override.toLowerCase());
            }
            if (!found) {
                found = checksList.find((c: any) => c.slug?.toLowerCase() === spec.key.toLowerCase() || c.name?.toLowerCase() === spec.name.toLowerCase());
            }

            if (found) {
                const apiId = found.unique_key || found.uuid;
                const flips = apiId ? await fetchHealthcheckFlips(apiId, env) : [];
                const flipsOk = flips !== null;
                
                let live = "nodata";
                if (found.n_pings > 0) {
                    const s = found.status?.toLowerCase();
                    live = s === "up" ? "ok" : s === "grace" ? "minor" : s === "down" ? "down" : s === "paused" ? "mnt" : "nodata";
                }

                probes[spec.key] = {
                    present: true,
                    live,
                    flips: flips || [],
                    flips_ok: flipsOk,
                    history_start: null,
                    last_ping: found.last_ping
                };
            } else {
                probes[spec.key] = { present: false, live: null, flips: [], flips_ok: false, history_start: null, last_ping: null };
            }
        }
    } else {
        const specs = COMPONENTS_SPEC.filter(c => c.source === "healthchecks");
        for (const spec of specs) probes[spec.key] = null; // API failed entirely
    }

    // 2. Fetch UptimeRobot
    const urSpecs = COMPONENTS_SPEC.filter(c => c.source === "uptimerobot");
    for (const spec of urSpecs) {
        const apiKey = spec.key === "map" ? env.UPTIMEROBOT_SIRENS_WEB_API : env.UPTIMEROBOT_SIRENS_API_API;
        if (!apiKey) {
            probes[spec.key] = { present: false, live: null, flips: [], flips_ok: false, history_start: null, last_ping: null };
            continue;
        }
        const mon = await fetchUptimeRobot(apiKey);
        if (mon) {
            const statusMap: Record<number, string> = {0: "mnt", 1: "nodata", 2: "ok", 8: "minor", 9: "down"};
            probes[spec.key] = {
                present: true,
                live: statusMap[mon.status] || "nodata",
                flips: mon.flips,
                flips_ok: true,
                history_start: mon.create_datetime,
                last_ping: null
            };
        } else {
            probes[spec.key] = null; // API failed entirely
        }
    }

    // Abort if any provider failed entirely to avoid overwriting cache with "nodata"
    if (Object.values(probes).some(p => p === null)) {
        return null;
    }

    const components = [];
    
    // Resolve history start baseline
    let configStart: Date | null = null;
    if (env.STATUS_START_DATE) {
        const [y, m, d] = env.STATUS_START_DATE.split("-").map(Number);
        configStart = new Date(Date.UTC(y, m - 1, d, 0, 0, 0));
    }

    for (const spec of COMPONENTS_SPEC) {
        const probe = probes[spec.key] || { present: false, live: null, flips: [], flips_ok: false, history_start: null };
        
        let historyStart = configStart;
        if (probe.present) {
            const startCandidates = [];
            if (probe.history_start) startCandidates.push(probe.history_start);
            else if (probe.flips && probe.flips.length > 0) startCandidates.push(probe.flips[0].timestamp);
            
            if (startCandidates.length > 0) {
                const earliestObserved = new Date(Math.min(...startCandidates.map(d => d.getTime())));
                if (configStart) {
                    historyStart = new Date(Math.max(configStart.getTime(), earliestObserved.getTime()));
                } else {
                    historyStart = earliestObserved;
                }
            } else {
                historyStart = configStart || now;
            }
        }

        const historyKnown = probe.present && probe.flips_ok && historyStart !== null;
        let windowStart = now;
        let intervals: {start: Date, end: Date}[] = [];
        
        if (historyKnown) {
            windowStart = new Date(Math.max(historyStart!.getTime(), firstHourStart.getTime()));
            const initialUp = stateAt(probe.flips, windowStart, probe.live !== "down");
            intervals = getDownIntervals(probe.flips, windowStart, now, initialUp);
        }

        const hours = [];
        let trackedSeconds = 0;
        let downSeconds = 0;
        let trackedHours = 0;

        for (let i = 0; i < WINDOW_HOURS; i++) {
            const hourStart = new Date(firstHourStart.getTime() + i * 3600 * 1000);
            const hourEnd = new Date(hourStart.getTime() + 3600 * 1000);
            const actualStart = new Date(Math.max(hourStart.getTime(), windowStart.getTime()));
            const actualEnd = new Date(Math.min(hourEnd.getTime(), now.getTime()));
            
            const dateIso = hourStart.toISOString();

            if (!historyKnown || actualEnd <= actualStart) {
                const parts = formatHourParts(dateIso, "nodata");
                hours.push({
                    date: dateIso,
                    state: "nodata",
                    timeText: parts.timeText,
                    statusText: parts.statusText,
                    title: parts.fullTitle
                });
                continue;
            }

            let down = 0;
            for (const {start, end} of intervals) {
                down += overlapSeconds(actualStart, actualEnd, start, end);
            }
            trackedHours++;
            trackedSeconds += (actualEnd.getTime() - actualStart.getTime()) / 1000;
            downSeconds += down;

            let state = "ok";
            if (down >= THRESHOLD_MAJOR) state = "down";
            else if (down > 0) state = "minor";
            
            const parts = formatHourParts(dateIso, state);
            hours.push({
                date: dateIso,
                state,
                timeText: parts.timeText,
                statusText: parts.statusText,
                title: parts.fullTitle
            });
        }

        // Live status override for current hour
        if (probe.live && hours.length > 0) {
            const severity = (s: string) => (s === "down" || s === "major") ? 2 : s === "minor" ? 1 : 0;
            const computed = hours[hours.length - 1].state;
            let finalState = computed;
            if (probe.live === "mnt" || computed === "mnt") {
                finalState = "mnt";
            } else if (probe.live === "nodata" || computed === "nodata") {
                if (computed === "nodata") finalState = probe.live;
            } else if (severity(probe.live) > severity(computed)) {
                finalState = probe.live === "major" ? "down" : probe.live;
            }
            hours[hours.length - 1].state = finalState;
            const updatedParts = formatHourParts(hours[hours.length - 1].date, finalState);
            hours[hours.length - 1].timeText = updatedParts.timeText;
            hours[hours.length - 1].statusText = updatedParts.statusText;
            hours[hours.length - 1].title = updatedParts.fullTitle;
        }

        const uptimePct = trackedSeconds > 0 ? Math.max(0, Math.min(100, ((trackedSeconds - downSeconds) / trackedSeconds) * 100)) : null;

        let outageSince = null;
        if (intervals.length > 0 && intervals[intervals.length - 1].end >= now) {
            outageSince = intervals[intervals.length - 1].start.toISOString();
        } else if (["down", "major", "minor"].includes(probe.live)) {
            if (probe.flips.length > 0 && probe.flips[probe.flips.length - 1].up === 0) {
                outageSince = probe.flips[probe.flips.length - 1].timestamp.toISOString();
            } else {
                outageSince = now.toISOString();
            }
        }

        components.push({
            key: spec.key,
            name: spec.name,
            uptime: uptimePct,
            hours,
            monitored: probe.present,
            state: hours.length > 0 ? hours[hours.length - 1].state : "nodata",
            outage_since: outageSince
        });
    }

    const monitored = components.filter(c => c.monitored);
    let headline = "Сповіщення працюють";
    let subtitle = "Сповіщення в Telegram надходять як зазвичай.";

    const formatSince = (dtStr: string | null) => {
        if (!dtStr) return "";
        const dt = new Date(dtStr);
        if (isNaN(dt.getTime())) return "";
        const p = getKyivParts(dt);
        
        const isToday = p.year === nowKyiv.year && p.month === nowKyiv.month && p.day === nowKyiv.day;
        const hh = p.hour.toString().padStart(2, '0');
        const mm = p.minute.toString().padStart(2, '0');
        if (isToday) return ` з ${hh}:${mm}`;
        return ` з ${p.day} ${UK_MONTHS[p.month]}, ${hh}:${mm}`;
    };

    const coreFailing = components.filter(c => (c.key === "alerts" || c.key === "tg") && ["down", "major", "minor"].includes(c.state) && c.monitored);
    const auxFailing = components.filter(c => (c.key === "map" || c.key === "api") && ["down", "major", "minor"].includes(c.state) && c.monitored);

    let lastAlertDt: Date | null = null;
    let lastAlertLocation: string | null = null;
    if (telemetry?.last_alert?.timestamp) {
        const parsed = new Date(telemetry.last_alert.timestamp);
        if (!isNaN(parsed.getTime())) {
            lastAlertDt = parsed;
            lastAlertLocation = telemetry.last_alert.city_name || telemetry.last_alert.district_name || null;
        }
    } else if (telemetry?.last_broadcast_at) {
        const parsed = new Date(telemetry.last_broadcast_at);
        if (!isNaN(parsed.getTime())) {
            lastAlertDt = parsed;
        }
    }

    if (!monitored.length || monitored.every(c => c.state === "nodata")) {
        headline = "Стан невідомий";
        subtitle = "Моніторинг не відповідає";
    } else if (coreFailing.length > 0) {
        const dts = coreFailing.map(c => c.outage_since).filter(Boolean);
        const earliest = dts.length ? dts.sort()[0] : null;
        headline = "Сервіс не працює";
        subtitle = `Сповіщення не надходять${formatSince(earliest)}. Перевіряйте офіційний канал вашої області.`;
    } else if (auxFailing.length > 0) {
        const keys = new Set(auxFailing.map(c => c.key));
        const dts = auxFailing.map(c => c.outage_since).filter(Boolean);
        const earliest = dts.length ? dts.sort()[0] : null;
        const timeStr = formatSince(earliest);

        if (keys.has("map") && keys.has("api")) {
            headline = "Сповіщення працюють, мапа й API — ні";
            subtitle = `Мапа та API недоступні${timeStr}. Сповіщення в Telegram надходять як зазвичай.`;
        } else if (keys.has("map")) {
            headline = "Сповіщення працюють, мапа — ні";
            subtitle = `Мапа недоступна${timeStr}. Сповіщення в Telegram надходять як зазвичай.`;
        } else {
            headline = "Сповіщення працюють, API — ні";
            subtitle = `API недоступний${timeStr}. Сповіщення в Telegram надходять як зазвичай.`;
        }
    } else if (monitored.some(c => c.state === "mnt")) {
        headline = "Планові роботи";
        subtitle = "Тривають планові технічні роботи.";
    } else {
        if (lastAlertDt && !isNaN(lastAlertDt.getTime())) {
            const p = getKyivParts(lastAlertDt);
            const isToday = p.year === nowKyiv.year && p.month === nowKyiv.month && p.day === nowKyiv.day;
            const dateStr = isToday ? "сьогодні" : `${p.day} ${UK_MONTHS[p.month]}`;
            const hh = p.hour.toString().padStart(2, '0');
            const mm = p.minute.toString().padStart(2, '0');
            const locPhrase = formatLocationLocative(
                telemetry?.last_alert?.district,
                telemetry?.last_alert?.city_name || telemetry?.last_alert?.district_name,
                (telemetry?.last_alert as any)?.location_title
            );
            const locSuffix = locPhrase ? ` ${locPhrase}` : "";
            subtitle = `Останнє сповіщення — ${dateStr} о ${hh}:${mm}${locSuffix}. Відтоді тривог не було.`;
        } else {
            subtitle = "Сповіщення в Telegram надходять як зазвичай.";
        }
    }

    return {
        headline,
        subtitle,
        components,
        telemetry,
        hour_title: formatHourTitle,
        hours_summary: summarizeHours
    };
}

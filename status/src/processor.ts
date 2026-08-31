import {
    COMPONENTS_SPEC,
    Env,
    Flip,
    Severity,
    StatusComponent,
    StatusData,
    fetchHealthcheckFlips,
    fetchHealthchecks,
    fetchTelemetry,
    fetchUptimeRobot,
    healthchecksSlug,
    uptimeRobotKey,
} from "./api";
import { UK_MONTHS, formatHourParts, getKyivParts, formatLocationLocative } from "./helpers";

const WINDOW_HOURS = 24;
const THRESHOLD_MAJOR = 900;
const FAILING_STATES = ["down", "major", "minor"];
const CORE_KEYS = ["source", "broadcast"];
const AUX_KEYS = ["map", "api"];

interface Probe {
    present: boolean;
    stale: boolean;
    live: string | null;
    flips: Flip[];
    flips_ok: boolean;
    history_start: Date | null;
}

function missingProbe(): Probe {
    return { present: false, stale: false, live: null, flips: [], flips_ok: false, history_start: null };
}

function staleProbe(configured: boolean): Probe {
    return { present: configured, stale: true, live: null, flips: [], flips_ok: false, history_start: null };
}

export function getHourStart(d: Date): Date {
    return new Date(Math.floor(d.getTime() / (3600 * 1000)) * (3600 * 1000));
}

export function overlapSeconds(aStart: Date, aEnd: Date, bStart: Date, bEnd: Date): number {
    const start = Math.max(aStart.getTime(), bStart.getTime());
    const end = Math.min(aEnd.getTime(), bEnd.getTime());
    return Math.max(0, (end - start) / 1000);
}

export function stateAt(flips: Flip[], moment: Date, fallbackUp: boolean): boolean {
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

export function getDownIntervals(flips: Flip[], windowStart: Date, now: Date, initialUp: boolean) {
    const intervals: { start: Date, end: Date }[] = [];
    let downSince = initialUp ? null : windowStart;

    for (const flip of flips) {
        if (flip.timestamp <= windowStart) continue;
        if (flip.timestamp > now) break;

        if (flip.up === 0) {
            if (!downSince) downSince = flip.timestamp;
        } else {
            if (downSince) {
                intervals.push({ start: downSince, end: flip.timestamp });
                downSince = null;
            }
        }
    }
    if (downSince) {
        intervals.push({ start: downSince, end: now });
    }
    return intervals;
}

function liveStateFromCheck(check: any): string {
    if (!(check.n_pings > 0)) return "nodata";
    const s = check.status?.toLowerCase();
    return s === "up" ? "ok"
        : s === "grace" ? "minor"
        : s === "down" ? "down"
        : s === "paused" ? "mnt"
        : "nodata";
}

async function collectHealthchecksProbes(env: Env): Promise<Record<string, Probe>> {
    const specs = COMPONENTS_SPEC.filter(c => c.source === "healthchecks");
    const probes: Record<string, Probe> = {};
    const checksList = await fetchHealthchecks(env);

    if (checksList === null) {
        for (const spec of specs) {
            probes[spec.key] = staleProbe(Boolean(healthchecksSlug(env, spec.key)));
        }
        return probes;
    }

    const matched = specs.map(spec => {
        const override = healthchecksSlug(env, spec.key);
        const byOverride = override
            ? checksList.find((c: any) => c.slug?.toLowerCase() === override.toLowerCase())
            : null;
        return byOverride || checksList.find((c: any) =>
            c.slug?.toLowerCase() === spec.key.toLowerCase()
            || c.name?.toLowerCase() === spec.name.toLowerCase()) || null;
    });

    const flipResults = await Promise.all(matched.map(check => {
        const apiId = check ? (check.unique_key || check.uuid) : null;
        return apiId ? fetchHealthcheckFlips(apiId, env) : Promise.resolve<Flip[]>([]);
    }));

    specs.forEach((spec, i) => {
        const check = matched[i];
        if (!check) {
            probes[spec.key] = missingProbe();
            return;
        }
        const flips = flipResults[i];
        probes[spec.key] = {
            present: true,
            stale: false,
            live: liveStateFromCheck(check),
            flips: flips || [],
            flips_ok: flips !== null,
            history_start: null,
        };
    });

    return probes;
}

async function collectUptimeRobotProbes(env: Env): Promise<Record<string, Probe>> {
    const specs = COMPONENTS_SPEC.filter(c => c.source === "uptimerobot");
    const statusMap: Record<number, string> = { 0: "mnt", 1: "nodata", 2: "ok", 8: "minor", 9: "down" };
    const probes: Record<string, Probe> = {};

    const monitors = await Promise.all(specs.map(spec => {
        const apiKey = uptimeRobotKey(env, spec.key);
        return apiKey ? fetchUptimeRobot(apiKey) : Promise.resolve(undefined);
    }));

    specs.forEach((spec, i) => {
        const mon = monitors[i];
        if (mon === undefined) {
            probes[spec.key] = missingProbe();
        } else if (mon === null) {
            probes[spec.key] = staleProbe(true);
        } else {
            probes[spec.key] = {
                present: true,
                stale: false,
                live: statusMap[mon.status] || "nodata",
                flips: mon.flips,
                flips_ok: true,
                history_start: mon.create_datetime,
            };
        }
    });

    return probes;
}

function buildComponent(
    spec: { key: string, name: string },
    probe: Probe,
    configStart: Date | null,
    firstHourStart: Date,
    now: Date
): StatusComponent {
    let historyStart = configStart;
    if (probe.present) {
        const startCandidates: Date[] = [];
        if (probe.history_start) startCandidates.push(probe.history_start);
        else if (probe.flips.length > 0) startCandidates.push(probe.flips[0].timestamp);

        if (startCandidates.length > 0) {
            const earliestObserved = new Date(Math.min(...startCandidates.map(d => d.getTime())));
            historyStart = configStart
                ? new Date(Math.max(configStart.getTime(), earliestObserved.getTime()))
                : earliestObserved;
        } else {
            historyStart = configStart || now;
        }
    }

    const historyKnown = probe.present && !probe.stale && probe.flips_ok && historyStart !== null;
    let windowStart = now;
    let intervals: { start: Date, end: Date }[] = [];

    if (historyKnown) {
        windowStart = new Date(Math.max(historyStart!.getTime(), firstHourStart.getTime()));
        const initialUp = stateAt(probe.flips, windowStart, probe.live !== "down");
        intervals = getDownIntervals(probe.flips, windowStart, now, initialUp);
    }

    const intervalStates = intervals.map(({ start, end }) => ({
        start,
        end,
        isDown: (end.getTime() - start.getTime()) / 1000 >= THRESHOLD_MAJOR
    }));

    const hours = [];
    let trackedSeconds = 0;
    let downSeconds = 0;

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
        let hasDownInterval = false;
        for (const interval of intervalStates) {
            const overlap = overlapSeconds(actualStart, actualEnd, interval.start, interval.end);
            down += overlap;
            if (overlap > 0 && interval.isDown) hasDownInterval = true;
        }
        trackedSeconds += (actualEnd.getTime() - actualStart.getTime()) / 1000;
        downSeconds += down;

        const state = hasDownInterval ? "down" : down > 0 ? "minor" : "ok";
        const parts = formatHourParts(dateIso, state);
        hours.push({
            date: dateIso,
            state,
            timeText: parts.timeText,
            statusText: parts.statusText,
            title: parts.fullTitle
        });
    }

    if (probe.live && !probe.stale) {
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

    const uptime = trackedSeconds > 0
        ? Math.max(0, Math.min(100, ((trackedSeconds - downSeconds) / trackedSeconds) * 100))
        : null;

    let outageSince: string | null = null;
    if (intervals.length > 0 && intervals[intervals.length - 1].end >= now) {
        outageSince = intervals[intervals.length - 1].start.toISOString();
    } else if (probe.live && FAILING_STATES.includes(probe.live)) {
        outageSince = probe.flips.length > 0 && probe.flips[probe.flips.length - 1].up === 0
            ? probe.flips[probe.flips.length - 1].timestamp.toISOString()
            : now.toISOString();
    }

    return {
        key: spec.key,
        name: spec.name,
        uptime,
        hours,
        monitored: probe.present,
        state: hours[hours.length - 1].state,
        outage_since: outageSince
    };
}

function earliestOutage(components: StatusComponent[]): string | null {
    const stamps = components.map(c => c.outage_since).filter(Boolean) as string[];
    return stamps.length ? stamps.sort()[0] : null;
}

export async function computeStatusData(env: Env): Promise<StatusData | null> {
    const now = new Date();
    const nowKyiv = getKyivParts(now);

    const [telemetry, healthchecksProbes, uptimeRobotProbes] = await Promise.all([
        fetchTelemetry(env),
        collectHealthchecksProbes(env),
        collectUptimeRobotProbes(env),
    ]);

    const probes: Record<string, Probe> = { ...healthchecksProbes, ...uptimeRobotProbes };

    if (!COMPONENTS_SPEC.some(spec => probes[spec.key].present && !probes[spec.key].stale)) {
        return null;
    }

    const currentHourStart = getHourStart(now);
    const firstHourStart = new Date(currentHourStart.getTime() - (WINDOW_HOURS - 1) * 3600 * 1000);

    let configStart: Date | null = null;
    if (env.STATUS_START_DATE) {
        const [y, m, d] = env.STATUS_START_DATE.split("-").map(Number);
        configStart = new Date(Date.UTC(y, m - 1, d, 0, 0, 0));
    }

    const components = COMPONENTS_SPEC.map(spec =>
        buildComponent(spec, probes[spec.key], configStart, firstHourStart, now));

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

    const monitored = components.filter(c => c.monitored);
    const isFailing = (c: StatusComponent) => c.monitored && FAILING_STATES.includes(c.state);
    const coreFailing = components.filter(c => CORE_KEYS.includes(c.key) && isFailing(c));
    const auxFailing = components.filter(c => AUX_KEYS.includes(c.key) && isFailing(c));
    const coreStale = CORE_KEYS.some(key => probes[key].present && probes[key].stale);

    let lastAlertDt: Date | null = null;
    if (telemetry?.last_alert?.timestamp) {
        const parsed = new Date(telemetry.last_alert.timestamp);
        if (!isNaN(parsed.getTime())) lastAlertDt = parsed;
    } else if (telemetry?.last_broadcast_at) {
        const parsed = new Date(telemetry.last_broadcast_at);
        if (!isNaN(parsed.getTime())) lastAlertDt = parsed;
    }

    let headline = "Сповіщення працюють";
    let subtitle = "Сповіщення в Telegram надходять як зазвичай.";
    let severity: Severity = "none";
    let outageSince: string | null = null;

    if (!monitored.length || monitored.every(c => c.state === "nodata")) {
        headline = "Стан невідомий";
        subtitle = "Моніторинг не відповідає";
        severity = "unknown";
    } else if (coreFailing.length > 0) {
        outageSince = earliestOutage(coreFailing);
        headline = "Сервіс не працює";
        subtitle = `Сповіщення не надходять${formatSince(outageSince)}. Перевіряйте офіційний канал вашої області.`;
        severity = "major";
    } else if (coreStale) {
        headline = "Стан невідомий";
        subtitle = "Моніторинг не відповідає";
        severity = "unknown";
    } else if (auxFailing.length > 0) {
        const keys = new Set(auxFailing.map(c => c.key));
        outageSince = earliestOutage(auxFailing);
        const timeStr = formatSince(outageSince);
        severity = "minor";

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
        severity = "maintenance";
    } else if (lastAlertDt) {
        const p = getKyivParts(lastAlertDt);
        const isToday = p.year === nowKyiv.year && p.month === nowKyiv.month && p.day === nowKyiv.day;
        const dateStr = isToday ? "сьогодні" : `${p.day} ${UK_MONTHS[p.month]}`;
        const hh = p.hour.toString().padStart(2, '0');
        const mm = p.minute.toString().padStart(2, '0');
        const locPhrase = formatLocationLocative(
            telemetry?.last_alert?.city_name || telemetry?.last_alert?.district_name,
            telemetry?.last_alert?.location_title
        );
        const locSuffix = locPhrase ? ` ${locPhrase}` : "";
        subtitle = `Останнє сповіщення — ${dateStr} о ${hh}:${mm}${locSuffix}. Відтоді тривог не було.`;
    }

    return { headline, subtitle, severity, outage_since: outageSince, components, telemetry };
}

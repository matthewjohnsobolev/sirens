import { Env, COMPONENTS_SPEC, fetchHealthchecks, fetchHealthcheckFlips, fetchUptimeRobot, fetchTelemetry, fetchMaintenance, healthchecksSlug, uptimeRobotKey, MaintenanceWindowData } from "./api";
import { UK_MONTHS, formatHourParts, formatHourTitle, summarizeHours, getKyivParts, formatLocationLocative, relativeDayLabel } from "./helpers";

const WINDOW_HOURS = 24;
const THRESHOLD_MAJOR = 900;

interface Probe {
    present: boolean;
    live: string | null;
    flips: { timestamp: Date; up: number }[];
    flips_ok: boolean;
    history_start: Date | null;
    last_ping: string | null;
}

// Провайдер налаштований, але не відповів. Це не те саме, що «не налаштовано»:
// present:true лишає компонент у списку, flips_ok:false робить усі смужки
// порожніми, live:null не дає перебити їх живим станом. Відмова одного
// провайдера гасить тільки його компоненти, решта сторінки живе далі.
function unreachable(): Probe {
    return { present: true, live: null, flips: [], flips_ok: false, history_start: null, last_ping: null };
}

// Компонент, для якого моніторинг не заведено взагалі.
function notConfigured(): Probe {
    return { present: false, live: null, flips: [], flips_ok: false, history_start: null, last_ping: null };
}

async function collectHealthchecks(specs: typeof COMPONENTS_SPEC, env: Env): Promise<(readonly [string, Probe])[]> {
    const checksList = await fetchHealthchecks(env);

    // fetchHealthchecks віддає [] коли ключа немає, тож null означає саме
    // «ключ є, але API не відповів».
    if (!checksList) return specs.map(spec => [spec.key, unreachable()] as const);

    return Promise.all(specs.map(async spec => {
        const override = healthchecksSlug(env, spec.key);

        let found = null;
        if (override) {
            found = checksList.find((c: any) => c.slug?.toLowerCase() === override.toLowerCase());
        }
        if (!found) {
            found = checksList.find((c: any) => c.slug?.toLowerCase() === spec.key.toLowerCase() || c.name?.toLowerCase() === spec.name.toLowerCase());
        }
        if (!found) return [spec.key, notConfigured()] as const;

        const apiId = found.unique_key || found.uuid;
        const flips = apiId ? await fetchHealthcheckFlips(apiId, env) : [];

        let live = "nodata";
        if (found.n_pings > 0) {
            const s = found.status?.toLowerCase();
            live = s === "up" ? "ok" : (s === "grace" || s === "down") ? "down" : s === "paused" ? "mnt" : "nodata";
        }

        return [spec.key, {
            present: true,
            live,
            flips: flips || [],
            flips_ok: flips !== null,
            history_start: null,
            last_ping: found.last_ping
        }] as const;
    }));
}

async function collectUptimeRobot(specs: typeof COMPONENTS_SPEC, env: Env): Promise<(readonly [string, Probe])[]> {
    const statusMap: Record<number, string> = {0: "mnt", 1: "nodata", 2: "ok", 8: "minor", 9: "down"};

    return Promise.all(specs.map(async spec => {
        const apiKey = uptimeRobotKey(env, spec.key);
        if (!apiKey) return [spec.key, notConfigured()] as const;

        const mon = await fetchUptimeRobot(apiKey);
        if (!mon) return [spec.key, unreachable()] as const;

        return [spec.key, {
            present: true,
            live: statusMap[mon.status] || "nodata",
            flips: mon.flips,
            flips_ok: true,
            history_start: mon.create_datetime,
            last_ping: null
        }] as const;
    }));
}

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

    const [telemetry, maintenance] = await Promise.all([
        fetchTelemetry(env),
        fetchMaintenance(env)
    ]);

    const activeMaintenance = (maintenance && maintenance.active)
        ? maintenance
        : (telemetry?.maintenance && telemetry.maintenance.active)
            ? telemetry.maintenance
            : null;

    const rawWindows = ((maintenance?.windows || telemetry?.maintenance?.windows || []) as MaintenanceWindowData[]);
    const allWindows: MaintenanceWindowData[] = [...rawWindows];
    if (activeMaintenance && activeMaintenance.active) {
        const activeId = activeMaintenance.id || "active";
        if (!allWindows.some(w => w.id === activeId)) {
            allWindows.push({
                id: activeId,
                components: activeMaintenance.components || ["all"],
                start_iso: activeMaintenance.start_iso,
                end_iso: activeMaintenance.end_iso,
                completed: false
            });
        }
    }

    const mntAppliesToComp = (key: string) => {
        if (!activeMaintenance) return false;
        const comps = activeMaintenance.components || ["all"];
        return comps.includes("all") || comps.includes(key);
    };

    const currentHourStart = getHourStart(now);
    const firstHourStart = new Date(currentHourStart.getTime() - (WINDOW_HOURS - 1) * 3600 * 1000);

    const probes: Record<string, any> = {};

    // Обидва провайдери опитуються паралельно: послідовно це до шести
    // round-trip на кожен холодний рендер.
    const [hcProbes, urProbes] = await Promise.all([
        collectHealthchecks(COMPONENTS_SPEC.filter(c => c.source === "healthchecks"), env),
        collectUptimeRobot(COMPONENTS_SPEC.filter(c => c.source === "uptimerobot"), env)
    ]);
    for (const [key, probe] of [...hcProbes, ...urProbes]) probes[key] = probe;

    const components = [];
    
    const lastSyncStr = telemetry?.synced_at || telemetry?.last_source_sync_at || telemetry?.updated_at;
    let isSourceStale = false;
    if (lastSyncStr) {
        const syncDate = new Date(lastSyncStr);
        if (!isNaN(syncDate.getTime())) {
            const staleMinutes = (now.getTime() - syncDate.getTime()) / 60000;
            if (staleMinutes > 20) {
                isSourceStale = true;
            }
        }
    }

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

        const compMntWindows = allWindows.filter(w => {
            const comps = w.components || ["all"];
            return comps.includes("all") || comps.includes(spec.key);
        });

        const mntIntervals: { start: Date; end: Date; completed: boolean }[] = [];
        for (const w of compMntWindows) {
            let wStart: Date | null = null;
            let wEnd: Date | null = null;
            if (w.start_epoch) {
                wStart = new Date(w.start_epoch * 1000);
            } else if (w.start_iso) {
                wStart = new Date(w.start_iso);
            }
            if (w.completed && w.completed_at) {
                wEnd = new Date(w.completed_at * 1000);
            } else if (w.completed && w.end_epoch) {
                wEnd = new Date(w.end_epoch * 1000);
            } else if (w.end_epoch) {
                wEnd = new Date(w.end_epoch * 1000);
            } else if (w.end_iso) {
                wEnd = new Date(w.end_iso);
            } else if (!w.completed) {
                wEnd = now;
            }
            if (wStart && wEnd && !isNaN(wStart.getTime()) && !isNaN(wEnd.getTime()) && wEnd > wStart) {
                mntIntervals.push({ start: wStart, end: wEnd, completed: Boolean(w.completed) });
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

        const intervalStates = intervals.map(({start, end}) => ({
            start,
            end,
            isDown: (end.getTime() - start.getTime()) / 1000 >= THRESHOLD_MAJOR
        }));

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

            let mntSec = 0;
            for (const mnt of mntIntervals) {
                mntSec += overlapSeconds(actualStart, actualEnd, mnt.start, mnt.end);
            }
            const isMntHour = mntSec > 0 && actualEnd > actualStart;

            if (!historyKnown || actualEnd <= actualStart) {
                if (isMntHour) {
                    const parts = formatHourParts(dateIso, "mnt", spec.key);
                    hours.push({
                        date: dateIso,
                        state: "mnt",
                        timeText: parts.timeText,
                        statusText: parts.statusText,
                        title: parts.fullTitle
                    });
                    trackedHours++;
                    trackedSeconds += (actualEnd.getTime() - actualStart.getTime()) / 1000;
                    continue;
                }
                const parts = formatHourParts(dateIso, "nodata", spec.key);
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
                let mntDowntime = 0;
                for (const mnt of mntIntervals) {
                    const subStart = new Date(Math.max(actualStart.getTime(), interval.start.getTime()));
                    const subEnd = new Date(Math.min(actualEnd.getTime(), interval.end.getTime()));
                    mntDowntime += overlapSeconds(subStart, subEnd, mnt.start, mnt.end);
                }
                const netDown = Math.max(0, overlap - mntDowntime);
                down += netDown;
                if (netDown > 0 && interval.isDown) hasDownInterval = true;
            }
            trackedHours++;
            trackedSeconds += (actualEnd.getTime() - actualStart.getTime()) / 1000;
            downSeconds += down;

            let state = "ok";
            if (hasDownInterval) state = "down";
            else if (down > 0) state = "minor";
            else if (isMntHour) state = "mnt";

            const parts = formatHourParts(dateIso, state, spec.key);
            hours.push({
                date: dateIso,
                state,
                timeText: parts.timeText,
                statusText: parts.statusText,
                title: parts.fullTitle
            });
        }

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
            const updatedParts = formatHourParts(hours[hours.length - 1].date, finalState, spec.key);
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

        let compState = hours.length > 0 ? hours[hours.length - 1].state : "nodata";
        if (mntAppliesToComp(spec.key)) {
            compState = "mnt";
            outageSince = null;
            if (hours.length > 0) {
                hours[hours.length - 1].state = "mnt";
                const updatedParts = formatHourParts(hours[hours.length - 1].date, "mnt", spec.key);
                hours[hours.length - 1].timeText = updatedParts.timeText;
                hours[hours.length - 1].statusText = updatedParts.statusText;
                hours[hours.length - 1].title = updatedParts.fullTitle;
            }
        } else if (compState === "mnt") {
            compState = (probe.live && probe.live !== "mnt") ? probe.live : "ok";
        } else if (spec.key === "source" && isSourceStale) {
            compState = "down";
            if (!outageSince && lastSyncStr) {
                outageSince = new Date(lastSyncStr).toISOString();
            }
            if (hours.length > 0) {
                hours[hours.length - 1].state = "down";
                const updatedParts = formatHourParts(hours[hours.length - 1].date, "down", spec.key);
                hours[hours.length - 1].timeText = updatedParts.timeText;
                hours[hours.length - 1].statusText = updatedParts.statusText;
                hours[hours.length - 1].title = updatedParts.fullTitle;
            }
        }

        components.push({
            key: spec.key,
            name: spec.name,
            desc: spec.desc,
            uptime: uptimePct,
            hours,
            monitored: probe.present || Boolean(activeMaintenance) || compMntWindows.length > 0 || (spec.key === "source" && Boolean(lastSyncStr)),
            state: compState,
            outage_since: outageSince
        });
    }

    const monitored = components.filter(c => c.monitored);

    const compSource = components.find(c => c.key === "source");
    const compBroadcast = components.find(c => c.key === "broadcast");
    const compMap = components.find(c => c.key === "map");
    const compApi = components.find(c => c.key === "api");

    const isFail = (c: any) => Boolean(c && c.monitored && (c.state === "down" || c.state === "major" || c.state === "minor"));

    const sourceFail = isFail(compSource);
    const broadcastFail = isFail(compBroadcast);
    const mapFail = isFail(compMap);
    const apiFail = isFail(compApi);

    const telegramAlive = !sourceFail && !broadcastFail;
    const webAlive = !mapFail && !apiFail;

    const hasMaintenance = Boolean(activeMaintenance) || monitored.some(c => c.state === "mnt");

    const formatSince = (dtStr: string | null) => {
        if (!dtStr) return "";
        const dt = new Date(dtStr);
        if (isNaN(dt.getTime())) return "";
        const p = getKyivParts(dt);

        const dayLabel = relativeDayLabel(p, nowKyiv);
        const hh = p.hour.toString().padStart(2, '0');
        const mm = p.minute.toString().padStart(2, '0');
        if (dayLabel === "сьогодні") return ` з ${hh}:${mm}`;
        if (dayLabel === "вчора") return ` з вчора, ${hh}:${mm}`;
        return ` з ${p.day} ${UK_MONTHS[p.month]}, ${hh}:${mm}`;
    };

    let lastAlertDt: Date | null = null;
    if (telemetry?.last_alert?.timestamp) {
        const parsed = new Date(telemetry.last_alert.timestamp);
        if (!isNaN(parsed.getTime())) {
            lastAlertDt = parsed;
        }
    } else if (telemetry?.last_broadcast_at) {
        const parsed = new Date(telemetry.last_broadcast_at);
        if (!isNaN(parsed.getTime())) {
            lastAlertDt = parsed;
        }
    }

    let headline = "Усе працює";
    let subtitle = "Розсилка в Telegram надходить як зазвичай.";

    if (hasMaintenance) {
        headline = activeMaintenance?.headline || "Технічні роботи";
        subtitle = activeMaintenance?.subtitle || "Тривають планові технічні роботи.";
    } else if (!monitored.length || monitored.every(c => c.state === "nodata")) {
        headline = "Немає даних";
        subtitle = "";
    } else if (!telegramAlive && !webAlive) {
        const allFailing = components.filter(c => isFail(c));
        const dts = allFailing.map(c => c.outage_since).filter(Boolean);
        const earliest = dts.length ? dts.sort()[0] : null;
        headline = "Система не працює";
        subtitle = `Не працюють${formatSince(earliest)}. Ми вже лагодимо. Поки що орієнтуйтесь на офіційний канал вашої області.`;
    } else if (!telegramAlive && webAlive) {
        const tgFailing = [compSource, compBroadcast].filter(c => isFail(c));
        const dts = tgFailing.map(c => c?.outage_since).filter(Boolean);
        const earliest = dts.length ? dts.sort()[0] : null;
        headline = "Телеграм-канали не працюють";
        subtitle = `Не працюють${formatSince(earliest)}. Ми вже лагодимо. Поки що орієнтуйтесь на офіційний канал вашої області.`;
    } else if (telegramAlive && !webAlive) {
        const webFailing = [compMap, compApi].filter(c => isFail(c));
        const dts = webFailing.map(c => c?.outage_since).filter(Boolean);
        const earliest = dts.length ? dts.sort()[0] : null;
        const timeStr = formatSince(earliest);

        headline = "Мапа тривог не працює";
        if (mapFail && apiFail) {
            subtitle = `Мапа та API недоступні${timeStr}. Розсилка в Telegram надходить як зазвичай.`;
        } else if (mapFail) {
            subtitle = `Мапа недоступна${timeStr}. Розсилка в Telegram надходить як зазвичай.`;
        } else {
            subtitle = `API недоступний${timeStr}. Розсилка в Telegram надходить як зазвичай.`;
        }
    } else {
        headline = "Усе працює";
        if (lastAlertDt && !isNaN(lastAlertDt.getTime())) {
            const p = getKyivParts(lastAlertDt);
            const dateStr = relativeDayLabel(p, nowKyiv) ?? `${p.day} ${UK_MONTHS[p.month]}`;
            const hh = p.hour.toString().padStart(2, '0');
            const mm = p.minute.toString().padStart(2, '0');
            const locPhrase = telemetry?.last_alert?.locative || formatLocationLocative(
                telemetry?.last_alert?.district,
                telemetry?.last_alert?.city || telemetry?.last_alert?.city_name || telemetry?.last_alert?.district_name,
                (telemetry?.last_alert as any)?.location_title
            );
            const locSuffix = locPhrase ? ` ${locPhrase}` : "";
            subtitle = `Останнє сповіщення ми надіслали ${dateStr} о ${hh}:${mm}${locSuffix}. Відтоді тривог чи відбоїв не було.`;
        } else {
            subtitle = "Розсилка в Telegram надходить як зазвичай.";
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

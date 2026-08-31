export interface Env {
    HEALTHCHECKS_API_KEY?: string;
    HEALTHCHECKS_ALERTS_SOURCE_SLUG?: string;
    HEALTHCHECKS_ALERTS_BROADCAST_SLUG?: string;
    UPTIMEROBOT_WEB_MONITOR_KEY?: string;
    UPTIMEROBOT_API_MONITOR_KEY?: string;
    STATUS_START_DATE?: string;
    ENVIRONMENT?: string;
    TELEMETRY?: KVNamespace;
}

export type Severity = "none" | "minor" | "major" | "maintenance" | "unknown";

export function healthchecksSlug(env: Env, componentKey: string): string | undefined {
    return componentKey === "source"
        ? env.HEALTHCHECKS_ALERTS_SOURCE_SLUG
        : env.HEALTHCHECKS_ALERTS_BROADCAST_SLUG;
}

export function uptimeRobotKey(env: Env, componentKey: string): string | undefined {
    return componentKey === "map"
        ? env.UPTIMEROBOT_WEB_MONITOR_KEY
        : env.UPTIMEROBOT_API_MONITOR_KEY;
}

export interface TelemetryAlert {
    type: string;
    region?: string;
    district?: string;
    district_name?: string;
    city_name?: string;
    location_title?: string;
    timestamp: string;
    message_id?: number | null;
    message_link?: string | null;
    source_type?: string;
}

export interface TelemetryData {
    last_broadcast_at?: string | null;
    last_alert?: TelemetryAlert | null;
    last_source_message_at?: string | null;
    last_primary_message_at?: string | null;
    last_fallback_message_at?: string | null;
    active_source?: string;
    active_alerts_count?: number;
    source_connected?: boolean;
    updated_at?: string;
}

export interface StatusHour {
    date: string;
    state: string;
    timeText: string;
    statusText: string;
    title: string;
}

export interface StatusComponent {
    key: string;
    name: string;
    uptime: number | null;
    hours: StatusHour[];
    monitored: boolean;
    state: string;
    outage_since: string | null;
}

export interface StatusData {
    headline: string;
    subtitle: string;
    severity: Severity;
    outage_since: string | null;
    components: StatusComponent[];
    telemetry?: TelemetryData | null;
    snapshot_at?: string;
}

export interface Flip {
    timestamp: Date;
    up: number;
}

export const COMPONENTS_SPEC = [
    { key: "broadcast", name: "Канали Telegram", source: "healthchecks" },
    { key: "source", name: "Обробка тривог", source: "healthchecks" },
    { key: "map", name: "Мапа тривог", source: "uptimerobot" },
    { key: "api", name: "API", source: "uptimerobot" },
];

const LAST_GOOD_KEY = "status:last_good";

export async function fetchTelemetry(env: Env): Promise<TelemetryData | null> {
    if (!env.TELEMETRY) return null;
    try {
        return await env.TELEMETRY.get<TelemetryData>("telemetry:latest", "json");
    } catch (e) {
        console.warn("Failed to fetch telemetry from KV:", e);
        return null;
    }
}

export async function putLastGoodStatus(env: Env, data: StatusData): Promise<void> {
    if (!env.TELEMETRY) return;
    try {
        const snapshot: StatusData = { ...data, snapshot_at: new Date().toISOString() };
        await env.TELEMETRY.put(LAST_GOOD_KEY, JSON.stringify(snapshot));
    } catch (e) {
        console.warn("Failed to store the last good status snapshot:", e);
    }
}

export async function getLastGoodStatus(env: Env): Promise<StatusData | null> {
    if (!env.TELEMETRY) return null;
    try {
        return await env.TELEMETRY.get<StatusData>(LAST_GOOD_KEY, "json");
    } catch (e) {
        console.warn("Failed to read the last good status snapshot:", e);
        return null;
    }
}

export async function fetchHealthchecks(env: Env) {
    if (!env.HEALTHCHECKS_API_KEY) return [];

    try {
        const res = await fetch("https://healthchecks.io/api/v3/checks/", {
            headers: { "X-Api-Key": env.HEALTHCHECKS_API_KEY }
        });
        if (!res.ok) return null;
        const data = await res.json() as any;
        return data.checks || [];
    } catch {
        return null;
    }
}

export async function fetchHealthcheckFlips(apiId: string, env: Env): Promise<Flip[] | null> {
    try {
        const res = await fetch(`https://healthchecks.io/api/v3/checks/${apiId}/flips/`, {
            headers: { "X-Api-Key": env.HEALTHCHECKS_API_KEY! }
        });
        if (!res.ok) return null;
        const data = await res.json() as any;
        const raw = Array.isArray(data) ? data : (data.flips || []);
        const flips: Flip[] = [];
        for (const item of raw) {
            if (item && item.timestamp) {
                flips.push({
                    timestamp: new Date(item.timestamp.replace("Z", "+00:00")),
                    up: item.up ? 1 : 0
                });
            }
        }
        flips.sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime());
        return flips;
    } catch {
        return null;
    }
}

export async function fetchUptimeRobot(apiKey: string) {
    if (!apiKey) return null;
    try {
        const body = new URLSearchParams({
            api_key: apiKey,
            format: "json",
            logs: "1",
            log_types: "1-2",
            response_times: "0"
        });
        const res = await fetch("https://api.uptimerobot.com/v2/getMonitors", {
            method: "POST",
            body,
            headers: { "Content-Type": "application/x-www-form-urlencoded" }
        });
        if (!res.ok) return null;
        const data = await res.json() as any;
        if (data.stat !== "ok" || !data.monitors || data.monitors.length === 0) return null;

        const monitor = data.monitors[0];
        const flips: Flip[] = [];
        for (const log of (monitor.logs || [])) {
            if (log.type === 1 || log.type === 2) {
                flips.push({
                    timestamp: new Date(log.datetime * 1000),
                    up: log.type === 2 ? 1 : 0
                });
            }
        }
        flips.sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime());

        return {
            status: monitor.status,
            create_datetime: monitor.create_datetime ? new Date(monitor.create_datetime * 1000) : null,
            flips
        };
    } catch {
        return null;
    }
}

export interface Env {
    HEALTHCHECKS_API?: string;
    HEALTHCHECKS_SLUG_ALERTS_SOURCE?: string;
    HEALTHCHECKS_SLUG_ALERTS_BROADCAST?: string;
    UPTIMEROBOT_SIRENS_WEB_API?: string;
    UPTIMEROBOT_SIRENS_API_API?: string;
    STATUS_START_DATE?: string;
    STATUS_KV?: KVNamespace;
    SIRENS_TELEMETRY?: KVNamespace;
    "sirens-telemetry"?: KVNamespace;
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
}

export interface TelemetryData {
    last_broadcast_at?: string | null;
    last_alert?: TelemetryAlert | null;
    last_source_message_at?: string | null;
    active_alerts_count?: number;
    source_connected?: boolean;
    updated_at?: string;
}

export const COMPONENTS_SPEC = [
    { key: "tg", name: "Канали Telegram", source: "healthchecks" },
    { key: "alerts", name: "Обробка тривог", source: "healthchecks" },
    { key: "map", name: "Мапа тривог", source: "uptimerobot" },
    { key: "api", name: "API", source: "uptimerobot" },
];

export async function fetchTelemetry(env: Env): Promise<TelemetryData | null> {
    const kv = env.STATUS_KV || env.SIRENS_TELEMETRY || env["sirens-telemetry"];
    if (!kv) return null;
    try {
        const data = await kv.get<TelemetryData>("telemetry:latest", "json");
        return data;
    } catch (e) {
        console.warn("Failed to fetch telemetry from KV:", e);
        return null;
    }
}

export async function fetchHealthchecks(env: Env) {
    if (!env.HEALTHCHECKS_API) return [];
    
    try {
        const res = await fetch("https://healthchecks.io/api/v3/checks/", {
            headers: { "X-Api-Key": env.HEALTHCHECKS_API }
        });
        if (!res.ok) return null;
        const data = await res.json() as any;
        return data.checks || [];
    } catch {
        return null;
    }
}

export async function fetchHealthcheckFlips(apiId: string, env: Env) {
    try {
        const res = await fetch(`https://healthchecks.io/api/v3/checks/${apiId}/flips/`, {
            headers: { "X-Api-Key": env.HEALTHCHECKS_API! }
        });
        if (!res.ok) return null;
        const data = await res.json() as any;
        // The API usually returns an array, or an object with a "flips" array.
        let raw = Array.isArray(data) ? data : (data.flips || []);
        const flips = [];
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
        const flips = [];
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


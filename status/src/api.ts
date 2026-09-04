// Both spellings are declared on purpose: the names on the left are the ones
// wrangler.toml and the .env now use, the ones on the right are what a Pages
// project provisioned before the rename still has bound. Reads go through the
// accessors below so neither half goes stale.
export interface Env {
    HEALTHCHECKS_API_KEY?: string;
    HEALTHCHECKS_API?: string;
    HEALTHCHECKS_ALERTS_SOURCE_SLUG?: string;
    HEALTHCHECKS_SLUG_ALERTS_SOURCE?: string;
    HEALTHCHECKS_ALERTS_BROADCAST_SLUG?: string;
    HEALTHCHECKS_SLUG_ALERTS_BROADCAST?: string;
    UPTIMEROBOT_WEB_MONITOR_KEY?: string;
    UPTIMEROBOT_SIRENS_WEB_API?: string;
    UPTIMEROBOT_API_MONITOR_KEY?: string;
    UPTIMEROBOT_SIRENS_API_API?: string;
    STATUS_START_DATE?: string;
    GA_MEASUREMENT_ID?: string;
    ENVIRONMENT?: string;
    TELEMETRY?: KVNamespace;
    STATUS_KV?: KVNamespace;
    SIRENS_TELEMETRY?: KVNamespace;
    "sirens-telemetry"?: KVNamespace;
}

export function telemetryKv(env: Env): KVNamespace | undefined {
    return env.TELEMETRY || env.STATUS_KV || env.SIRENS_TELEMETRY || env["sirens-telemetry"];
}

export function healthchecksApiKey(env: Env): string | undefined {
    return env.HEALTHCHECKS_API_KEY || env.HEALTHCHECKS_API;
}

export function healthchecksSlug(env: Env, componentKey: string): string | undefined {
    return componentKey === "source"
        ? env.HEALTHCHECKS_ALERTS_SOURCE_SLUG || env.HEALTHCHECKS_SLUG_ALERTS_SOURCE
        : env.HEALTHCHECKS_ALERTS_BROADCAST_SLUG || env.HEALTHCHECKS_SLUG_ALERTS_BROADCAST;
}

export function uptimeRobotKey(env: Env, componentKey: string): string | undefined {
    return componentKey === "map"
        ? env.UPTIMEROBOT_WEB_MONITOR_KEY || env.UPTIMEROBOT_SIRENS_WEB_API
        : env.UPTIMEROBOT_API_MONITOR_KEY || env.UPTIMEROBOT_SIRENS_API_API;
}

export interface TelemetryAlert {
    type: string;
    oblast?: string;
    district?: string;
    // The place in the nominative, and again declined into the locative
    // ("Біла Церква" / "у Білій Церкві"). Ukrainian declines it, so the
    // alerts service ships the form the sentence needs already built.
    name?: string;
    locative?: string;
    timestamp: string;
}

// The snapshot holds the last alert and nothing else.
export interface TelemetryData {
    last_alert?: TelemetryAlert | null;
}

export const COMPONENTS_SPEC = [
    { key: "broadcast", name: "Розсилка в Telegram", desc: "Канали, якими ми надсилаємо вам сповіщення про тривогу.", source: "healthchecks" },
    { key: "source", name: "Джерело тривог", desc: "Звідки ми дізнаємось, що тривогу оголосили.", source: "healthchecks" },
    { key: "map", name: "Мапа тривог", desc: "Показує тривоги по всій країні в реальному часі.", source: "uptimerobot" },
    { key: "api", name: "API", desc: "Дані для сторонніх ботів і застосунків.", source: "uptimerobot" },
];

export async function fetchTelemetry(env: Env): Promise<TelemetryData | null> {
    const kv = telemetryKv(env);
    if (!kv) return null;
    try {
        const data = await kv.get<TelemetryData>("telemetry:latest", "json");
        return data;
    } catch (e) {
        console.warn("Failed to fetch telemetry from KV:", e);
        return null;
    }
}

// Провайдер, який не відповідає, не має тримати рендер до ліміту воркера.
// AbortError падає в наявні catch і читається як «цей компонент без даних».
const UPSTREAM_TIMEOUT_MS = 5000;

export async function fetchHealthchecks(env: Env) {
    const apiKey = healthchecksApiKey(env);
    if (!apiKey) return [];
    
    try {
        const res = await fetch("https://healthchecks.io/api/v3/checks/", {
            headers: { "X-Api-Key": apiKey },
            signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS)
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
            headers: { "X-Api-Key": healthchecksApiKey(env)! },
            signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS)
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
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS)
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


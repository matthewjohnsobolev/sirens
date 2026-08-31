import { Env, StatusData, getLastGoodStatus } from "../src/api";
import { computeStatusData } from "../src/processor";
import { getMockStatusData } from "../src/mock";

const CORS_HEADERS: Record<string, string> = {
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "X-Content-Type-Options": "nosniff",
};

const NO_STORE = "no-cache, no-store, must-revalidate";

const COMPONENT_STATUS: Record<string, string> = {
    ok: "operational",
    minor: "degraded_performance",
    down: "major_outage",
    major: "major_outage",
    mnt: "under_maintenance",
};

function buildPayload(data: StatusData) {
    return {
        page: {
            id: "sirens-status",
            name: "Сирени",
            url: "https://status.sirens.live",
            time_zone: "Europe/Kyiv",
            updated_at: new Date().toISOString()
        },
        status: {
            indicator: data.severity,
            headline: data.headline,
            description: data.subtitle,
            outage_since: data.outage_since
        },
        stale: Boolean(data.snapshot_at),
        snapshot_at: data.snapshot_at || null,
        telemetry: data.telemetry || null,
        components: data.components.map(c => ({
            id: c.key,
            name: c.name,
            status: COMPONENT_STATUS[c.state] || "unknown",
            uptime_pct_24h: c.uptime,
            monitored: c.monitored,
            outage_since: c.outage_since
        }))
    };
}

function jsonResponse(body: unknown, status: number, cacheControl: string): Response {
    return new Response(JSON.stringify(body, null, 2), {
        status,
        headers: { ...CORS_HEADERS, "Cache-Control": cacheControl }
    });
}

export const onRequest: PagesFunction<Env> = async (context) => {
    const { env, request } = context;

    if (request.method === "OPTIONS") {
        return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    const url = new URL(request.url);
    const mockParam = url.searchParams.get("mock");

    if (mockParam && env.ENVIRONMENT === "development") {
        return jsonResponse(buildPayload(getMockStatusData(mockParam, new Date())), 200, NO_STORE);
    }

    const cacheKey = new Request(`${url.origin}${url.pathname}`, { method: "GET" });
    const cache = caches.default;

    const cached = await cache.match(cacheKey);
    if (cached) return cached;

    let data: StatusData | null = null;
    try {
        data = await computeStatusData(env);
    } catch (error) {
        console.error("Error computing status data for status.json:", error);
    }

    if (data) {
        const response = jsonResponse(buildPayload(data), 200, "public, max-age=30");
        context.waitUntil(cache.put(cacheKey, response.clone()));
        return response;
    }

    const lastGood = await getLastGoodStatus(env);
    if (lastGood) {
        return jsonResponse(buildPayload(lastGood), 200, NO_STORE);
    }

    return jsonResponse({
        status: {
            indicator: "unknown",
            description: "Стан невідомий: сервіс моніторингу тимчасово не відповідає",
            outage_since: null
        },
        updated_at: new Date().toISOString()
    }, 503, NO_STORE);
};

import { Env } from "../src/api";
import { computeStatusData } from "../src/processor";
import { getMockStatusData } from "../src/mock";

// Відповіді Pages Functions не кешуються самі по собі, тож без явного
// caches.default кожен запит сюди — це свіжий похід в усі апстріми.
const JSON_CACHE_SECONDS = 60;
const ERROR_CACHE_SECONDS = 15;

const CORS_HEADERS: Record<string, string> = {
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "X-Content-Type-Options": "nosniff",
};

export const onRequest: PagesFunction<Env> = async (context) => {
    const { env, request } = context;

    if (request.method === "OPTIONS") {
        return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    const url = new URL(request.url);
    const mockParam = url.searchParams.get("mock");

    const isMock = Boolean(mockParam) && env.ENVIRONMENT === "development";

    // Ключ кеша — тільки шлях, щоб довільна query-строка не промахувалась
    // повз кеш і не тягла за собою повний розрахунок.
    const cacheKey = new Request(new URL(url.pathname, url.origin).toString(), { method: "GET" });
    const cache = caches.default;

    if (!isMock) {
        const cached = await cache.match(cacheKey);
        if (cached) return cached;
    }

    let data: any = null;

    if (isMock) {
        data = getMockStatusData(mockParam!, new Date());
    } else {
        try {
            data = await computeStatusData(env);
        } catch (error) {
            console.error("Error computing status data for status.json:", error);
        }
    }

    if (!data) {
        const errorResponse = new Response(JSON.stringify({
            status: {
                indicator: "critical",
                description: "Стан невідомий: сервіс моніторингу тимчасово не відповідає",
                outage_since: null
            },
            updated_at: new Date().toISOString()
        }, null, 2), {
            status: 503,
            headers: {
                ...CORS_HEADERS,
                "Cache-Control": `public, max-age=${ERROR_CACHE_SECONDS}`
            }
        });

        if (!isMock) context.waitUntil(cache.put(cacheKey, errorResponse.clone()).catch(() => {}));
        return errorResponse;
    }

    const isServiceDown = data.headline === "Сповіщення не надходять";
    const isDegraded = data.headline.includes("— ні") || data.headline.includes("перебо");
    const isMnt = data.headline === "Планові роботи";
    const isUnknown = data.headline === "Немає даних";

    let indicator = "none";
    if (isServiceDown) indicator = "major";
    else if (isDegraded) indicator = "minor";
    else if (isMnt) indicator = "maintenance";
    else if (isUnknown) indicator = "unknown";

    const responsePayload = {
        page: {
            id: "sirens-status",
            name: "Сирени",
            url: "https://status.sirens.live",
            time_zone: "Europe/Kyiv",
            updated_at: new Date().toISOString()
        },
        status: {
            indicator,
            headline: data.headline,
            description: data.subtitle,
            outage_since: data.components.find((c: any) => c.outage_since)?.outage_since || null
        },
        telemetry: data.telemetry || null,
        components: data.components.map((c: any) => ({
            id: c.key,
            name: c.name,
            status: c.state === "ok" ? "operational" : c.state === "minor" ? "degraded_performance" : c.state === "down" ? "major_outage" : c.state === "mnt" ? "under_maintenance" : "unknown",
            uptime_pct_24h: c.uptime,
            monitored: c.monitored,
            outage_since: c.outage_since
        }))
    };

    const response = new Response(JSON.stringify(responsePayload, null, 2), {
        headers: {
            ...CORS_HEADERS,
            "Cache-Control": `public, max-age=${JSON_CACHE_SECONDS}`
        }
    });

    if (!isMock) context.waitUntil(cache.put(cacheKey, response.clone()).catch(() => {}));
    return response;
};

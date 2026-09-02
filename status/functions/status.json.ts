import { Env } from "../src/api";
import { computeStatusData } from "../src/processor";
import { getMockStatusData } from "../src/mock";

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

    let data: any = null;

    if (mockParam && env.ENVIRONMENT === "development") {
        data = getMockStatusData(mockParam, new Date());
    } else {
        try {
            data = await computeStatusData(env);
        } catch (error) {
            console.error("Error computing status data for status.json:", error);
        }
    }

    if (!data) {
        return new Response(JSON.stringify({
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
                "Cache-Control": "no-cache, no-store, must-revalidate"
            }
        });
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

    return new Response(JSON.stringify(responsePayload, null, 2), {
        headers: {
            ...CORS_HEADERS,
            "Cache-Control": "public, max-age=30"
        }
    });
};

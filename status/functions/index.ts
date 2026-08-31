import { COMPONENTS_SPEC, Env, StatusData, getLastGoodStatus, putLastGoodStatus } from "../src/api";
import { computeStatusData } from "../src/processor";
import { renderHtml } from "../src/template";
import { formatHourParts } from "../src/helpers";
import { getMockStatusData } from "../src/mock";

const SECURITY_HEADERS: Record<string, string> = {
    "Content-Type": "text/html; charset=utf-8",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "SAMEORIGIN",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()"
};

const NO_STORE = "no-cache, no-store, must-revalidate";

function getFallbackStatusData(now: Date): StatusData {
    const hours = Array.from({ length: 24 }, (_, i) => {
        const d = new Date(now.getTime() - (23 - i) * 3600 * 1000);
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

    return {
        headline: "Стан невідомий",
        subtitle: "Моніторинг тимчасово не відповідає",
        severity: "unknown",
        outage_since: null,
        components: COMPONENTS_SPEC.map(s => ({
            key: s.key,
            name: s.name,
            uptime: null,
            hours,
            monitored: false,
            state: "nodata",
            outage_since: null
        }))
    };
}

export const onRequest: PagesFunction<Env> = async (context) => {
    const { env, request } = context;

    const url = new URL(request.url);
    const mockParam = url.searchParams.get("mock");

    if (mockParam && env.ENVIRONMENT === "development") {
        return new Response(renderHtml(getMockStatusData(mockParam, new Date())), {
            headers: { ...SECURITY_HEADERS, "Cache-Control": NO_STORE }
        });
    }

    const cacheKey = new Request(`${url.origin}${url.pathname}`, { method: "GET" });
    const cache = caches.default;

    const cached = await cache.match(cacheKey);
    if (cached) return cached;

    let data: StatusData | null = null;
    try {
        data = await computeStatusData(env);
    } catch (error) {
        console.error("Error generating status page:", error);
    }

    if (data) {
        const response = new Response(renderHtml(data), {
            headers: { ...SECURITY_HEADERS, "Cache-Control": "public, max-age=60" }
        });
        context.waitUntil(putLastGoodStatus(env, data));
        context.waitUntil(cache.put(cacheKey, response.clone()));
        return response;
    }

    const lastGood = await getLastGoodStatus(env);
    if (lastGood) {
        return new Response(renderHtml(lastGood), {
            headers: { ...SECURITY_HEADERS, "Cache-Control": NO_STORE }
        });
    }

    return new Response(renderHtml(getFallbackStatusData(new Date())), {
        status: 503,
        headers: { ...SECURITY_HEADERS, "Cache-Control": NO_STORE }
    });
};

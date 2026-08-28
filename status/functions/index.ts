import { Env, COMPONENTS_SPEC } from "../src/api";
import { computeStatusData } from "../src/processor";
import { renderHtml } from "../src/template";
import { formatHourParts, formatHourTitle, summarizeHours } from "../src/helpers";
import { getMockStatusData } from "../src/mock";

const SECURITY_HEADERS: Record<string, string> = {
    "Content-Type": "text/html; charset=utf-8",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "SAMEORIGIN",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()"
};

function getFallbackStatusData(now: Date) {
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
        components: COMPONENTS_SPEC.map(s => ({
            key: s.key,
            name: s.name,
            uptime: null,
            hours,
            monitored: false,
            state: "nodata",
            outage_since: null
        })),
        hour_title: formatHourTitle,
        hours_summary: summarizeHours
    };
}

export const onRequest: PagesFunction<Env> = async (context) => {
    const { env, request } = context;

    const url = new URL(request.url);
    const mockParam = url.searchParams.get("mock");

    if (mockParam) {
        const mockData = getMockStatusData(mockParam, new Date());
        const html = renderHtml(mockData);
        return new Response(html, {
            headers: {
                ...SECURITY_HEADERS,
                "Cache-Control": "no-cache, no-store, must-revalidate"
            }
        });
    }

    const cacheKey = new Request(url.toString(), { method: "GET" });
    const cache = caches.default;

    let response = await cache.match(cacheKey);

    if (!response) {
        try {
            const data = await computeStatusData(env);
            if (!data) {
                const fallbackHtml = renderHtml(getFallbackStatusData(new Date()));
                return new Response(fallbackHtml, {
                    status: 503,
                    headers: {
                        ...SECURITY_HEADERS,
                        "Cache-Control": "no-cache, no-store, must-revalidate"
                    }
                });
            }
            
            const html = renderHtml(data);
            
            response = new Response(html, {
                headers: {
                    ...SECURITY_HEADERS,
                    "Cache-Control": "public, max-age=60"
                }
            });
            
            context.waitUntil(cache.put(cacheKey, response.clone()));
            
        } catch (error) {
            console.error("Error generating status page:", error);
            const fallbackHtml = renderHtml(getFallbackStatusData(new Date()));
            return new Response(fallbackHtml, {
                status: 500,
                headers: {
                    ...SECURITY_HEADERS,
                    "Cache-Control": "no-cache, no-store, must-revalidate"
                }
            });
        }
    }

    return response;
};

import { Env, COMPONENTS_SPEC } from "../src/api";
import { computeStatusData } from "../src/processor";
import { renderHtml } from "../src/template";
import { formatHourParts, formatHourTitle, summarizeHours } from "../src/helpers";
import { getMockStatusData } from "../src/mock";

// UptimeRobot на безкоштовному плані дає ~10 запитів на хвилину на акаунт,
// а сторінка робить два (по одному на монітор). Кеш живе окремо в кожному
// дата-центрі Cloudflare, тож 60 с при п'яти активних точках — це рівно ліміт.
// 120 с дає дворазовий запас і нічого не змінює на око: смужки погодинні.
const PAGE_CACHE_SECONDS = 120;
const ERROR_CACHE_SECONDS = 15;

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
        headline: "Немає даних",
        subtitle: "",
        components: COMPONENTS_SPEC.map(s => ({
            key: s.key,
            name: s.name,
            desc: s.desc,
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

    if (mockParam && env.ENVIRONMENT === "development") {
        const mockData = getMockStatusData(mockParam, new Date());
        const html = renderHtml(mockData);
        return new Response(html, {
            headers: {
                ...SECURITY_HEADERS,
                "Cache-Control": "no-cache, no-store, must-revalidate"
            }
        });
    }

    // Ключ кеша — тільки шлях: інакше будь-який ?x=1 промахується повз кеш
    // і запускає повний похід в апстріми.
    const cacheKey = new Request(new URL(url.pathname, url.origin).toString(), { method: "GET" });
    const cache = caches.default;

    let response = await cache.match(cacheKey);

    if (!response) {
        try {
            const data = await computeStatusData(env);
            response = new Response(renderHtml(data), {
                headers: {
                    ...SECURITY_HEADERS,
                    "Cache-Control": `public, max-age=${PAGE_CACHE_SECONDS}`
                }
            });
        } catch (error) {
            // Провайдер, який не відповів, тепер гасить лише свої компоненти,
            // тож сюди веде тільки справжня помилка розрахунку. Кешуємо її
            // ненадовго, щоб баг не перетворився на цикл запитів в апстріми.
            console.error("Error generating status page:", error);
            response = new Response(renderHtml(getFallbackStatusData(new Date())), {
                status: 500,
                headers: {
                    ...SECURITY_HEADERS,
                    "Cache-Control": `public, max-age=${ERROR_CACHE_SECONDS}`
                }
            });
        }

        context.waitUntil(cache.put(cacheKey, response.clone()).catch(() => {}));
    }

    return response;
};

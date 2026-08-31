import { afterEach, describe, expect, it, vi } from "vitest";
import { Env } from "../src/api";
import { computeStatusData } from "../src/processor";
import { renderHtml } from "../src/template";

const ENV: Env = {
    HEALTHCHECKS_API_KEY: "hc-key",
    HEALTHCHECKS_ALERTS_SOURCE_SLUG: "sirens-alerts-source",
    HEALTHCHECKS_ALERTS_BROADCAST_SLUG: "sirens-alerts-broadcast",
    UPTIMEROBOT_WEB_MONITOR_KEY: "ur-web",
    UPTIMEROBOT_API_MONITOR_KEY: "ur-api",
    STATUS_START_DATE: "2023-01-01",
};

interface Scenario {
    healthchecks?: "ok" | "fail";
    checkStatus?: string;
    uptimerobot?: "ok" | "fail";
    monitorStatus?: number;
}

function stubFetch(scenario: Scenario) {
    const checks = [
        {
            slug: "sirens-alerts-source",
            name: "Обробка тривог",
            status: scenario.checkStatus ?? "up",
            n_pings: 100,
            unique_key: "source-key",
        },
        {
            slug: "sirens-alerts-broadcast",
            name: "Канали Telegram",
            status: scenario.checkStatus ?? "up",
            n_pings: 100,
            unique_key: "broadcast-key",
        },
    ];

    vi.stubGlobal("fetch", vi.fn(async (input: any) => {
        const url = typeof input === "string" ? input : input.url;

        if (url.includes("uptimerobot.com")) {
            if (scenario.uptimerobot === "fail") return new Response("", { status: 500 });
            return Response.json({
                stat: "ok",
                monitors: [{ status: scenario.monitorStatus ?? 2, create_datetime: 1600000000, logs: [] }],
            });
        }
        if (url.includes("/flips/")) return Response.json([]);
        if (url.includes("healthchecks.io")) {
            if (scenario.healthchecks === "fail") return new Response("", { status: 500 });
            return Response.json({ checks });
        }
        throw new Error(`unexpected fetch: ${url}`);
    }));
}

const byKey = (data: any, key: string) => data.components.find((c: any) => c.key === key);

afterEach(() => vi.unstubAllGlobals());

describe("computeStatusData", () => {
    it("reports everything healthy", async () => {
        stubFetch({});
        const data = (await computeStatusData(ENV))!;

        expect(data.severity).toBe("none");
        expect(data.headline).toBe("Сповіщення працюють");
        expect(data.outage_since).toBeNull();
        expect(data.components).toHaveLength(4);
        expect(data.components.every(c => c.monitored)).toBe(true);
        expect(byKey(data, "source").state).toBe("ok");
        expect(byKey(data, "source").uptime).toBe(100);
    });

    it("calls a core outage a service outage", async () => {
        stubFetch({ checkStatus: "down" });
        const data = (await computeStatusData(ENV))!;

        expect(data.severity).toBe("major");
        expect(data.headline).toBe("Сервіс не працює");
        expect(data.outage_since).not.toBeNull();
        expect(byKey(data, "source").state).toBe("down");
    });

    it("calls an auxiliary outage a partial one", async () => {
        stubFetch({ monitorStatus: 9 });
        const data = (await computeStatusData(ENV))!;

        expect(data.severity).toBe("minor");
        expect(data.headline).toBe("Сповіщення працюють, мапа й API — ні");
        expect(byKey(data, "source").state).toBe("ok");
    });

    it("keeps the map and API alive when healthchecks is unreachable", async () => {
        stubFetch({ healthchecks: "fail" });
        const data = (await computeStatusData(ENV))!;

        expect(byKey(data, "map").state).toBe("ok");
        expect(byKey(data, "map").uptime).toBe(100);
        expect(byKey(data, "source").state).toBe("nodata");
        expect(byKey(data, "source").monitored).toBe(true);
        expect(byKey(data, "source").uptime).toBeNull();
        expect(data.severity).toBe("unknown");
    });

    it("keeps the alert components alive when uptimerobot is unreachable", async () => {
        stubFetch({ uptimerobot: "fail" });
        const data = (await computeStatusData(ENV))!;

        expect(byKey(data, "source").state).toBe("ok");
        expect(byKey(data, "map").state).toBe("nodata");
        expect(byKey(data, "map").monitored).toBe(true);
        expect(data.severity).toBe("none");
    });

    it("gives up only when every provider is unreachable", async () => {
        stubFetch({ healthchecks: "fail", uptimerobot: "fail" });

        expect(await computeStatusData(ENV)).toBeNull();
    });

    it("names the location of the last alert from telemetry", async () => {
        stubFetch({});
        const telemetry = {
            last_alert: {
                type: "air_raid_alert",
                timestamp: new Date(Date.now() - 3600 * 1000).toISOString(),
                city_name: "Біла Церква",
                location_title: "у Білій Церкві",
            },
        };
        const env: Env = {
            ...ENV,
            TELEMETRY: { get: async () => telemetry } as unknown as KVNamespace,
        };

        const data = (await computeStatusData(env))!;

        expect(data.subtitle).toContain("у Білій Церкві");
        expect(data.telemetry).toEqual(telemetry);
    });
});

describe("renderHtml", () => {
    const base = {
        headline: "Сповіщення працюють",
        subtitle: "Сповіщення в Telegram надходять як зазвичай.",
        severity: "none" as const,
        outage_since: null,
        components: [],
    };

    it("picks the notice style from severity, not from the headline text", () => {
        expect(renderHtml({ ...base, severity: "major" })).toContain("notice--error");
        expect(renderHtml({ ...base, severity: "minor" })).toContain("notice--warning");
        expect(renderHtml({ ...base, severity: "maintenance" })).toContain("notice--mnt");
        expect(renderHtml({ ...base, severity: "unknown" })).toContain("notice--nodata");
        expect(renderHtml(base)).toContain("notice--ok");
    });

    it("offers a different report wording once a failure is already named", () => {
        expect(renderHtml({ ...base, severity: "major" })).toContain("Повідомити про інший збій");
        expect(renderHtml(base)).toContain("Не отримали сповіщення або помітили збій?");
    });

    it("marks a snapshot served after a failed refresh", () => {
        const html = renderHtml({ ...base, snapshot_at: "2026-08-31T09:32:00Z" });

        expect(html).toContain("notice-stale");
        expect(html).toContain("оновити зараз не вдалося");
    });

    it("says nothing about staleness for a fresh render", () => {
        expect(renderHtml(base)).not.toContain("notice-stale");
    });

    it("escapes text that reaches the page from telemetry", () => {
        const html = renderHtml({ ...base, subtitle: 'Останнє — <script>alert("x")</script>' });

        expect(html).not.toContain("<script>alert");
        expect(html).toContain("&lt;script&gt;");
    });

    it("keeps wrapping times in the subtitle", () => {
        const html = renderHtml({ ...base, subtitle: "Сповіщення не надходять з 03:10." });

        expect(html).toContain('<time class="mono-time">03:10</time>');
    });
});

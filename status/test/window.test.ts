import { describe, expect, it } from "vitest";
import { getDownIntervals, getHourStart, overlapSeconds, stateAt } from "../src/processor";

const at = (iso: string) => new Date(iso);

describe("getHourStart", () => {
    it("floors to the top of the hour", () => {
        expect(getHourStart(at("2026-08-31T10:47:13Z")).toISOString()).toBe("2026-08-31T10:00:00.000Z");
    });
});

describe("overlapSeconds", () => {
    it("measures the shared part of two ranges", () => {
        expect(overlapSeconds(
            at("2026-08-31T10:00:00Z"), at("2026-08-31T11:00:00Z"),
            at("2026-08-31T10:30:00Z"), at("2026-08-31T12:00:00Z")
        )).toBe(1800);
    });

    it("is zero for disjoint ranges", () => {
        expect(overlapSeconds(
            at("2026-08-31T10:00:00Z"), at("2026-08-31T11:00:00Z"),
            at("2026-08-31T12:00:00Z"), at("2026-08-31T13:00:00Z")
        )).toBe(0);
    });
});

describe("stateAt", () => {
    const flips = [
        { timestamp: at("2026-08-31T10:00:00Z"), up: 0 },
        { timestamp: at("2026-08-31T11:00:00Z"), up: 1 },
    ];

    it("takes the last flip before the moment", () => {
        expect(stateAt(flips, at("2026-08-31T10:30:00Z"), true)).toBe(false);
        expect(stateAt(flips, at("2026-08-31T11:30:00Z"), false)).toBe(true);
    });

    it("assumes it was up before the first flip went down", () => {
        expect(stateAt(flips, at("2026-08-31T09:00:00Z"), false)).toBe(true);
    });

    it("uses the fallback when there are no flips at all", () => {
        expect(stateAt([], at("2026-08-31T09:00:00Z"), false)).toBe(false);
        expect(stateAt([], at("2026-08-31T09:00:00Z"), true)).toBe(true);
    });
});

describe("getDownIntervals", () => {
    const windowStart = at("2026-08-31T00:00:00Z");
    const now = at("2026-08-31T12:00:00Z");

    it("pairs a down flip with the recovery that follows", () => {
        const intervals = getDownIntervals([
            { timestamp: at("2026-08-31T02:00:00Z"), up: 0 },
            { timestamp: at("2026-08-31T03:00:00Z"), up: 1 },
        ], windowStart, now, true);

        expect(intervals).toHaveLength(1);
        expect(intervals[0].start.toISOString()).toBe("2026-08-31T02:00:00.000Z");
        expect(intervals[0].end.toISOString()).toBe("2026-08-31T03:00:00.000Z");
    });

    it("closes an unrecovered outage at the current moment", () => {
        const intervals = getDownIntervals(
            [{ timestamp: at("2026-08-31T09:00:00Z"), up: 0 }], windowStart, now, true);

        expect(intervals[0].end.toISOString()).toBe(now.toISOString());
    });

    it("counts the window as down from the start when it began down", () => {
        const intervals = getDownIntervals([], windowStart, now, false);

        expect(intervals).toHaveLength(1);
        expect(intervals[0].start.toISOString()).toBe(windowStart.toISOString());
    });

    it("ignores flips outside the window", () => {
        const intervals = getDownIntervals([
            { timestamp: at("2026-08-30T22:00:00Z"), up: 0 },
            { timestamp: at("2026-09-01T02:00:00Z"), up: 1 },
        ], windowStart, now, true);

        expect(intervals).toHaveLength(0);
    });
});

import { describe, expect, it } from "vitest";
import { formatLocationLocative, pluralHours, summarizeHours } from "../src/helpers";

describe("formatLocationLocative", () => {
    it("prefers the locative the worker already computed", () => {
        expect(formatLocationLocative("Біла Церква", "у Білій Церкві")).toBe("у Білій Церкві");
    });

    it("adds the preposition to a bare custom locative", () => {
        expect(formatLocationLocative(null, "Білій Церкві")).toBe("у Білій Церкві");
    });

    it("declines a district name", () => {
        expect(formatLocationLocative("Бучанський район")).toBe("у Бучанському районі");
    });

    it("switches the preposition before a vowel", () => {
        expect(formatLocationLocative("Одеса")).toBe("в Одеса");
        expect(formatLocationLocative("Львів")).toBe("у Львів");
    });

    it("returns nothing without a location", () => {
        expect(formatLocationLocative(null, null)).toBe("");
    });
});

describe("pluralHours", () => {
    it("follows Ukrainian plural rules", () => {
        expect(pluralHours(1)).toBe("година");
        expect(pluralHours(3)).toBe("години");
        expect(pluralHours(5)).toBe("годин");
        expect(pluralHours(11)).toBe("годин");
        expect(pluralHours(21)).toBe("година");
    });
});

describe("summarizeHours", () => {
    it("counts states in a fixed order", () => {
        const hours = [
            { state: "ok" }, { state: "ok" }, { state: "minor" }, { state: "down" }
        ];
        expect(summarizeHours(hours)).toBe(
            "2 години працює, 1 година з частковими збоями, 1 година з тривалими збоями"
        );
    });

    it("folds major into down", () => {
        expect(summarizeHours([{ state: "major" }])).toBe("1 година з тривалими збоями");
    });

    it("falls back when there is nothing to summarise", () => {
        expect(summarizeHours([])).toBe("немає даних");
    });
});

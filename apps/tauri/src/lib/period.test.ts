import { describe, expect, it } from "vitest";
import { periodRange } from "./period";

describe("periodRange", () => {
  const sat = new Date(2026, 6, 18); // Sat 2026-07-18

  it("weekly is the last full Monday–Sunday week", () => {
    expect(periodRange("weekly", sat)).toEqual({ start: "2026-07-06", end: "2026-07-12", periodType: "weekly" });
    // On a Monday the week just ended is still the previous one.
    expect(periodRange("weekly", new Date(2026, 6, 13))).toEqual({ start: "2026-07-06", end: "2026-07-12", periodType: "weekly" });
  });

  it("monthly is the previous calendar month", () => {
    expect(periodRange("monthly", sat)).toEqual({ start: "2026-06-01", end: "2026-06-30", periodType: "monthly" });
  });

  it("quarterly is the previous calendar quarter, across a year boundary", () => {
    expect(periodRange("quarterly", sat)).toEqual({ start: "2026-04-01", end: "2026-06-30", periodType: "quarterly" });
    expect(periodRange("quarterly", new Date(2026, 1, 10))).toEqual({ start: "2025-10-01", end: "2025-12-31", periodType: "quarterly" });
  });
});

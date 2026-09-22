import { describe, expect, it } from "vitest";
import { heatmapWeeks, yearSpan } from "./heatmap";

describe("yearSpan", () => {
  // 2026-08-05 is a Wednesday.
  const latest = new Date(2026, 7, 5, 22, 0);

  it("defaults to 53 Sunday-first weeks ending on latest", () => {
    expect(yearSpan("", latest)).toEqual(["2025-08-03", "2026-08-05"]);
  });

  it("clips the current year to latest, keeps a past year whole", () => {
    expect(yearSpan("2026", latest)).toEqual(["2026-01-01", "2026-08-05"]);
    expect(yearSpan("2025", latest)).toEqual(["2025-01-01", "2025-12-31"]);
  });
});

describe("heatmapWeeks", () => {
  it("starts each column on a Sunday and nulls days outside the span", () => {
    // 2026-07-28 is a Tuesday, 2026-08-05 a Wednesday.
    const cols = heatmapWeeks([], "2026-07-28", "2026-08-05");
    expect(cols).toHaveLength(2);
    expect(cols[0].slice(0, 2)).toEqual([null, null]);
    expect(cols[0][2]?.day).toBe("2026-07-28");
    expect(cols[1][0]?.day).toBe("2026-08-02");
    expect(cols[1][3]?.day).toBe("2026-08-05");
    expect(cols[1].slice(4)).toEqual([null, null, null]);
  });

  it("lays a whole year out in 53 columns", () => {
    // 2025-01-01 is a Wednesday, so Dec 31 lands in the 53rd column.
    expect(heatmapWeeks([], "2025-01-01", "2025-12-31")).toHaveLength(53);
  });

  it("shades relative to the busiest day, zero stays level 0", () => {
    const cols = heatmapWeeks(
      [
        { bucket: "2026-08-03", total_mins: 100 },
        { bucket: "2026-08-04", total_mins: 10 },
      ],
      "2026-08-02",
      "2026-08-05"
    );
    expect(cols[0].map((c) => c?.level)).toEqual([0, 4, 1, 0, undefined, undefined, undefined]);
  });
});

export type ReportPeriod = "weekly" | "monthly" | "seasonal";

const fmt = (dt: Date) =>
  `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;

/** Last fully completed period (local time). Week starts Monday; seasonal = calendar quarter. */
export function periodRange(
  period: ReportPeriod,
  now = new Date()
): { start: string; end: string; periodType: string } {
  const y = now.getFullYear();
  const m = now.getMonth();
  if (period === "weekly") {
    const monOffset = (now.getDay() + 6) % 7; // Mon=0 .. Sun=6
    const lastSun = new Date(y, m, now.getDate() - monOffset - 1);
    const lastMon = new Date(lastSun.getFullYear(), lastSun.getMonth(), lastSun.getDate() - 6);
    return { start: fmt(lastMon), end: fmt(lastSun), periodType: "weekly" };
  }
  if (period === "monthly") {
    return { start: fmt(new Date(y, m - 1, 1)), end: fmt(new Date(y, m, 0)), periodType: "monthly" };
  }
  const q = Math.floor(m / 3); // current quarter; JS Date normalizes negative months
  return {
    start: fmt(new Date(y, (q - 1) * 3, 1)),
    end: fmt(new Date(y, q * 3, 0)),
    periodType: "custom",
  };
}

// Self-check, runs only under node (`npx tsx src/lib/period.ts`) — never in the webview.
if (typeof window === "undefined") {
  const now = new Date(2026, 6, 18); // Sat 2026-07-18
  const eq = (a: object, b: object) => JSON.stringify(a) === JSON.stringify(b) || (() => { throw new Error(`${JSON.stringify(a)} != ${JSON.stringify(b)}`); })();
  eq(periodRange("weekly", now), { start: "2026-07-06", end: "2026-07-12", periodType: "weekly" });
  eq(periodRange("monthly", now), { start: "2026-06-01", end: "2026-06-30", periodType: "monthly" });
  eq(periodRange("seasonal", now), { start: "2026-04-01", end: "2026-06-30", periodType: "custom" });
  eq(periodRange("seasonal", new Date(2026, 1, 10)), { start: "2025-10-01", end: "2025-12-31", periodType: "custom" }); // Q4 prev year
  eq(periodRange("weekly", new Date(2026, 6, 13)), { start: "2026-07-06", end: "2026-07-12", periodType: "weekly" }); // Monday
  console.log("period.ts self-check OK");
}

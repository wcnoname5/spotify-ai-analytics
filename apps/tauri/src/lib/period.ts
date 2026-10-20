export type ReportPeriod = "weekly" | "monthly" | "quarterly";

const fmt = (dt: Date) =>
  `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;

/** Last fully completed period (local time). Week starts Monday; quarterly = calendar quarter. */
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
    periodType: "quarterly",
  };
}

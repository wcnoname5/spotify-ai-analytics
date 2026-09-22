// GitHub-style calendar of daily listening: a column per week, Sunday on top.
// Pure, like gantt.ts — rows come from @sql/trend_daily.sql via queries.trend().
import { localDay } from "./gantt";

export interface Cell {
  day: string; // YYYY-MM-DD, local
  mins: number;
  level: number; // 0 = silent, 1-4 = shade
}

/**
 * The span a year filter covers, as local YYYY-MM-DD. `year` "" means the last
 * 12 months: 53 Sunday-first weeks ending on `latest`, GitHub's default view.
 * A year is clipped to `latest` so the calendar stops where the data does.
 */
export function yearSpan(year: string, latest: Date): [string, string] {
  const last = localDay(latest);
  if (!year) {
    const first = new Date(latest.getFullYear(), latest.getMonth(), latest.getDate() - latest.getDay() - 52 * 7);
    return [localDay(first), last];
  }
  const end = `${year}-12-31`;
  return [`${year}-01-01`, end < last ? end : last];
}

/**
 * Sunday-first columns of 7 cells covering `first`..`last`. Days of the edge
 * weeks outside the span are null, so they draw as gaps.
 */
export function heatmapWeeks(
  rows: { bucket: string; total_mins: number }[],
  first: string,
  last: string
): (Cell | null)[][] {
  const mins = new Map(rows.map((r) => [r.bucket, r.total_mins]));
  // ponytail: shade is linear against the busiest day, so one binge day mutes
  // the rest. Switch to quartiles of non-zero days if that starts to bite.
  const max = Math.max(1, ...mins.values());
  const f = new Date(first + "T00:00:00");
  const sunday = new Date(f.getFullYear(), f.getMonth(), f.getDate() - f.getDay());
  const cols: (Cell | null)[][] = [];
  for (let w = 0; ; w++) {
    const col: (Cell | null)[] = [];
    for (let d = 0; d < 7; d++) {
      const day = localDay(new Date(sunday.getFullYear(), sunday.getMonth(), sunday.getDate() + w * 7 + d));
      const m = mins.get(day) ?? 0;
      col.push(day < first || day > last ? null : { day, mins: m, level: m > 0 ? Math.ceil((4 * m) / max) : 0 });
    }
    if (col.every((c) => c === null)) break; // ran past `last`
    cols.push(col);
  }
  return cols;
}

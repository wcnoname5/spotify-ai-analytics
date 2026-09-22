// Layout for the listening timeline (Gantt): one lane per day, one bar per play,
// consecutive plays of the same artist sharing a hue.
// Pure — no Vue, no Plotly, no DB — so it can be tested in plain node.

/** A row of @sql/listening_timeline.sql. `started_local` is "YYYY-MM-DD HH:MM:SS". */
export interface TimelinePlay {
  track_name: string;
  artist_name: string;
  album_name: string;
  ms_played: number;
  started_local: string;
}

export interface Bar {
  lane: number; // index into Gantt.days — the y value
  base: number; // seconds into the local day
  width: number; // seconds
  color: number; // hue slot 0-7, advanced once per artist run
  day: string;
  artist: string;
  album: string;
  track: string;
}

export interface Gantt {
  days: string[];
  bars: Bar[];
}

const DAY_SECONDS = 86_400;

/** Hue slots to cycle through*/
export const HUE_SLOTS = 8;

export const localDay = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** The `n` local days ending on `latest`'s local day, oldest first, as YYYY-MM-DD. */
export function windowDays(latest: Date, n = 7): string[] {
  const days: string[] = [];
  for (let i = n - 1; i >= 0; i--) {
    days.push(localDay(new Date(latest.getFullYear(), latest.getMonth(), latest.getDate() - i)));
  }
  return days;
}

/** Midnight of `day` (local) as a UTC ISO string — the query's lower bound. */
export function dayStartIso(day: string): string {
  return new Date(day + "T00:00:00").toISOString();
}

/** Midnight after `day` (local) as a UTC ISO string — the query's upper bound. */
export function dayEndIso(day: string): string {
  const d = new Date(day + "T00:00:00");
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1).toISOString();
}

function secondsIntoDay(startedLocal: string): number {
  const [h, m, s] = startedLocal.slice(11).split(":").map(Number);
  return h * 3600 + m * 60 + s;
}

/**
 * One lane per day, one bar per play. `days` fixes both the window and the row
 * order, so a day nobody listened on still gets an (empty) lane.
 * Each run of consecutive same-artist plays shares the same hue (cycled). 
 */
export function buildGantt(plays: TimelinePlay[], days: string[]): Gantt {
  const laneOf = new Map(days.map((d, i) => [d, i]));
  const laneEnd = new Map<number, number>();
  const bars: Bar[] = [];
  let color = -1;
  let prevArtist: string | undefined;

  for (const p of plays) {
    const day = p.started_local.slice(0, 10);
    const lane = laneOf.get(day);
    if (lane === undefined) continue;
    // floor matches SQLite's integer `ms_played / 1000` in the query, so
    // consecutive complete plays about to the second instead of drifting apart.
    // ponytail: songs that played across midnight may loss its tail
    const end = Math.min(secondsIntoDay(p.started_local) + Math.floor(p.ms_played / 1000), DAY_SECONDS);
    // `ms_played` is the track's duration_ms, not time actually listened
    // (worker/src/sync.ts) — so a skipped track's derived start lands before
    // the previous play ended. played_at (the end) is the trustworthy edge:
    // pull the start forward to where the lane last finished, which recovers
    // the real listening time instead of drawing bars on top of each other.
    const base = Math.max(secondsIntoDay(p.started_local), laneEnd.get(lane) ?? 0);
    if (end <= base) continue; // a play entirely swallowed by the previous one
    laneEnd.set(lane, end);
    if (p.artist_name !== prevArtist) color = (color + 1) % HUE_SLOTS;
    prevArtist = p.artist_name;
    bars.push({
      lane,
      base,
      width: end - base,
      color,
      day,
      artist: p.artist_name,
      album: p.album_name,
      track: p.track_name,
    });
  }

  return { days, bars };
}

// ---------------------------------------------------------------------------
// Plotly wiring. Pure data too — it builds config objects, it doesn't draw — so
// the same code the app renders can be exercised outside the app.

/**
 * The validated categorical palette (see dataviz's validate_palette.js: eight
 * slots, adjacent-pair safe in both modes). "Other" is a neutral, not a 9th hue.
 */
const HUES = {
  light: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
  dark: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
};
const INK = {
  light: { grid: "#e1e0d9", axis: "#c3c2b7" },
  dark: { grid: "#2c2c2a", axis: "#383835" },
};

export type Theme = "light" | "dark";

/** Row pitch in px — also what the chart's height is derived from. */
export const ROW_PX = 22;

export const colorOf = (slot: number, theme: Theme) => HUES[theme][slot];

export const hhmm = (secs: number) =>
  `${String(Math.floor(secs / 3600) % 24).padStart(2, "0")}:${String(Math.floor(secs / 60) % 60).padStart(2, "0")}`;

/** y is negated so the oldest day sits at the top — Plotly's y grows upward. */
const laneY = (lane: number) => -lane;

/** One trace per hue slot, each carrying its bars across every lane. */
export function ganttTraces(g: Gantt, theme: Theme) {
  return HUES[theme]
    .map((color, slot) => {
      const bars = g.bars.filter((b) => b.color === slot);
      return {
        type: "bar" as const,
        orientation: "h" as const,
        // ms on a date axis: Plotly reads numbers as epoch ms in UTC, so day 0
        // of 1970 stands in for "a day" and its ticks read as local wall time.
        x: bars.map((b) => b.width * 1000),
        base: bars.map((b) => b.base * 1000),
        y: bars.map((b) => laneY(b.lane)),
        width: 0.62,
        marker: { color },
        customdata: bars.map((b) => [
          b.track, b.artist, hhmm(b.base), hhmm(b.base + b.width), `${Math.floor(b.width / 60)}m${b.width % 60}s`,
        ]),
        hovertemplate:
          "<b>%{customdata[0]}</b><br>%{customdata[1]}<br>%{customdata[2]}–%{customdata[3]} · %{customdata[4]}<extra></extra>",
      };
    })
    .filter((t) => t.x.length > 0);
}

/**
 * Overrides for PlotChart's chrome(). That merge is shallow, so anything this
 * sets on xaxis/yaxis has to re-state gridcolor/linecolor/fixedrange itself.
 */
export function ganttLayout(g: Gantt, theme: Theme) {
  const { grid, axis } = INK[theme];
  const n = g.days.length;
  return {
    height: n * ROW_PX + 60,
    margin: { l: 84, r: 12, t: 8, b: 40 },
    // chrome() defaults to "x unified", which on a Gantt reports every lane at
    // the pointer's time instead of the bar under it.
    hovermode: "closest" as const,
    bargap: 0,
    barmode: "overlay" as const,
    // Keeps the user's zoom across re-renders (e.g. a theme toggle).
    uirevision: "gantt",
    // Drag zooms time only (y is fixed); double-click resets to the full day.
    xaxis: {
      type: "date" as const,
      range: [0, DAY_SECONDS * 1000],
      tickformat: "%H:%M",
      gridcolor: grid,
      linecolor: axis,
      zerolinecolor: axis,
      fixedrange: false,
      title: { text: "Time of day (local)" },
    },
    yaxis: {
      range: [-n + 0.5, 0.5],
      tickvals: g.days.map((_, i) => laneY(i)),
      ticktext: g.days,
      gridcolor: grid,
      linecolor: axis,
      zerolinecolor: axis,
      fixedrange: true,
      showgrid: false,
    },
  };
}

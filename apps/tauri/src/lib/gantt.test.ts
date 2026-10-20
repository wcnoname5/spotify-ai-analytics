import { describe, expect, it } from "vitest";
import { buildGantt, dayTime, windowDays, type TimelinePlay } from "./gantt";

const play = (
  started_local: string,
  ms_played: number,
  artist_name = "Artist A",
  album_name = "Album X",
  track_name = "track"
): TimelinePlay => ({ started_local, ms_played, artist_name, album_name, track_name });

describe("windowDays", () => {
  it("returns n local days ending on the given day, oldest first", () => {
    expect(windowDays(new Date(2026, 7, 4, 10, 5), 7)).toEqual([
      "2026-07-29", "2026-07-30", "2026-07-31",
      "2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04",
    ]);
  });

  it("crosses a month boundary", () => {
    expect(windowDays(new Date(2026, 2, 2), 4)).toEqual([
      "2026-02-27", "2026-02-28", "2026-03-01", "2026-03-02",
    ]);
  });
});

describe("dayTime", () => {
  // Numbers on a Plotly date axis get shifted by the viewer's UTC offset;
  // these naive strings must not depend on the timezone at all.
  it("is a timezone-naive wall time on 1970-01-01", () => {
    expect(dayTime(11 * 3600 + 35 * 60)).toBe("1970-01-01 11:35:00");
    expect(dayTime(86_400)).toBe("1970-01-02 00:00:00");
  });
});

describe("buildGantt", () => {
  const days = ["2026-07-28", "2026-07-29"];

  it("makes consecutive plays abut exactly, never overlap", () => {
    // The real chain from the DB: played_at is the END of playback, so
    // started_local(n+1) == started_local(n) + floor(ms_played(n) / 1000).
    const { bars } = buildGantt(
      [
        play("2026-07-28 16:43:28", 189173),
        play("2026-07-28 16:46:37", 158106),
        play("2026-07-28 16:49:15", 231066),
      ],
      days
    );
    expect(bars).toHaveLength(3);
    for (let i = 1; i < bars.length; i++) {
      expect(bars[i - 1].base + bars[i - 1].width).toBe(bars[i].base);
    }
  });

  it("puts the bar at seconds-into-the-local-day", () => {
    const { bars } = buildGantt([play("2026-07-28 16:43:28", 60_000)], days);
    expect(bars[0].base).toBe(16 * 3600 + 43 * 60 + 28);
    expect(bars[0].width).toBe(60);
  });

  it("pulls a skipped track's start forward instead of overlapping the previous bar", () => {
    // ms_played is the track's full duration, so a track skipped partway has a
    // derived start that lands before the previous play ended.
    const { bars } = buildGantt(
      [
        play("2026-07-28 14:08:23", 258_506, "The Strokes", "A", "Going Shopping"),
        play("2026-07-28 14:10:17", 290_773, "The Strokes", "A", "Liar's Remorse"),
      ],
      days
    );
    expect(bars[0].base + bars[0].width).toBe(bars[1].base); // no overlap
    expect(bars[1].width).toBe(146); // 14:12:41 -> 14:15:07, the time really listened
  });

  it("drops a play entirely swallowed by the previous one", () => {
    const { bars } = buildGantt(
      [
        play("2026-07-28 09:00:00", 600_000, "A", "X", "long"),
        play("2026-07-28 09:01:00", 60_000, "A", "X", "swallowed"),
      ],
      days
    );
    expect(bars.map((b) => b.track)).toEqual(["long"]);
  });

  it("puts each day on its own lane, including a silent one", () => {
    const { bars } = buildGantt([play("2026-07-29 09:00:00", 60_000)], days);
    expect(bars[0].lane).toBe(1);
  });

  it("gives a run of consecutive same-artist plays one hue, the next run the next", () => {
    const { bars } = buildGantt(
      [
        play("2026-07-28 09:00:00", 60_000, "Alpha"),
        play("2026-07-28 09:01:00", 60_000, "Alpha"),
        play("2026-07-28 09:02:00", 60_000, "Beta"),
        play("2026-07-28 09:03:00", 60_000, "Alpha"),
      ],
      days
    );
    expect(bars.map((b) => b.color)).toEqual([0, 0, 1, 2]);
  });

  it("cycles hues after eight runs", () => {
    const plays = Array.from({ length: 9 }, (_, i) =>
      play(`2026-07-28 09:0${i}:00`, 60_000, `Artist ${i}`)
    );
    expect(buildGantt(plays, days).bars.map((b) => b.color)).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 0]);
  });

  it("drops plays outside the day window", () => {
    const { bars } = buildGantt([play("2026-07-27 09:00:00", 60_000)], days);
    expect(bars).toEqual([]);
  });
});

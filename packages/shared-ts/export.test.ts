import { describe, expect, it } from "vitest";

import { parseExportFile, toTrackRow } from "./export";
import { playRowId } from "./rowid";

const play = (over: Record<string, unknown> = {}) => ({
  ts: "2026-01-15T10:30:45.123Z",
  ms_played: 210000,
  platform: "windows",
  conn_country: "TW",
  master_metadata_track_name: "Song",
  master_metadata_album_artist_name: "Artist",
  master_metadata_album_album_name: "Album",
  spotify_track_uri: "spotify:track:abc123",
  reason_start: "clickrow",
  reason_end: "trackdone",
  shuffle: false,
  skipped: false,
  ...over,
});

describe("toTrackRow", () => {
  it("drops sub-second precision from the timestamp", async () => {
    // The export and the API report the same play with different milliseconds,
    // so keeping them would give the same listen two different ids.
    const row = await toTrackRow(play());
    expect(row?.played_at).toBe("2026-01-15T10:30:45Z");
  });

  it("derives the id the same way the Worker cron does", async () => {
    const row = await toTrackRow(play());
    expect(row?.id).toBe(await playRowId("spotify:track:abc123", "2026-01-15T10:30:45Z"));
  });

  it("maps booleans to integers, because the column is INTEGER", async () => {
    const row = await toTrackRow(play({ shuffle: true, skipped: false }));
    expect(row?.shuffle).toBe(1);
    expect(row?.skipped).toBe(0);
  });

  it("keeps a missing boolean null rather than defaulting it to 0", async () => {
    // 0 would assert "this play was not shuffled", which the export never said.
    const row = await toTrackRow(play({ shuffle: undefined, skipped: null }));
    expect(row?.shuffle).toBeNull();
    expect(row?.skipped).toBeNull();
  });

  it("skips podcast and audiobook rows", async () => {
    // These have no spotify_track_uri and are normal contents of a real export.
    expect(await toTrackRow(play({ spotify_track_uri: null }))).toBeNull();
    expect(await toTrackRow(play({ spotify_track_uri: undefined }))).toBeNull();
  });

  it("skips a record whose timestamp cannot be parsed", async () => {
    expect(await toTrackRow(play({ ts: "not a date" }))).toBeNull();
    expect(await toTrackRow(play({ ts: undefined }))).toBeNull();
  });

  it("tolerates null track metadata", async () => {
    const row = await toTrackRow(
      play({
        master_metadata_track_name: null,
        master_metadata_album_artist_name: null,
        master_metadata_album_album_name: null,
      })
    );
    expect(row?.track_name).toBeNull();
    expect(row?.artist_name).toBeNull();
    expect(row?.id).toBeTruthy();
  });

  it("marks the source so imported rows are distinguishable from synced ones", async () => {
    expect((await toTrackRow(play()))?.source).toBe("json_import");
  });
});

describe("parseExportFile", () => {
  it("counts unusable records instead of failing the file", async () => {
    const text = JSON.stringify([
      play(),
      play({ spotify_track_uri: null }),
      play({ ts: "nope" }),
      play({ ts: "2026-01-16T00:00:00Z" }),
    ]);
    const { rows, skipped } = await parseExportFile(text);
    expect(rows).toHaveLength(2);
    expect(skipped).toBe(2);
  });

  it("throws when handed something that is not a record array", async () => {
    // This is the "you picked the wrong folder" case, worth surfacing.
    await expect(parseExportFile('{"not": "an array"}')).rejects.toThrow(/array/);
    await expect(parseExportFile("garbage")).rejects.toThrow();
  });

  it("handles an empty file", async () => {
    expect(await parseExportFile("[]")).toEqual({ rows: [], skipped: 0 });
  });

  it("gives two plays of the same track at different times different ids", async () => {
    const text = JSON.stringify([play(), play({ ts: "2026-01-15T11:30:45Z" })]);
    const { rows } = await parseExportFile(text);
    expect(rows[0].id).not.toBe(rows[1].id);
  });

  it("gives the same play the same id, so a re-import inserts nothing", async () => {
    const first = await parseExportFile(JSON.stringify([play()]));
    const second = await parseExportFile(JSON.stringify([play()]));
    expect(first.rows[0].id).toBe(second.rows[0].id);
  });
});

// Importing a Spotify data export into D1.
//
// This replaced `spotify-mcp import-history`, which read the export with Polars
// (156 MB of dependencies to parse JSON) and wrote to the *local* SQLite. That
// was backwards: local SQLite is a disposable mirror of D1, so an import that
// only landed there was lost on any machine change.
//
// Rows go to the Worker; the normal startup sync pulls them back down.
import { fetch } from "@tauri-apps/plugin-http";
import { invoke } from "@tauri-apps/api/core";
import { parseExportFile, type TrackRow } from "@shared/export";

import { getConfig } from "./config";

/**
 * Rows per POST.
 *
 * D1 caps a batch's statement count and a Worker request's body size, and a
 * full export is ~100k rows. 500 keeps each request well inside both while
 * still being ~200 requests rather than ~100k.
 */
const BATCH = 500;

export interface ImportProgress {
  file: string;
  fileIndex: number;
  fileCount: number;
  inserted: number;
  skipped: number;
}

export interface ImportResult {
  inserted: number;
  /** Records that are not track plays: podcasts, audiobooks, unparseable dates. */
  skipped: number;
  files: number;
}

/**
 * Import every history file in `folder`, reporting progress per file.
 *
 * Resumable by construction rather than by bookkeeping: the row id is a hash of
 * the play, so re-running after a failure re-sends rows D1 already has and
 * `INSERT OR IGNORE` drops them.
 */
export async function importHistory(
  folder: string,
  onProgress?: (p: ImportProgress) => void
): Promise<ImportResult> {
  const cfg = await getConfig();
  if (!cfg.configured.worker) {
    throw new Error(
      "Set up Cloud sync first — imported history is stored in your Cloudflare D1."
    );
  }

  const files = await invoke<string[]>("list_history_files", { folder });
  let inserted = 0;
  let skipped = 0;

  for (const [fileIndex, file] of files.entries()) {
    const text = await invoke<string>("read_history_file", { path: file });
    let parsed;
    try {
      parsed = await parseExportFile(text);
    } catch (e) {
      throw new Error(`${basename(file)}: ${e instanceof Error ? e.message : String(e)}`);
    }
    skipped += parsed.skipped;

    for (let i = 0; i < parsed.rows.length; i += BATCH) {
      inserted += await postBatch(cfg.worker_url, cfg.worker_auth_token, parsed.rows.slice(i, i + BATCH));
    }

    onProgress?.({
      file: basename(file),
      fileIndex: fileIndex + 1,
      fileCount: files.length,
      inserted,
      skipped,
    });
  }

  return { inserted, skipped, files: files.length };
}

async function postBatch(workerUrl: string, token: string, tracks: TrackRow[]): Promise<number> {
  const res = await fetch(`${workerUrl}/api/tracks`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ tracks }),
  });
  if (!res.ok) {
    // Fail the whole import rather than continuing: a silent partial import is
    // worse than a clear failure, because the gap is invisible in the charts.
    throw new Error(`Worker rejected a batch: HTTP ${res.status} ${await res.text()}`);
  }
  const body = (await res.json()) as { inserted?: number };
  return body.inserted ?? 0;
}

const basename = (path: string) => path.split(/[\\/]/).pop() ?? path;

/**
 * Ask the Worker to pull the last ~50 plays now.
 *
 * Offered right after authorizing, because Spotify takes days to send the full
 * export and the hourly cron may be up to an hour away — otherwise a new user's
 * first sight of the dashboard is an empty one.
 *
 * This used to be `spotify-mcp sync`, which needed the Spotify tokens on this
 * machine. They live only in D1 now, so the Worker is the only thing that can.
 */
export async function syncRecentPlays(): Promise<{ inserted: number }> {
  const cfg = await getConfig();
  if (!cfg.configured.worker) {
    throw new Error("Set up Cloud sync first — fetching plays runs on your Worker.");
  }
  const res = await fetch(`${cfg.worker_url}/api/sync`, {
    method: "POST",
    headers: { Authorization: `Bearer ${cfg.worker_auth_token}` },
  });
  const body = (await res.json()) as { inserted?: number; error?: string };
  if (!res.ok) {
    throw new Error(body.error ?? `Worker sync failed: HTTP ${res.status}`);
  }
  return { inserted: body.inserted ?? 0 };
}

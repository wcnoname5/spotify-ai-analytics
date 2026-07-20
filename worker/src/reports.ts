import type { Env } from "./tracks";

export interface ReportRow {
  id: string;
  style: string;
  period_type: string;
  start_date: string;
  end_date: string;
  provider: string;
  model: string;
  generated_at: string;
  revision_count: number;
  report_text: string;
}

const COLUMNS = [
  "id", "style", "period_type", "start_date", "end_date",
  "provider", "model", "generated_at", "revision_count", "report_text", "synced",
] as const;

// synced is local-only bookkeeping; anything in D1 is synced by definition.
const INSERT_SQL = `INSERT OR IGNORE INTO reports (${COLUMNS.join(
  ", "
)}) VALUES (${COLUMNS.map(() => "?").join(", ")})`;

function badRequest(message: string): Response {
  return new Response(message, { status: 400 });
}

function isReportRow(value: unknown): value is ReportRow {
  if (typeof value !== "object" || value === null) return false;
  const row = value as Record<string, unknown>;
  return (
    typeof row.id === "string" &&
    typeof row.generated_at === "string" &&
    typeof row.report_text === "string"
  );
}

const ISO_RE = /^\d{4}-\d{2}-\d{2}T/;

/** POST /api/reports body = one report row -> { inserted: 0|1 } */
export async function handlePostReport(request: Request, env: Env): Promise<Response> {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return badRequest("Malformed JSON body");
  }
  if (!isReportRow(body)) return badRequest("Report requires id, generated_at, report_text");

  const result = await env.DB.prepare(INSERT_SQL)
    .bind(
      body.id, body.style ?? "", body.period_type ?? "", body.start_date ?? "",
      body.end_date ?? "", body.provider ?? "", body.model ?? "",
      body.generated_at, body.revision_count ?? 0, body.report_text, 1
    )
    .run();
  return Response.json({ inserted: result.meta.changes ?? 0 });
}

/** GET /api/reports?since=<iso> -> { reports: [...] } */
export async function handleGetReports(request: Request, env: Env): Promise<Response> {
  const since = new URL(request.url).searchParams.get("since");
  if (since === null || !ISO_RE.test(since)) return badRequest("Provide 'since' (ISO-8601)");
  const { results } = await env.DB.prepare(
    "SELECT * FROM reports WHERE generated_at > ? ORDER BY generated_at ASC"
  ).bind(since).all();
  return Response.json({ reports: results });
}

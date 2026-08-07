<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { marked } from "marked";
import DOMPurify from "dompurify";
import { isTauri } from "./lib/db";
import { periodRange, type ReportPeriod } from "./lib/period";
import { listReports, getReportText, reportExistsForPeriod, saveReportLocal, type ReportMeta } from "./lib/queries";
import { syncReports } from "./lib/sync";

type Provider = "google" | "openai";
// ponytail: placeholder model lists — swap for real favorites anytime.
const MODELS: Record<Provider, string[]> = {
  google: ["gemini-3.5-flash", "gemini-flash-lite-latest"],
  openai: ["gpt-5", "gpt-5-mini"],
};

const style = ref<"listening_review" | "roast">("listening_review");
const period = ref<ReportPeriod>("weekly");
const provider = ref<Provider>("google");
const model = ref(MODELS.google[0]);
watch(provider, (p) => (model.value = MODELS[p][0]));

const running = ref(false);
const report = ref("");
const caption = ref<captionInfo>({
  analysisPeriod: "",
  generated_at: "",
  model: "",
  style: "listening_review",
});
const error = ref("");

interface captionInfo {
  analysisPeriod: string;
  generated_at: string;
  model: string; // TODO: should be one of the MODELS[provider]
  style: "listening_review" | "roast"; // TODO: in later it shouln't be hardcoded
}

const saved = ref(false);
const pastReports = ref<ReportMeta[]>([]);
const filterStyle = ref<"all" | "listening_review" | "roast">("all");
const filterPeriod = ref<"all" | ReportPeriod>("all");
const filteredReports = computed(() =>
  pastReports.value.filter(
    (r) =>
      (filterStyle.value === "all" || r.style === filterStyle.value) &&
      (filterPeriod.value === "all" || r.period_type === filterPeriod.value)
  )
);
// params of the currently displayed report (outlive the selects)
const lastRun = ref<{
  start: string;
  end: string;
  periodType: string;
  style: "listening_review" | "roast";
  provider: Provider;
  model: string;
} | null>(null);

onMounted(async () => {
  if (isTauri) pastReports.value = await listReports();
});

// LLM output crosses into the webview as HTML — sanitize before v-html.
const reportHtml = computed(() =>
  report.value ? DOMPurify.sanitize(marked.parse(report.value, { async: false })) : ""
);

const STYLE_LABELS: Record<captionInfo["style"], string> = {
  listening_review: "Listening review",
  roast: "Roast",
};

function makeCaption(
  start: string,
  end: string,
  generated_at: string,
  model: string,
  style: captionInfo["style"]
): captionInfo {
  return { analysisPeriod: `${start} → ${end}`, generated_at, model, style };
}

async function generate() {
  const { start, end, periodType } = periodRange(period.value);
  if (await reportExistsForPeriod(start, end)) {
    const ok = await invoke<boolean>("confirm_dialog", {
      title: "Report exists",
      message: `A report for ${start} → ${end} is already saved. Generate another? (Saving keeps both.)`,
    });
    if (!ok) return;
  }
  running.value = true;
  error.value = "";
  try {
    report.value = await invoke<string>("generate_report", {
      style: style.value, start, end, periodType,
      provider: provider.value, model: model.value,
    });
    caption.value = makeCaption(
      start, end, new Date().toISOString().replace(/\.\d{3}Z$/, "Z"), model.value, style.value
    );
    lastRun.value = { start, end, periodType, style: style.value, provider: provider.value, model: model.value };
    saved.value = false;
  } catch (e) {
    error.value = String(e);
  } finally {
    running.value = false;
  }
}

async function saveToDb() {
  if (!lastRun.value || !report.value) return;
  await saveReportLocal({
    id: crypto.randomUUID(),
    style: lastRun.value.style,
    period_type: lastRun.value.periodType,
    start_date: lastRun.value.start,
    end_date: lastRun.value.end,
    provider: lastRun.value.provider,
    model: lastRun.value.model,
    generated_at: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
    revision_count: 0, // ponytail: CLI prints markdown only; thread real count through when it matters
    report_text: report.value,
  }); // synced=0 — survives offline
  saved.value = true;
  pastReports.value = await listReports();
  syncReports().catch(console.error); // fail-soft push; retried on next startup
}

async function exportMd() {
  if (!lastRun.value || !report.value) return;
  await invoke("export_report_md", {
    content: report.value,
    suggestedName: `report-${lastRun.value.style}-${lastRun.value.start}.md`,
  });
}

async function openReport(meta: ReportMeta) {
  const text = await getReportText(meta.id);
  if (text === null) return;
  report.value = text;
  // TODO: 要讓上面印出的是html format不是
  caption.value = {
    analysisPeriod: `${meta.start_date} → ${meta.end_date}`,
    generated_at: meta.generated_at,
    model: meta.model,
    // revision_count: meta.revision_count,
    style: meta.style as "listening_review" | "roast"
  };
  lastRun.value = {
    start: meta.start_date,
    end: meta.end_date,
    periodType: meta.period_type,
    style: meta.style as "listening_review" | "roast",
    provider: meta.provider as Provider,
    model: meta.model,
  };
  saved.value = true; // already persisted
}
</script>

<template>
  <div class="card">
    <h3>AI Report</h3>
    <p v-if="!isTauri" class="banner">Reports need the desktop app — run <code>npm run tauri dev</code>.</p>
    <div class="filters">
      <label class="field">
        <span>Style</span>
        <select v-model="style">
          <option value="listening_review">Listening review</option>
          <option value="roast">Roast</option>
        </select>
      </label>
      <label class="field">
        <span>Period</span>
        <select v-model="period">
          <option value="weekly">Last week (Mon–Sun)</option>
          <option value="monthly">Last month</option>
          <option value="quarterly">Last quarter</option>
        </select>
      </label>
      <label class="field">
        <span>Provider</span>
        <select v-model="provider">
          <option value="google">Gemini</option>
          <option value="openai">OpenAI</option>
        </select>
      </label>
      <label class="field">
        <span>Model</span>
        <select v-model="model">
          <option v-for="m in MODELS[provider]" :key="m" :value="m">{{ m }}</option>
        </select>
      </label>
      <button class="btn btn-primary" :disabled="!isTauri || running" @click="generate">
        {{ running ? "Generating…" : "Generate" }}
      </button>
    </div>
    <p v-if="running">This takes a minute — multiple LLM calls.</p>
    <p v-if="error" class="banner">Report failed: <br> <code>{{ error }}</code></p>
    <template v-if="report">
      <div class="caption">
        <p><b>分析區間: </b>{{ caption.analysisPeriod }}</p>
        <p><b>分析風格: </b>{{ STYLE_LABELS[caption.style] }}</p>
        <p><b>模型: </b>{{ caption.model }}</p>
        <p><b>報告產生時間: </b>{{ new Date(caption.generated_at).toLocaleString() }}</p>
      </div>
      <hr class="nav-divider" />

      <div class="report-html" v-html="reportHtml"></div>
      <div class="action">
        <button class="btn" :disabled="saved" @click="saveToDb">
          {{ saved ? "Saved" : "Save to DB" }}
        </button>
        <button class="btn" @click="exportMd">Export</button>
      </div>
      <hr class="nav-divider" />
    </template>
    <template v-if="pastReports.length">
      <h3>Past reports</h3>
      <div class="filters">
        <label class="field">
          <span>Style</span>
          <select v-model="filterStyle">
            <!-- TODO: Add more options in the future as needed -->
            <option value="all">All</option>
            <option value="listening_review">Listening review</option>
            <option value="roast">Roast</option>
          </select>
        </label>
        <label class="field">
          <span>Period</span>
          <select v-model="filterPeriod">
            <option value="all">All</option>
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
            <option value="quarterly">Quarterly</option>
          </select>
        </label>
      </div>
      <div class="report-grid-scroll">
        <div class="report-grid">
          <button
            v-for="r in filteredReports"
            :key="r.id"
            class="report-card"
            @click="openReport(r)"
          >
            <div class="report-period">{{ r.start_date }} → {{ r.end_date }}</div>
            <span class="pill" :class="r.style">{{ STYLE_LABELS[r.style as captionInfo['style']] }}</span>
            <div class="report-model">{{ r.model }}</div>
            <div class="report-generated">{{ new Date(r.generated_at).toLocaleString() }}</div>
          </button>
          <p v-if="!filteredReports.length" class="muted">No reports match these filters.</p>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.caption p {
  margin: 0.40rem 0;
}
.report-grid-scroll {
  max-height: 24rem;
  overflow-y: auto;
}
.report-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 220px));
  gap: 1rem;
  margin-top: 0.5rem;
}
.report-card {
  font: inherit;
  text-align: left;
  cursor: pointer;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.report-card:hover {
  border-color: var(--muted);
}
.report-period {
  font-weight: 600;
  color: var(--ink);
}
.report-model {
  color: var(--ink-2);
  font-size: 0.85rem;
}
.report-generated {
  color: var(--muted);
  font-size: 0.75rem;
}
.pill {
  align-self: flex-start;
  border-radius: 999px;
  border: 1px solid var(--border);
  padding: 0.1rem 0.55rem;
  font-size: 0.75rem;
}
.pill.roast { border-color: var(--down); }
.pill.listening_review { border-color: var(--series); }
.muted {
  color: var(--muted);
}
.btn-primary {
  background: var(--series);
  border-color: var(--series);
  color: #fff;
  font-weight: 600;
}
.btn-primary:hover:not(:disabled) {
  border-color: var(--series);
  opacity: 0.9;
}
</style>

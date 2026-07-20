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
const caption = ref("");
const error = ref("");

const saved = ref(false);
const pastReports = ref<ReportMeta[]>([]);
// params of the currently displayed report (outlive the selects)
const lastRun = ref<{ start: string; end: string; periodType: string } | null>(null);

onMounted(async () => {
  if (isTauri) pastReports.value = await listReports();
});

// LLM output crosses into the webview as HTML — sanitize before v-html.
const reportHtml = computed(() =>
  report.value ? DOMPurify.sanitize(marked.parse(report.value, { async: false })) : ""
);

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
    caption.value = `${style.value} · ${model.value} · ${start} → ${end}`;
    lastRun.value = { start, end, periodType };
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
    style: style.value,
    period_type: lastRun.value.periodType,
    start_date: lastRun.value.start,
    end_date: lastRun.value.end,
    provider: provider.value,
    model: model.value,
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
    suggestedName: `report-${style.value}-${lastRun.value.start}.md`,
  });
}

async function openReport(meta: ReportMeta) {
  const text = await getReportText(meta.id);
  if (text === null) return;
  report.value = text;
  caption.value = `${meta.style} · ${meta.model} · ${meta.start_date} → ${meta.end_date}`;
  lastRun.value = { start: meta.start_date, end: meta.end_date, periodType: meta.period_type };
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
    </div>
    <div class="action">
      <button class="range-btn" :disabled="!isTauri || running" @click="generate">
        {{ running ? "Generating…" : "Generate" }}
      </button>
    </div>
    <p v-if="running">This takes a minute — multiple LLM calls.</p>
    <p v-if="error" class="banner">Report failed: <br> <code>{{ error }}</code></p>
    <template v-if="report">
      <p class="period">{{ caption }}</p>
      <div class="report-html" v-html="reportHtml"></div>
      <div class="action">
        <button class="range-btn" :disabled="saved" @click="saveToDb">
          {{ saved ? "Saved" : "Save to DB" }}
        </button>
        <button class="range-btn" @click="exportMd">Export .md</button>
      </div>
    </template>
    <template v-if="pastReports.length">
      <h3>Past reports</h3>
      <ul class="past-reports">
        <li v-for="r in pastReports" :key="r.id">
          <a href="#" @click.prevent="openReport(r)">
            {{ r.start_date }} → {{ r.end_date }} · {{ r.style }} · {{ r.model }}
          </a>
        </li>
      </ul>
    </template>
  </div>
</template>

<style scoped>
.past-reports {
  list-style: none;
  padding: 0;
  margin: 0.5rem 0 0;
}
.past-reports li {
  padding: 0.25rem 0;
}
.past-reports a {
  text-decoration: none;
}
.past-reports a:hover {
  text-decoration: underline;
}
</style>

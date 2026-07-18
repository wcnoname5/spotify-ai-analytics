<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { marked } from "marked";
import DOMPurify from "dompurify";
import { isTauri } from "./lib/db";
import { periodRange, type ReportPeriod } from "./lib/period";

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

// LLM output crosses into the webview as HTML — sanitize before v-html.
const reportHtml = computed(() =>
  report.value ? DOMPurify.sanitize(marked.parse(report.value, { async: false })) : ""
);

async function generate() {
  const { start, end, periodType } = periodRange(period.value);
  running.value = true;
  error.value = "";
  try {
    report.value = await invoke<string>("generate_report", {
      style: style.value, start, end, periodType,
      provider: provider.value, model: model.value,
    });
    caption.value = `${style.value} · ${model.value} · ${start} → ${end}`;
  } catch (e) {
    error.value = String(e);
  } finally {
    running.value = false;
  }
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
          <option value="seasonal">Last quarter</option>
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
    </template>
  </div>
</template>

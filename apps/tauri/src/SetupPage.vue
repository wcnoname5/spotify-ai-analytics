<script setup lang="ts">
// One-time setup, as a front-end over the existing Python wizard steps.
// Every action spawns a `spotify-mcp` subcommand — the same step functions the
// interactive CLI wizard drives, minus its prompts. Nothing here reimplements
// OAuth, Fernet, or ingestion; a third component touching tokens would break
// the rule that only spotify_client/ and the Worker decrypt.
import { onMounted, reactive, ref } from "vue";
import { openUrl } from "@tauri-apps/plugin-opener";
import { isTauri } from "./lib/db";
import {
  getConfig,
  pickHistoryFolder,
  runDoctor,
  runSetupStep,
  setConfig,
  type DoctorReport,
  type SetupStep,
} from "./lib/config";

const DASHBOARD_URL = "https://developer.spotify.com/dashboard";

const doctor = ref<DoctorReport | null>(null);
const envFile = ref("");
const loading = ref(true);
const savedNotice = ref(false);

// Secrets are never read back into the form: `config get` returns only what the
// app itself needs, so these stay blank and a blank field means "leave as-is".
const form = reactive({
  SPOTIFY_CLIENT_ID: "",
  GEMINI_API_KEY: "",
  OPENAI_API_KEY: "",
  LANGFUSE_PUBLIC_KEY: "",
  LANGFUSE_SECRET_KEY: "",
  LANGFUSE_BASE_URL: "",
  LANGSMITH_API_KEY: "",
  LANGSMITH_PROJECT: "",
  WORKER_URL: "",
  WORKER_AUTH_TOKEN: "",
});

// Per-step run state, so a failure shows its own output instead of one global error.
type StepState = { running: boolean; ok: boolean | null; output: string };
const steps = reactive<Record<SetupStep, StepState>>({
  keygen: { running: false, ok: null, output: "" },
  oauth: { running: false, ok: null, output: "" },
  import: { running: false, ok: null, output: "" },
});

const CHECK_LABELS: Record<string, string> = {
  client_id: "Spotify Client ID",
  fernet_key: "Encryption key",
  dbs_initialized: "Databases initialized",
  tokens_valid: "Spotify authorized",
  history_has_data: "Listening history imported",
};

async function refresh() {
  loading.value = true;
  try {
    const cfg = await getConfig();
    envFile.value = cfg.env_file;
    form.WORKER_URL = cfg.worker_url;
    doctor.value = await runDoctor();
  } catch (e) {
    console.error("setup refresh failed:", e);
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  if (isTauri) refresh();
  else loading.value = false;
});

async function save() {
  // Blank means "don't touch": sending "" would wipe an existing key.
  const values = Object.fromEntries(
    Object.entries(form).filter(([, v]) => v.trim() !== "")
  ) as Record<string, string>;
  if (!Object.keys(values).length) return;
  await setConfig(values);
  // Clear the secret inputs so keys don't linger on screen after saving.
  for (const k of Object.keys(values)) form[k as keyof typeof form] = "";
  savedNotice.value = true;
  await refresh();
}

async function runStep(step: SetupStep) {
  const state = steps[step];
  state.running = true;
  state.ok = null;
  state.output = "";
  try {
    let arg: string | undefined;
    if (step === "import") {
      const folder = await pickHistoryFolder();
      if (!folder) return; // cancelled
      arg = folder;
    }
    state.output = await runSetupStep(step, arg);
    state.ok = true;
    await refresh();
  } catch (e) {
    state.ok = false;
    state.output = String(e);
  } finally {
    state.running = false;
  }
}
</script>

<template>
  <section class="setup">
    <h2>Setup</h2>

    <p v-if="!isTauri" class="hint">Setup is only available in the desktop app.</p>
    <p v-else-if="loading" class="hint">Checking your environment…</p>

    <template v-else>
      <!-- Readiness, straight from `spotify-mcp doctor --json`. -->
      <div class="card">
        <div class="card-head">
          <h3>Status</h3>
          <button class="btn" @click="refresh">Re-check</button>
        </div>
        <ul class="checks">
          <li v-for="(ok, key) in doctor?.checks ?? {}" :key="key">
            <span :class="ok ? 'ok' : 'pending'">{{ ok ? "✓" : "○" }}</span>
            {{ CHECK_LABELS[key] ?? key }}
          </li>
        </ul>
        <p v-if="doctor?.message" class="hint">{{ doctor.message }}</p>
        <p v-for="w in doctor?.warnings ?? []" :key="w" class="warn">{{ w }}</p>
      </div>

      <!-- Steps that spawn a subcommand. Buffered: output appears when done. -->
      <div class="card">
        <h3>Actions</h3>

        <div class="step">
          <button class="btn" :disabled="steps.keygen.running" @click="runStep('keygen')">
            {{ steps.keygen.running ? "Working…" : "Generate encryption key" }}
          </button>
          <span class="hint">Created once. Never regenerated — that would orphan saved tokens.</span>
        </div>

        <div class="step">
          <button class="btn" :disabled="steps.oauth.running" @click="runStep('oauth')">
            {{ steps.oauth.running ? "Waiting for browser…" : "Authorize Spotify" }}
          </button>
          <span class="hint">Opens your browser. Needs the Client ID and encryption key first.</span>
        </div>

        <div class="step">
          <button class="btn" :disabled="steps.import.running" @click="runStep('import')">
            {{ steps.import.running ? "Importing…" : "Import history…" }}
          </button>
          <span class="hint">Pick the folder of <code>Streaming_History_Audio_*.json</code> files.</span>
        </div>

        <template v-for="(state, name) in steps" :key="name">
          <details v-if="state.ok === false" class="failure" open>
            <summary>{{ name }} failed</summary>
            <pre>{{ state.output }}</pre>
          </details>
        </template>
      </div>

      <!-- Forms. Blank fields are left untouched on save. -->
      <div class="card">
        <h3>Spotify</h3>
        <p class="hint">
          Create an app on the dashboard, then paste its Client ID. Use
          <code>http://127.0.0.1:8888/callback</code> as the redirect URI —
          <code>localhost</code> is rejected by Spotify.
        </p>
        <button class="btn" @click="openUrl(DASHBOARD_URL)">Open Spotify dashboard</button>
        <label>Client ID <input v-model="form.SPOTIFY_CLIENT_ID" placeholder="unchanged" /></label>
      </div>

      <div class="card">
        <h3>LLM</h3>
        <label>Google API key <input v-model="form.GEMINI_API_KEY" type="password" placeholder="unchanged" /></label>
        <label>OpenAI API key <input v-model="form.OPENAI_API_KEY" type="password" placeholder="unchanged" /></label>
      </div>

      <div class="card">
        <h3>Tracing <span class="hint">(optional)</span></h3>
        <label>Langfuse public key <input v-model="form.LANGFUSE_PUBLIC_KEY" type="password" placeholder="unchanged" /></label>
        <label>Langfuse secret key <input v-model="form.LANGFUSE_SECRET_KEY" type="password" placeholder="unchanged" /></label>
        <label>Langfuse base URL <input v-model="form.LANGFUSE_BASE_URL" placeholder="unchanged" /></label>
        <label>LangSmith API key <input v-model="form.LANGSMITH_API_KEY" type="password" placeholder="unchanged" /></label>
        <label>LangSmith project <input v-model="form.LANGSMITH_PROJECT" placeholder="unchanged" /></label>
      </div>

      <!-- Phase 3 landing point: paste the values, scripts/setup_cloud.sh does the deploy. -->
      <div class="card">
        <h3>Cloud sync</h3>
        <p class="hint">
          Deploy the Worker with <code>scripts/setup_cloud.sh</code>, then paste its URL and token here.
        </p>
        <label>Worker URL <input v-model="form.WORKER_URL" placeholder="https://….workers.dev" /></label>
        <label>Worker token <input v-model="form.WORKER_AUTH_TOKEN" type="password" placeholder="unchanged" /></label>
      </div>

      <div class="save-row">
        <button class="btn current" @click="save">Save settings</button>
        <span v-if="savedNotice" class="hint">Saved to {{ envFile }} — restart the app to apply.</span>
      </div>
    </template>
  </section>
</template>

<style scoped>
.setup { display: flex; flex-direction: column; gap: 1rem; max-width: 46rem; }
.card { display: flex; flex-direction: column; gap: 0.6rem; }
.checks { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.3rem; }
.ok { color: var(--series); font-weight: 700; }
.pending { color: var(--muted); }
.step { display: flex; align-items: center; gap: 0.8rem; flex-wrap: wrap; }
label { display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.85rem; color: var(--ink-2); }
input { font: inherit; padding: 0.35rem 0.5rem; border: 1px solid var(--border); border-radius: 8px; background: transparent; color: var(--ink); }
.hint { font-size: 0.8rem; color: var(--muted); }
.warn { font-size: 0.8rem; color: #d08770; }
.failure pre { white-space: pre-wrap; font-size: 0.75rem; max-height: 14rem; overflow: auto; }
.save-row { display: flex; align-items: center; gap: 0.8rem; }
</style>

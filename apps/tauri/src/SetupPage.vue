<script setup lang="ts">
// One-time setup, as a front-end over the existing Python wizard steps.
// Every action spawns only a `spotify-mcp` subcommand: the same step functions the
// interactive CLI wizard drives.
//
// Two modes, one template. First run is a wizard: one card at a time, in the same
// order the CLI walks, so nobody has to work out what to press next. `showAll`
// flips to the whole page at once, which is the right shape for coming back later
// to rotate a key.
import { computed, onMounted, reactive, ref } from "vue";
import { openUrl } from "@tauri-apps/plugin-opener";
import { isTauri } from "./lib/db";
import {
  getConfig,
  pickHistoryFolder,
  runDoctor,
  runSetupStep,
  setConfig,
  type ConfiguredFlags,
  type DoctorReport,
  type SetupStep,
} from "./lib/config";

const DASHBOARD_URL = "https://developer.spotify.com/dashboard";

const doctor = ref<DoctorReport | null>(null);
const envFile = ref("");
const loading = ref(true);
const savedNotice = ref(false);
const showAll = ref(false);

const configured = ref<ConfiguredFlags>({
  gemini: false, openai: false, langfuse: false, langsmith: false, worker: false,
});

// Langfuse and LangSmith do the same job; picking one keeps the form short.
type Tracing = "none" | "langfuse" | "langsmith";
const tracing = ref<Tracing>("none");

// Secrets are never read back into the form: `config get` reports only whether
// each is set. Blank therefore means "leave as-is", not "clear it".
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

// keygen is not here: it needs no decision from the user, so it runs
// automatically (see refresh) rather than being a step they must remember.
type ManualStep = Exclude<SetupStep, "keygen">;
type StepState = { running: boolean; ok: boolean | null; output: string };
const steps = reactive<Record<ManualStep, StepState>>({
  oauth: { running: false, ok: null, output: "" },
  import: { running: false, ok: null, output: "" },
  sync: { running: false, ok: null, output: "" },
});

// Only ever attempted once per session, so a failing keygen cannot loop.
const keygenTried = ref(false);
const keygenError = ref("");

const CHECK_LABELS: Record<string, string> = {
  client_id: "Spotify Client ID",
  fernet_key: "Encryption key",
  dbs_initialized: "Databases initialized",
  tokens_valid: "Spotify authorized",
  history_has_data: "Listening history imported",
};

const checks = computed(() => doctor.value?.checks ?? {});
const hasLlm = computed(() => configured.value.gemini || configured.value.openai);
const hasTracing = computed(() => configured.value.langfuse || configured.value.langsmith);
const allReady = computed(() => doctor.value?.ready === true && hasLlm.value);

// Mirrors the order of run_wizard() in apps/mcp/spotify_mcp/wizard/__init__.py.
// Deliberately a literal rather than something shared with Python: the two
// front-ends have different step sets (no spotify_app/claude_desktop here, no
// cloud-paste there), so a shared list would need filtering on both sides to be
// usable. What *is* shared is `doctor --json`'s checks, which drive stepDone.
const ORDER = ["client_id", "oauth", "history", "llm", "tracing", "worker"] as const;
type WizardStep = (typeof ORDER)[number];

const STEP_LABELS: Record<WizardStep, string> = {
  client_id: "Spotify Client ID",
  oauth: "Authorize Spotify",
  history: "Listening history",
  llm: "LLM provider",
  tracing: "Tracing",
  worker: "Cloud sync",
};

// fernet_key and dbs_initialized are not steps: the key is generated on sight
// (see refresh) and each spawned subcommand now creates its own schema.
const stepDone: Record<WizardStep, () => boolean> = {
  client_id: () => !!checks.value.client_id,
  oauth: () => !!checks.value.tokens_valid,
  history: () => !!checks.value.history_has_data,
  llm: () => hasLlm.value,
  tracing: () => hasTracing.value,
  worker: () => configured.value.worker,
};

// ponytail: session-scoped. Restarting re-offers whatever was skipped, which is
// the behaviour we want -- skipping means "not now", not "never ask again".
const skipped = reactive(new Set<WizardStep>());

const current = computed<WizardStep | null>(
  () => ORDER.find((s) => !stepDone[s]() && !skipped.has(s)) ?? null,
);
const stepNumber = computed(() =>
  current.value ? ORDER.indexOf(current.value) + 1 : ORDER.length,
);

/** Wizard mode reveals one step; `showAll` is the whole page for later edits. */
const need = (step: WizardStep) => showAll.value || current.value === step;

function skipStep() {
  if (current.value) skipped.add(current.value);
}

async function refresh() {
  loading.value = true;
  try {
    const cfg = await getConfig();
    envFile.value = cfg.env_file;
    form.WORKER_URL = cfg.worker_url;
    configured.value = cfg.configured;
    if (cfg.configured.langfuse) tracing.value = "langfuse";
    else if (cfg.configured.langsmith) tracing.value = "langsmith";

    let report = await runDoctor();
    // Generating the Fernet key takes no input and OAuth refuses to run without
    // it, so create it on sight instead of asking the user to press a button
    // whose only correct answer is "yes". ensure_fernet_key never overwrites an
    // existing key, so this cannot rotate one out from under stored tokens.
    if (!report.checks?.fernet_key && !keygenTried.value) {
      keygenTried.value = true;
      try {
        await runSetupStep("keygen");
        report = await runDoctor();
      } catch (e) {
        keygenError.value = String(e);
      }
    }
    doctor.value = report;
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

/** Keys belonging to the tracing provider the user did not pick. */
function unusedTracingKeys(): (keyof typeof form)[] {
  if (tracing.value === "langfuse")
    return ["LANGSMITH_API_KEY", "LANGSMITH_PROJECT"];
  if (tracing.value === "langsmith")
    return ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"];
  return ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL",
          "LANGSMITH_API_KEY", "LANGSMITH_PROJECT"];
}

async function save() {
  const skip = new Set<string>(unusedTracingKeys());
  const values = Object.fromEntries(
    Object.entries(form).filter(([k, v]) => v.trim() !== "" && !skip.has(k))
  ) as Record<string, string>;
  // LangSmith only traces when the flag is on; setting the key alone does nothing.
  if (tracing.value === "langsmith" && values.LANGSMITH_API_KEY)
    values.LANGSMITH_TRACING = "true";
  if (!Object.keys(values).length) return;
  await setConfig(values);
  for (const k of Object.keys(values)) {
    if (k in form) form[k as keyof typeof form] = "";
  }
  savedNotice.value = true;
  await refresh();
}

async function runStep(step: ManualStep) {
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
    <div class="card-head">
      <h2>Setup</h2>
      <button class="btn" @click="showAll = !showAll">
        {{ showAll ? "Show only what's missing" : "Show all settings" }}
      </button>
    </div>

    <p v-if="!isTauri" class="hint">Setup is only available in the desktop app.</p>
    <p v-else-if="loading" class="hint">Checking your environment…</p>

    <template v-else>
      <!-- Wizard progress. Hidden in showAll, where there is no "current" step. -->
      <p v-if="!showAll && current" class="progress">
        Step {{ stepNumber }} of {{ ORDER.length }} · {{ STEP_LABELS[current] }}
      </p>

      <div v-if="!current && !showAll" class="card">
        <h3><span class="ok">✓</span> Setup complete</h3>
        <p class="hint">
          {{ allReady ? "Everything is ready." : "Everything essential is done; skipped items are still available under “Show all settings”." }}
          Restart the app to apply what you saved.
        </p>
      </div>

      <p v-if="keygenError" class="warn">Could not create the encryption key: {{ keygenError }}</p>

      <!-- Outstanding items only; a passing check drops off the list. -->
      <div v-if="!allReady || showAll" class="card">
        <div class="card-head">
          <h3>{{ showAll ? "Status" : "Still needed" }}</h3>
          <button class="btn" @click="refresh">Re-check</button>
        </div>
        <ul class="checks">
          <template v-for="(ok, key) in checks" :key="key">
            <li v-if="showAll || !ok">
              <span :class="ok ? 'ok' : 'pending'">{{ ok ? "✓" : "○" }}</span>
              {{ CHECK_LABELS[key] ?? key }}
            </li>
          </template>
          <li v-if="!hasLlm"><span class="pending">○</span> LLM API key (needed for reports)</li>
        </ul>
        <p v-for="w in doctor?.warnings ?? []" :key="w" class="warn">{{ w }}</p>
      </div>

      <div v-if="need('client_id')" class="card">
        <h3>Spotify</h3>
        <p class="hint">
          Create an app on the dashboard, then paste its Client ID. Use
          <code>http://127.0.0.1:8888/callback</code> as the redirect URI —
          <code>localhost</code> is rejected by Spotify.
        </p>
        <button class="btn" @click="openUrl(DASHBOARD_URL)">Open Spotify dashboard</button>
        <label>Client ID <input v-model="form.SPOTIFY_CLIENT_ID" placeholder="unchanged" /></label>
        <div v-if="!showAll" class="step">
          <button class="btn current" @click="save">Save and continue</button>
        </div>
      </div>

      <div v-if="need('oauth')" class="card">
        <h3>Authorize Spotify</h3>
        <div class="step">
          <button class="btn current" :disabled="steps.oauth.running" @click="runStep('oauth')">
            {{ steps.oauth.running ? "Waiting for browser…" : "Authorize Spotify" }}
          </button>
          <span class="hint">Opens your browser. Needs the Client ID saved first.</span>
        </div>
      </div>

      <div v-if="need('history')" class="card">
        <h3>Listening history</h3>
        <div class="step">
          <button class="btn current" :disabled="steps.import.running" @click="runStep('import')">
            {{ steps.import.running ? "Importing…" : "Import history…" }}
          </button>
          <span class="hint">Pick the folder of <code>Streaming_History_Audio_*.json</code> files.</span>
        </div>
        <!-- Spotify takes days to send the export, so a first-time user usually
             has nothing to import yet. The API's last ~50 plays fill the gap. -->
        <p class="hint">Export hasn’t arrived yet? Spotify can take a few days to send it.</p>
        <div class="step">
          <button class="btn" :disabled="steps.sync.running" @click="runStep('sync')">
            {{ steps.sync.running ? "Fetching…" : "Fetch my last 50 plays" }}
          </button>
          <button v-if="!showAll" class="btn" @click="skipStep">Skip for now</button>
        </div>
      </div>

      <template v-for="(state, name) in steps" :key="name">
        <details v-if="state.ok === false" class="failure" open>
          <summary>{{ name }} failed</summary>
          <pre>{{ state.output }}</pre>
        </details>
      </template>

      <!-- TODO: 加上href (AI Studio & OpenAI) -->
      <div v-if="need('llm')" class="card">
        <h3>LLM Provider<span class="hint"></span></h3>
        <label>Gemini API key <input v-model="form.GEMINI_API_KEY" type="password" :placeholder="configured.gemini ? 'set — leave blank to keep' : ''" /></label>
        <label>OpenAI API key <input v-model="form.OPENAI_API_KEY" type="password" :placeholder="configured.openai ? 'set — leave blank to keep' : ''" /></label>
        <div v-if="!showAll" class="step">
          <button class="btn current" @click="save">Save and continue</button>
          <span class="hint">Needed for AI reports.</span>
        </div>
      </div>

      <!-- Optional tracing: Langfuse or LangSmith  -->
      <div v-if="need('tracing')" class="card">
        <h3>Tracing <span class="hint">(optional)</span></h3>
        <div class="step">
          <label class="inline"><input type="radio" value="none" v-model="tracing" /> None</label>
          <label class="inline"><input type="radio" value="langfuse" v-model="tracing" /> Langfuse</label>
          <label class="inline"><input type="radio" value="langsmith" v-model="tracing" /> LangSmith</label>
        </div>

        <template v-if="tracing === 'langfuse'">
          <label>Public key <input v-model="form.LANGFUSE_PUBLIC_KEY" type="password" :placeholder="configured.langfuse ? 'set — leave blank to keep' : ''" /></label>
          <label>Secret key <input v-model="form.LANGFUSE_SECRET_KEY" type="password" :placeholder="configured.langfuse ? 'set — leave blank to keep' : ''" /></label>
          <label>Base URL <input v-model="form.LANGFUSE_BASE_URL" placeholder="https://cloud.langfuse.com" /></label>
        </template>

        <template v-else-if="tracing === 'langsmith'">
          <label>API key <input v-model="form.LANGSMITH_API_KEY" type="password" :placeholder="configured.langsmith ? 'set — leave blank to keep' : ''" /></label>
          <label>Project <input v-model="form.LANGSMITH_PROJECT" placeholder="spotify-ai-analytics" /></label>
        </template>
        <div v-if="!showAll" class="step">
          <button class="btn current" @click="save">Save and continue</button>
          <button class="btn" @click="skipStep">Skip</button>
        </div>
      </div>

      <!-- Phase 3 landing point: paste the values, scripts/setup_cloud.sh does the deploy. -->
      <div v-if="need('worker')" class="card">
        <h3>Cloud sync <span class="hint">(optional)</span></h3>
        <p class="hint">
          Deploy the Worker with <code>scripts/setup_cloud.sh</code>, then paste its URL and token here.
        </p>
        <label>Worker URL <input v-model="form.WORKER_URL" placeholder="https://….workers.dev" /></label>
        <label>Worker token <input v-model="form.WORKER_AUTH_TOKEN" type="password" :placeholder="configured.worker ? 'set — leave blank to keep' : ''" /></label>
        <div v-if="!showAll" class="step">
          <button class="btn current" @click="save">Save and continue</button>
          <button class="btn" @click="skipStep">Skip</button>
        </div>
      </div>

      <p v-if="showAll" class="hint">
        <span class="ok">✓</span> Encryption key set. Back up <code>{{ envFile }}</code> —
        losing this key makes every stored token permanently unreadable.
      </p>

      <!-- One global save only in showAll; the wizard saves per step. -->
      <div v-if="showAll" class="save-row">
        <button class="btn current" @click="save">Save settings</button>
      </div>
      <p v-if="savedNotice" class="hint">Saved to {{ envFile }}: restart the app to apply.</p>
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
label.inline { flex-direction: row; align-items: center; gap: 0.3rem; }
input { font: inherit; padding: 0.35rem 0.5rem; border: 1px solid var(--border); border-radius: 8px; background: transparent; color: var(--ink); }
input[type="radio"] { width: auto; }
.hint { font-size: 0.8rem; color: var(--muted); }
.warn { font-size: 0.8rem; color: #d08770; }
.failure pre { white-space: pre-wrap; font-size: 0.75rem; max-height: 14rem; overflow: auto; }
.save-row { display: flex; align-items: center; gap: 0.8rem; }
.progress { font-size: 0.8rem; color: var(--muted); letter-spacing: 0.02em; }
</style>

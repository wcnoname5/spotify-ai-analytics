<script setup lang="ts">
// One-time setup: OAuth is lib/oauth.ts, import is lib/historyImport.ts,
//  sync is a Worker call, config and keygen are Rust.
//
// Two modes, one template. First run is a wizard: one card at a time for first time setup.
// `showAll` flips to the whole page at once, which is for coming back later to rotate a key.
import { computed, nextTick, onMounted, reactive, ref } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { openUrl } from "@tauri-apps/plugin-opener";
import { isTauri } from "./lib/db";
import {
  cloudDeploy,
  getConfig,
  keygen,
  pickHistoryFolder,
  runDoctor,
  setConfig,
  type ConfiguredFlags,
  type DoctorReport,
  type SetupStep,
} from "./lib/config";
import { authorizeSpotify } from "./lib/oauth";
import { importHistory, syncRecentPlays } from "./lib/historyImport";

const DASHBOARD_URL = "https://developer.spotify.com/dashboard";
const CF_TOKEN_URL = "https://dash.cloudflare.com/profile/api-tokens";

// Cloud deploy. Unlike every other step this one streams: it runs for minutes,
// and a button stuck on "Deploying…" with no output reads as a hang.
const cfApiToken = ref("");
const cloudName = ref("spotify-analytics");
const cloudLog = ref<string[]>([]);
const logPane = ref<HTMLElement | null>(null);
const deploying = ref(false);
const deployError = ref("");
const deployOk = ref(false);
const workerUrl = ref("");
const workerToken = ref("");
const revealToken = ref(false);
const copied = ref(false);

async function copyToken() {
  await navigator.clipboard.writeText(workerToken.value);
  copied.value = true;
}

async function runDeploy(rotate: boolean) {
  deploying.value = true;
  deployError.value = "";
  cloudLog.value = [];
  try {
    await cloudDeploy(cloudName.value.trim() || "spotify-analytics", cfApiToken.value.trim(), rotate);
    cfApiToken.value = ""; // not ours to keep once the deploy is done
    deployOk.value = true;
    await refresh();
  } catch (e) {
    deployError.value = String(e);
  } finally {
    deploying.value = false;
  }
}

const doctor = ref<DoctorReport | null>(null);
const envFile = ref("");
/** Which .env this session resolved to — empty unless it is a non-default one. */
const envBadge = ref("");

/** Reveals the dashboard and closes this window (Rust owns both windows). */
const finishSetup = () => invoke("finish_setup").catch(console.error);
const loading = ref(true);
const savedNotice = ref("");
const showAll = ref(false);

const configured = ref<ConfiguredFlags>({
  client_id: false, gemini: false, openai: false, langfuse: false, langsmith: false, worker: false,
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

// keygen is not a step: it needs no decision from the user, so it runs
// automatically (see refresh) rather than being something they must remember.
//
// `oauth` is not a SetupStep: SetupStep is the list of steps that still spawn
// Python, and OAuth left it when the flow moved to lib/oauth.ts.
type ManualStep = SetupStep | "oauth";
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
  tokens_valid: "Spotify authorized",
  history_has_data: "Listening history imported",
};

const checks = computed(() => doctor.value?.checks ?? {});
const hasLlm = computed(() => configured.value.gemini || configured.value.openai);
const hasTracing = computed(() => configured.value.langfuse || configured.value.langsmith);
const allReady = computed(() => doctor.value?.ready === true && hasLlm.value);

// Dependency chain: `worker` must precede `oauth` and `history`,
// because D1 (requires worker) is now the onlu oath source.
//  llm/tracing are optional, so they go last.
const ORDER = ["client_id", "worker", "oauth", "history", "llm", "tracing"] as const;
type WizardStep = (typeof ORDER)[number];

const STEP_LABELS: Record<WizardStep, string> = {
  client_id: "Spotify Client ID",
  oauth: "Authorize Spotify",
  history: "Listening history",
  llm: "LLM provider",
  tracing: "Tracing",
  worker: "Cloud sync",
};

// fernet_key is not a step: the key is generated on sight (see refresh).
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
    if (cfg.dev) envBadge.value = `DEV · ${cfg.env_file}`;
    workerUrl.value = cfg.worker_url;
    workerToken.value = cfg.worker_auth_token;
    form.WORKER_URL = cfg.worker_url;
    configured.value = cfg.configured;
    if (cfg.configured.langfuse) tracing.value = "langfuse";
    else if (cfg.configured.langsmith) tracing.value = "langsmith";

    let report = await runDoctor();
    // Generating the Fernet key takes no input and OAuth refuses to run without
    // it. ensure_fernet_key never overwrites an
    // existing key, so this cannot rotate one out from under stored tokens.
    if (!report.checks?.fernet_key && !keygenTried.value) {
      keygenTried.value = true;
      try {
        await keygen();
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

onMounted(async () => {
  if (!isTauri) {
    loading.value = false;
    return;
  }
  await refresh();
  // Same component, two jobs: a fresh environment is a wizard, an already-set-up
  // one is Preferences (opened from the gear), where the whole page is the point.
  showAll.value = !!checks.value.client_id;

  listen<string>("cloud-log", async (e) => {
    cloudLog.value.push(e.payload);
    await nextTick();
    if (logPane.value) logPane.value.scrollTop = logPane.value.scrollHeight;
  });
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
  // Nothing to write is a normal case -- the cloud deploy already saved its own
  // values -- but returning silently made the button look broken. Always give
  // the press an effect.
  if (Object.keys(values).length) {
    await setConfig(values);
    for (const k of Object.keys(values)) {
      if (k in form) form[k as keyof typeof form] = "";
    }
    savedNotice.value = `Saved to ${envFile.value}: restart the app to apply.`;
  } else {
    savedNotice.value = "Nothing to change here.";
  }
  deployOk.value = false; // release the success card so the wizard can move on
  await refresh();
}

async function runStep(step: ManualStep) {
  const state = steps[step];
  state.running = true;
  state.ok = null;
  state.output = "";
  try {
    if (step === "oauth") {
      // No longer a spawned `spotify-mcp reauth`: Rust listens on the callback
      // port and the flow itself is TS. See lib/oauth.ts.
      const { userId } = await authorizeSpotify();
      state.output = `Authorized as ${userId}.`;
    } else if (step === "import") {
      const folder = await pickHistoryFolder();
      if (!folder) return; // cancelled
      // A full export is ~100k plays over dozens of files and takes minutes, so
      // this reports per file instead of leaving the button looking stuck.
      const result = await importHistory(folder, (p) => {
        state.output = `${p.file} (${p.fileIndex}/${p.fileCount}) — ${p.inserted} plays imported`;
      });
      state.output =
        `Imported ${result.inserted} plays from ${result.files} file(s).` +
        (result.skipped ? ` Skipped ${result.skipped} non-track records (podcasts, audiobooks).` : "");
    } else {
      // step === "sync": the Worker holds the tokens, so it does the fetching.
      const { inserted } = await syncRecentPlays();
      state.output = inserted
        ? `Fetched ${inserted} recent plays.`
        : "No new plays since the last sync.";
    }
    state.ok = true;
    await refresh();
  } catch (e) {
    state.ok = false;
    state.output = e instanceof Error ? e.message : String(e);
  } finally {
    state.running = false;
  }
}
</script>

<template>
  <section class="setup">
    <div class="card-head">
      <h2>Setup</h2>
      <span v-if="envBadge" class="env-badge" :title="envBadge">{{ envBadge }}</span>
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
        </p>
        <div class="step">
          <button class="btn current" @click="finishSetup">Done</button>
          <span class="hint">Closes this window and opens your dashboard.</span>
        </div>
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
          Create an app on the dashboard (name whatever you want), then paste its Client ID. Use
          <code>http://127.0.0.1:8888/callback</code> as the redirect URI.
        </p>
        <button class="btn" @click="openUrl(DASHBOARD_URL)">Open Spotify dashboard</button>
        <label>Client ID <input v-model="form.SPOTIFY_CLIENT_ID" placeholder="Enter your Client ID" /></label>
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
        <p class="hint"> You can request your data from <a href="https://www.spotify.com/account/privacy/" target="_blank" rel="noopener noreferrer">Spotify privacy settings</a> (takes a few days to arrive), or just fetch the last 50 plays now.</p>
        <div class="step">
          <button class="btn current" :disabled="steps.import.running" @click="runStep('import')">
            {{ steps.import.running ? "Importing…" : "Import history…" }}
          </button>
          <span class="hint">Pick the folder with <code>Streaming_History_Audio_*.json</code> files.</span>
        </div>
        <!-- Spotify takes days to send the export, so a first-time user usually
             has nothing to import yet. The API's last ~50 plays fill the gap. -->
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

      <div v-if="need('llm')" class="card">
        <h3>LLM Provider</h3>
        <p class="hint">
          You can use either <a href="https://aistudio.google.com/" target="_blank" rel="noopener noreferrer">Google's Gemini</a>
          or <a href="https://platform.openai.com/" target="_blank" rel="noopener noreferrer">OpenAI</a> as model providers for AI reports.
        </p>
        <label>Gemini API key <input v-model="form.GEMINI_API_KEY" type="password" :placeholder="configured.gemini ? 'set — leave blank to keep' : ''" /></label>
        <label>OpenAI API key <input v-model="form.OPENAI_API_KEY" type="password" :placeholder="configured.openai ? 'set — leave blank to keep' : ''" /></label>
        <div v-if="!showAll" class="step">
          <button class="btn current" @click="save">Save and continue</button>
          <button class="btn" @click="skipStep">Skip</button>
          <span class="hint">Only needed for AI reports — the dashboard works without it.</span>
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

      <!-- `|| deployOk` keeps the card up after a successful deploy: the step is
           done, so it would otherwise vanish before the result was read. -->
      <div v-if="need('worker') || deployOk" class="card">
        <h3>Cloud sync <span class="hint">(recommended)</span></h3>
        <p class="hint">
          Keeps your history safe and updating hourly, even while the app is closed.
          Without it this machine's copy is the only one.
        </p>

        <!-- Connected: the token exists nowhere but this machine (Cloudflare
             secrets are write-only), so showing and copying it is the only
             backup the user can make, and rotating is the only "recovery". -->
        <template v-if="configured.worker">
          <p class="hint"><span class="ok">✓</span> Connected to <code>{{ workerUrl }}</code></p>
          <label>Worker token
            <input :type="revealToken ? 'text' : 'password'" :value="workerToken" readonly />
          </label>
          <div class="step">
            <button class="btn" @click="revealToken = !revealToken">{{ revealToken ? "Hide" : "Reveal" }}</button>
            <button class="btn" @click="copyToken">{{ copied ? "Copied" : "Copy" }}</button>
            <button class="btn" :disabled="deploying" @click="runDeploy(true)">Rotate token</button>
            <span class="hint">Cloudflare cannot show you this token — back it up with <code>{{ envFile }}</code>.</span>
          </div>
        </template>
        <!-- Not connected: one credential, one button. -->
        <template v-else>
          <!-- WIP: need to reformat UI -->
          <p class="hint">create one at <a href="https://dash.cloudflare.com" target="_blank">Cloudflare Dashboard</a> → API Tokens, Permissions: enable 
            <code>[Account] [D1] [Edit]</code> and <code>[Account] [Workers Scripts] [Edit]</code>
          </p>
          <label>Cloudflare API token
            <input v-model="cfApiToken" type="password" placeholder="" />
          </label>
          <label>Name <input v-model="cloudName" placeholder="spotify-analytics" /></label>
          <div class="step">
            <button class="btn" @click="openUrl(CF_TOKEN_URL)">Get a token ↗</button>
            <button class="btn current" :disabled="deploying" @click="runDeploy(false)">
              {{ deploying ? "Deploying…" : "Deploy to Cloudflare" }}
            </button>
          </div>
          <p class="hint">
            Takes a few minutes. Creates a D1 database and a Worker in your own
            Cloudflare account.
          </p>
        </template>

        <pre v-if="cloudLog.length" ref="logPane" class="cloud-log">{{ cloudLog.join("\n") }}</pre>
        <p v-if="deployError" class="warn">{{ deployError }}</p>

        <!-- The log ends in wrangler's own output, which does not read as "done".
             Say so, and say what to press next. -->
        <p v-if="deployOk" class="ok-box">
          <span class="ok">✓</span> <strong>Deployment succeeded.</strong>
          Your Worker is live and will sync your listening history every hour, even
          while this app is closed. Press <strong>Save and continue</strong> below.
        </p>

        <details v-if="!configured.worker">
          <summary class="hint">Connect to an existing Worker instead</summary>
          <p class="hint">
            The token is the one written to that Worker's <code>.env</code> when it was deployed —
            Cloudflare cannot show it to you.
          </p>
          <label>Worker URL <input v-model="form.WORKER_URL" placeholder="https://….workers.dev" /></label>
          <label>Worker token <input v-model="form.WORKER_AUTH_TOKEN" type="password" /></label>
        </details>

        <div v-if="!showAll" class="step">
          <button class="btn current" @click="save">Save and continue</button>
          <!-- Nothing left to skip once the Worker is up. -->
          <button v-if="!configured.worker" class="btn" @click="skipStep">Skip</button>
        </div>
      </div>

      <!-- Also shown on step 1, where the key was just auto-generated: it is the
           only moment the user learns it exists (backing it up is on them). -->
      <p v-if="(showAll || need('client_id')) && checks.fernet_key" class="hint">
        <span class="ok">✓</span> Encryption key set. Back up <code>{{ envFile }}</code> —
        losing this key makes every stored token permanently unreadable.
      </p>

      <!-- One global save only in showAll; the wizard saves per step. -->
      <div v-if="showAll" class="save-row">
        <button class="btn current" @click="save">Save settings</button>
        <button class="btn" @click="finishSetup">Done</button>
      </div>
      <p v-if="savedNotice" class="hint">{{ savedNotice }}</p>
    </template>
  </section>
</template>

<style scoped>
h3 { margin: 0;margin-bottom: 0.0rem; font-size: 1rem; }
.setup { display: flex; flex-direction: column; gap: 0.6rem; max-width: 46rem; }
/* The global .card margin is sized for the dashboard; here the flex gap does it. */
div.card {padding: 0.6rem 0.8rem; margin-bottom: 0.8rem; border: 1px solid var(--border);}
.card { display: flex; flex-direction: column; gap: 0.6rem; padding: 0.6rem 0.8rem; }
.env-badge {
  margin-right: auto; font-size: 0.7rem; font-family: monospace; color: var(--muted);
  border: 1px solid var(--border); border-radius: 999px; padding: 0.15rem 0.5rem;
  max-width: 22rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.checks { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.3rem; }
.ok { color: var(--series); font-weight: 700; }
.pending { color: var(--muted); }
.step { display: flex; align-items: center; gap: 0.8rem; flex-wrap: wrap; }
label { display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.85rem; color: var(--ink-2); }
label.inline { flex-direction: row; align-items: center; gap: 0.3rem; }
input { font: inherit; padding: 0.35rem 0.5rem; border: 1px solid var(--border); border-radius: 8px; background: transparent; color: var(--ink); }
input[type="radio"] { width: auto; }
.hint { font-size: 0.8rem; color: var(--muted); margin: 0.3rem 0 0.3rem; }
.warn { font-size: 0.8rem; color: #d08770; }
.failure pre { white-space: pre-wrap; font-size: 0.75rem; max-height: 14rem; overflow: auto; }
.ok-box {
  font-size: 0.85rem; border: 1px solid var(--series); border-radius: 8px;
  padding: 0.6rem 0.75rem; margin: 0;
}
.cloud-log {
  white-space: pre-wrap; font-size: 0.72rem; max-height: 16rem; overflow: auto;
  border: 1px solid var(--border); border-radius: 6px; padding: 0.5rem; margin: 0;
}
.save-row { display: flex; align-items: center; gap: 0.8rem; }
.progress { font-size: 0.8rem; color: var(--muted); letter-spacing: 0.02em; }
</style>

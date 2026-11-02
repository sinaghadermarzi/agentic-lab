// Layer 3, the harness SDK: a file-backed session, closed, reopened, resumed.
// Run from Python: shoplab.pi.run_ts("04-session.ts", TASK, bridge=bridge, DESK_SYSTEM=...)

import {
  createAgentSession,
  DefaultResourceLoader,
  ModelRuntime,
  SessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";
import { deskProvider, deskTools, emit, SYSTEM } from "./desk.ts";

const task = process.argv[2] ?? "Triage ticket TKT-2205.";
const cwd = process.cwd();
const home = process.env.PI_CODING_AGENT_DIR ?? `${cwd}/.pi-agent`; // never ~/.pi
const sessionDir = `${home}/sessions`;

/** No discovered extensions, skills, templates, themes or AGENTS.md: only our prompt. */
async function isolatedLoader(systemPrompt: string): Promise<DefaultResourceLoader> {
  const loader = new DefaultResourceLoader({
    cwd, agentDir: home, noExtensions: true, noSkills: true, noPromptTemplates: true,
    noThemes: true, noContextFiles: true,
    systemPromptOverride: () => systemPrompt, appendSystemPromptOverride: () => [],
  });
  await loader.reload();
  return loader;
}

// >>> pi_lab.session
const runtime = await ModelRuntime.create({ authPath: `${home}/auth.json`, modelsPath: null });
runtime.registerProvider("larkspur", deskProvider);            // the bridge, as harness config

async function openSession(sessionManager: SessionManager) {
  const { session } = await createAgentSession({
    cwd, agentDir: home, modelRuntime: runtime, model: runtime.getModel("larkspur", "larkspur-desk"),
    thinkingLevel: "off", noTools: "builtin", customTools: await deskTools(), // desk tools only
    resourceLoader: await isolatedLoader(SYSTEM), sessionManager,
    settingsManager: SettingsManager.inMemory({ compaction: { enabled: false } }),
  });
  return session;
}

const first = await openSession(SessionManager.create(cwd, sessionDir)); // a new JSONL file
await first.prompt(task);
const file = first.sessionFile ?? "";
first.dispose();                                                         // this "process" is gone

const second = await openSession(SessionManager.open(file, sessionDir)); // resume from disk
await second.prompt("Which decision, policy and refund did you settle on? One sentence.");
emit({ type: "session", file, followUp: second.getLastAssistantText() ?? "" });
second.dispose();
// <<< pi_lab.session

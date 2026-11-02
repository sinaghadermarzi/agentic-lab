// Layer 2, pi-agent-core: the desk's ticket through the low-level agentLoop.
// Run from Python: shoplab.pi.run_ts("02-agent-loop.ts", TASK, bridge=bridge, DESK_SYSTEM=...)

import { agentLoop } from "@earendil-works/pi-agent-core";
import type { AgentContext, AgentLoopConfig, AgentMessage } from "@earendil-works/pi-agent-core";
import { deskModel, deskTools, emit, SYSTEM, toLlm } from "./desk.ts";
import { models } from "./models.ts";

const task = process.argv[2] ?? "Triage ticket TKT-2205.";

// >>> pi_lab.agent-loop
const context: AgentContext = {
  messages: [{ role: "system", content: SYSTEM, timestamp: Date.now() }], // ch02's system message
  tools: await deskTools(),                                                 // ch02's tools dict
};
const config: AgentLoopConfig = { model: deskModel, convertToLlm: toLlm };
const prompt: AgentMessage = { role: "user", content: task, timestamp: Date.now() };

const events = agentLoop([prompt], context, config, undefined, models.streamSimple.bind(models));
for await (const event of events) {
  if (event.type !== "message_update") emit(event); // skip the per-token stream
}
// <<< pi_lab.agent-loop

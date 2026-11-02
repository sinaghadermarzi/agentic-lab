// Layer 1, pi-ai: one model call with one tool, printed event by event.
// Run from Python: shoplab.pi.run_ts("01-stream.ts", bridge=bridge)

import { Type } from "@earendil-works/pi-ai";
import type { Context, Tool } from "@earendil-works/pi-ai";
import { deskModel, emit } from "./desk.ts";
import { models } from "./models.ts";

// >>> pi_lab.stream
const getOrder: Tool = {
  name: "get_order",
  description: "Look up an order by id: items, totals, status, dates.",
  parameters: Type.Object({ order_id: Type.String({ description: "e.g. ORD-7301" }) }),
};
const context: Context = {
  systemPrompt: "You are the Larkspur ops desk. Look facts up with tools; never guess.",
  messages: [{ role: "user", content: "What did order ORD-7312 cost?", timestamp: Date.now() }],
  tools: [getOrder],
};

const stream = models.stream(deskModel, context);
for await (const event of stream) {
  emit({ type: event.type }); // start, toolcall_start, toolcall_delta, ..., done | error
}
emit({ type: "message", message: await stream.result() }); // the finished AssistantMessage
// <<< pi_lab.stream

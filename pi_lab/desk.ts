// The Larkspur desk, as pi sees it: one model behind the course's own model
// door, and the desk's toolset fetched from the tool door. Both doors are
// served by shoplab.bridge.DeskBridge, whose URL arrives in DESK_URL.
//
// Shared by 01-04 and the extension. Only type imports from the pi packages,
// so loading it inside the pi CLI pulls in no second copy of pi-ai. Written
// for Node's built-in type stripping: `import type`, and no enums.

import type { Message, Model, TSchema } from "@earendil-works/pi-ai";
import type { AgentMessage, AgentTool, AgentToolResult } from "@earendil-works/pi-agent-core";
import type { ProviderConfig } from "@earendil-works/pi-coding-agent";

export const DESK_URL = process.env.DESK_URL ?? "http://127.0.0.1:8765";
export const SYSTEM = process.env.DESK_SYSTEM ?? "You are the Larkspur Outfitters ops desk.";

/** The agent's messages, minus any app-only kinds, are what the model reads. */
export function toLlm(messages: AgentMessage[]): Message[] {
  return messages.filter((m): m is Message =>
    m.role === "system" || m.role === "user" || m.role === "assistant" || m.role === "toolResult");
}

/** One JSON object per line on stdout: the only channel Python reads. */
export function emit(record: Record<string, unknown>): void {
  process.stdout.write(JSON.stringify(record) + "\n");
}

// >>> pi_lab.desk-model
// A model is data: the wire it speaks (api), who serves it (provider), where
// (baseUrl), and what it costs. This one is the course's own model door.
export const deskModel: Model<"openai-completions"> = {
  id: "larkspur-desk",
  name: "Larkspur desk (shoplab.llm via the bridge)",
  api: "openai-completions",
  provider: "larkspur",
  baseUrl: `${DESK_URL}/v1`,
  reasoning: false,
  input: ["text"],
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, // the Python LEDGER is the meter
  contextWindow: 128000,
  maxTokens: 1000,
  // Plain chat completions: no `store`, no `developer` role, `max_tokens`.
  compat: {
    supportsStore: false,
    supportsDeveloperRole: false,
    supportsReasoningEffort: false,
    maxTokensField: "max_tokens",
    supportsLongCacheRetention: false,
  },
};

// <<< pi_lab.desk-model

// >>> pi_lab.desk-provider
// The same model as harness configuration -- what pi.registerProvider() and
// ModelRuntime.registerProvider() take. One definition serves every layer.
export const deskProvider: ProviderConfig = {
  name: "Larkspur desk bridge",
  baseUrl: deskModel.baseUrl,
  apiKey: "local", // the bridge ignores it; the client requires one
  api: "openai-completions",
  models: [deskModel],
};
// <<< pi_lab.desk-provider

interface DeskTool {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  risky: boolean;
}

/** The desk's toolset as data, exactly as the Python Tool dataclasses define it. */
export async function deskCatalog(): Promise<DeskTool[]> {
  const res = await fetch(`${DESK_URL}/tools`);
  return (await res.json()) as DeskTool[];
}

/** Run one desk tool through the tool door. Always resolves to run_tool's JSON text. */
export async function callDesk(name: string, args: unknown): Promise<string> {
  const res = await fetch(`${DESK_URL}/tools/${name}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(args ?? {}),
  });
  return res.text();
}

// >>> pi_lab.desk-tools
// Each catalog entry becomes an AgentTool whose execute() posts to the tool
// door. Chapter 02's {"error": ...} result keeps its text and gains a typed
// flag, isError: true. A successful `finish` asks pi to stop (terminate);
// pi stops only when every call in that turn's batch asks the same.
export async function deskTools(): Promise<AgentTool<TSchema>[]> {
  return (await deskCatalog()).map((tool) => ({
    name: tool.name,
    label: tool.name,
    description: tool.description,
    parameters: tool.parameters as unknown as TSchema, // plain JSON Schema validates as-is
    execute: async (_toolCallId, args): Promise<AgentToolResult<unknown>> => {
      const text = await callDesk(tool.name, args);
      const value: unknown = JSON.parse(text);
      const failed = value !== null && typeof value === "object" && "error" in value;
      return { content: [{ type: "text", text }], details: value, isError: failed,
               terminate: tool.name === "finish" && !failed };
    },
  }));
}
// <<< pi_lab.desk-tools

/** Names of the risky tools (issue_refund, create_replacement), from the catalog. */
export async function riskyNames(): Promise<Set<string>> {
  return new Set((await deskCatalog()).filter((t) => t.risky).map((t) => t.name));
}

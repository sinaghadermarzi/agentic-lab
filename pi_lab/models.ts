// The pi-ai runtime for layers 1 and 2: a Models collection that knows one
// provider, the desk bridge. (The harness layers get the same model through
// deskProvider instead: the pi CLI and SDK own their own Models runtime.)

import { createModels, createProvider } from "@earendil-works/pi-ai";
import { openAICompletionsApi } from "@earendil-works/pi-ai/api/openai-completions.lazy";
import { deskModel } from "./desk.ts";

// >>> pi_lab.models
// A provider owns auth and the wire implementation (here: the OpenAI
// chat-completions API); a Models collection routes each request to the
// provider that owns the model. The bridge ignores the key, but the
// openai-completions client refuses to send a request without one.
export const models = createModels();
models.setProvider(createProvider({
  id: "larkspur",
  baseUrl: deskModel.baseUrl,
  auth: { apiKey: { name: "desk bridge", resolve: async () => ({ auth: { apiKey: "local" } }) } },
  models: [deskModel],
  api: openAICompletionsApi(),
}));
// <<< pi_lab.models

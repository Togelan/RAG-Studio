import { z } from "zod"

import { ApiClient } from "../../api/client"

export const ProviderSchema = z.enum(["openai", "deepseek", "anthropic", "ollama"])
export type Provider = z.infer<typeof ProviderSchema>

export const ChunkingStrategySchema = z.enum([
  "static",
  "recursive",
  "parent_document",
  "sentence_window",
])
export type ChunkingStrategy = z.infer<typeof ChunkingStrategySchema>

export const ChunkingSettingsSchema = z.object({
  schema_version: z.literal(1),
  strategy: ChunkingStrategySchema,
  chunk_size: z.union([z.literal(128), z.literal(256), z.literal(512), z.literal(1024)]),
  chunk_overlap: z.union([z.literal(0), z.literal(32), z.literal(64), z.literal(128)]),
  parent_size: z.union([
    z.literal(512),
    z.literal(1024),
    z.literal(2048),
    z.literal(4096),
    z.null(),
  ]),
  window_sentences: z.union([z.literal(1), z.literal(2), z.literal(3), z.null()]),
})
export type ChunkingSettings = z.infer<typeof ChunkingSettingsSchema>

const SettingsFieldsSchema = z.object({
  provider: ProviderSchema,
  model: z.string().min(1),
  temperature: z.number().min(0).max(2),
  max_tokens: z.number().int().min(1).max(32_768),
  system_prompt: z.string(),
  top_k: z.number().int().min(1).max(100),
  chunk_size: z.number().int().min(128).max(4096),
  chunk_overlap: z.number().int().min(0).max(512),
  chunking: ChunkingSettingsSchema,
})

export const SettingsResponseSchema = SettingsFieldsSchema.extend({
  api_key: z.union([z.literal("********"), z.null()]),
})
export type SettingsResponse = z.infer<typeof SettingsResponseSchema>
export type SettingsDraft = z.infer<typeof SettingsFieldsSchema>

const SavedSettingsSchema = SettingsFieldsSchema.extend({ chunks_changed: z.boolean() })
export type SavedSettings = z.infer<typeof SavedSettingsSchema>

const ValidateKeyResponseSchema = z.object({
  valid: z.boolean(),
  provider: ProviderSchema,
  error: z.string().nullable().optional(),
})
export type ValidateKeyResponse = z.infer<typeof ValidateKeyResponseSchema>

const ModelsResponseSchema = z.object({
  provider: ProviderSchema,
  models: z.array(z.string().min(1)),
  cached: z.boolean(),
  error: z.string().nullable().optional(),
})
export type ModelsResponse = z.infer<typeof ModelsResponseSchema>

export type SettingsApi = {
  readonly load: (signal?: AbortSignal) => Promise<SettingsResponse>
  readonly models: (provider: Provider, signal?: AbortSignal) => Promise<ModelsResponse>
  readonly save: (
    draft: SettingsDraft,
    apiKey?: string,
    signal?: AbortSignal,
  ) => Promise<SavedSettings>
  readonly validateKey: (
    provider: Provider,
    apiKey: string,
    signal?: AbortSignal,
  ) => Promise<ValidateKeyResponse>
}

export function bindBrowserFetch(
  fetchImplementation: typeof fetch = globalThis.fetch,
): typeof fetch {
  return fetchImplementation.bind(globalThis)
}

function createBrowserApiClient(): ApiClient {
  return new ApiClient(bindBrowserFetch())
}

function signalOptions(signal: AbortSignal | undefined): { readonly signal?: AbortSignal } {
  return signal === undefined ? {} : { signal }
}

export function createSettingsApi(client: ApiClient = createBrowserApiClient()): SettingsApi {
  return {
    load: (signal) =>
      client.get("/api/personal/settings", SettingsResponseSchema, signalOptions(signal)),
    models: (provider, signal) =>
      client.get(
        `/api/personal/settings/models/${encodeURIComponent(provider)}`,
        ModelsResponseSchema,
        signalOptions(signal),
      ),
    save: (draft, apiKey, signal) =>
      client.post(
        "/api/personal/settings",
        apiKey === undefined ? draft : { ...draft, api_key: apiKey },
        SavedSettingsSchema,
        signalOptions(signal),
      ),
    validateKey: (provider, apiKey, signal) =>
      client.post(
        "/api/personal/settings/validate-key",
        { api_key: apiKey, provider },
        ValidateKeyResponseSchema,
        signalOptions(signal),
      ),
  }
}

export const settingsApi = createSettingsApi()

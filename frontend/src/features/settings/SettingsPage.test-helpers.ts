import { vi } from "vitest"

import type { IngestionApi } from "../ingestion/ingestion-api"
import type { SettingsApi } from "./settings-api"

export const SETTINGS_FIXTURE = {
  provider: "deepseek" as const,
  model: "deepseek-chat",
  temperature: 1,
  max_tokens: 2048,
  system_prompt: "Answer from context.",
  top_k: 5,
  chunk_size: 512,
  chunk_overlap: 64,
  chunking: {
    schema_version: 1 as const,
    strategy: "recursive" as const,
    chunk_size: 512 as const,
    chunk_overlap: 64 as const,
    parent_size: 2048 as const,
    window_sentences: 2 as const,
  },
}

export function createSettingsApi(overrides: Partial<SettingsApi> = {}): SettingsApi {
  return {
    clearCredential: vi.fn(() => Promise.resolve({ ...SETTINGS_FIXTURE, api_key: null })),
    load: vi.fn(() => Promise.resolve({ ...SETTINGS_FIXTURE, api_key: "********" as const })),
    models: vi.fn(() =>
      Promise.resolve({ provider: "deepseek" as const, models: ["deepseek-chat"], cached: true }),
    ),
    save: vi.fn(() => Promise.resolve({ ...SETTINGS_FIXTURE, chunks_changed: false })),
    validateKey: vi.fn(() =>
      Promise.resolve({ valid: true, provider: "deepseek" as const, error: null }),
    ),
    ...overrides,
  }
}

export function createIngestionApi(): IngestionApi {
  return {
    chunks: vi.fn(() => Promise.resolve({ chunks: [], next_cursor: null, truncated: false })),
    clear: vi.fn(() => Promise.resolve({ status: "ok" as const, message: "ok", deleted_count: 0 })),
    deleteDocument: vi.fn(() =>
      Promise.resolve({ status: "ok" as const, message: "ok", deleted_count: 0 }),
    ),
    documents: vi.fn(() =>
      Promise.resolve({ documents: [], total: 0, next_cursor: null, truncated: false }),
    ),
    progress: vi.fn(() =>
      Promise.resolve({ file_id: "job", status: "done" as const, message: "done" }),
    ),
    reingest: vi.fn(() =>
      Promise.resolve({ status: "skipped" as const, file_id: "doc", message: "skip" }),
    ),
    upload: vi.fn(() =>
      Promise.resolve({
        kind: "accepted" as const,
        response: { status: "unchanged" as const, file_id: "", message: "same" },
      }),
    ),
  }
}

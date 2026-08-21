import { describe, expect, it, vi } from "vitest"

import { ApiClient, type KyHttpClient, type KyRequestOptions } from "../api/client"
import { ApiError } from "../api/errors"
import { createChatGateway } from "../features/chat/chat-api"
import { createIngestionApi } from "../features/ingestion/ingestion-api"
import { createSettingsApi, type SettingsDraft } from "../features/settings/settings-api"

type RequestRecord = {
  readonly body: unknown
  readonly method: "delete" | "get" | "patch" | "post"
  readonly path: string
}

const settingsDraft: SettingsDraft = {
  chunk_overlap: 64,
  chunk_size: 512,
  chunking: {
    chunk_overlap: 64,
    chunk_size: 512,
    parent_size: 2048,
    schema_version: 1,
    strategy: "recursive",
    window_sentences: 2,
  },
  max_tokens: 2048,
  model: "gpt-4o-mini",
  provider: "openai",
  system_prompt: "Use supplied context.",
  temperature: 1,
  top_k: 5,
}

function jsonResponse(value: unknown, status: number = 200): Response {
  return new Response(JSON.stringify(value), {
    headers: { "Content-Type": "application/json" },
    status,
  })
}

function responseFor(path: string, method: RequestRecord["method"]): Response {
  if (path === "/api/settings") {
    return jsonResponse(
      method === "post"
        ? { ...settingsDraft, chunks_changed: false }
        : { ...settingsDraft, api_key: "********" },
    )
  }
  if (path.startsWith("/api/settings/models/")) {
    return jsonResponse({ cached: false, models: ["gpt-4o-mini"], provider: "openai" })
  }
  if (path === "/api/settings/validate-key")
    return jsonResponse({ provider: "openai", valid: true })
  if (path === "/api/chat/sessions") {
    return method === "post"
      ? jsonResponse({ created_at: "2026-08-15", id: "s1", title: "New" })
      : jsonResponse([])
  }
  if (path.includes("/messages")) {
    return method === "post"
      ? jsonResponse({ content: "Question", created_at: "2026-08-15", id: "m1", role: "user" })
      : method === "delete"
        ? jsonResponse({ session_id: "s1", status: "cleared" })
        : jsonResponse([])
  }
  if (path === "/api/chat/feedback") return jsonResponse({ feedback: "positive", status: "saved" })
  if (path.startsWith("/api/chat/sessions/")) {
    return method === "patch"
      ? jsonResponse({ created_at: "2026-08-15", id: "s1", title: "Renamed" })
      : jsonResponse({ session_id: "s1", status: method === "delete" ? "deleted" : "stopped" })
  }
  if (path.includes("/chunks"))
    return jsonResponse({ chunks: [], next_cursor: null, truncated: false })
  if (path.startsWith("/api/ingest/documents")) {
    if (method === "delete") {
      return jsonResponse({ deleted_count: 0, message: "safe", status: "ok" })
    }
    return jsonResponse({ documents: [], next_cursor: null, total: 0, truncated: false })
  }
  if (path === "/api/ingest/clear")
    return jsonResponse({ deleted_count: 0, message: "safe", status: "ok" })
  if (path.startsWith("/api/ingest/progress/")) {
    return jsonResponse({ file_id: "job-1", message: "done", status: "done" })
  }
  if (path === "/api/ingest/reingest")
    return jsonResponse({ file_id: "job-1", message: "safe", status: "skipped" })
  return jsonResponse({ deleted_count: 0, message: "safe", status: "ok" })
}

function recordingClient(records: RequestRecord[]): ApiClient {
  const request =
    (method: RequestRecord["method"]) =>
    (path: string, options: KyRequestOptions): Promise<Response> => {
      records.push({ body: options.json, method, path })
      return Promise.resolve(responseFor(path, method))
    }
  const http: KyHttpClient = {
    delete: request("delete"),
    get: request("get"),
    patch: request("patch"),
    post: request("post"),
  }
  return new ApiClient(fetch, http, () => "csrf-proof")
}

describe("Stage 2 frontend endpoint contract", () => {
  it("keeps Settings, Chat, and ingestion requests on exact relative methods, bodies, and paths", async () => {
    const records: RequestRecord[] = []
    const client = recordingClient(records)
    const settings = createSettingsApi(client)
    const chat = createChatGateway(client)
    const upload = vi.fn(() =>
      Promise.resolve(jsonResponse({ file_id: "job-1", message: "queued", status: "processing" })),
    )
    const ingestion = createIngestionApi(client, upload)

    await settings.load()
    await settings.models("openai")
    await settings.validateKey("openai", "secret-value")
    await settings.save(settingsDraft)
    await chat.createSession("New")
    await chat.renameSession("s1", "Renamed")
    await chat.listSessions()
    await chat.listMessages("s1")
    await chat.commitMessage("s1", { content: "Question", message_id: "m1" })
    await chat.feedback({ feedback: "positive", message_id: "m1", session_id: "s1" })
    await chat.cancel("s1")
    await chat.clearMessages("s1")
    await chat.deleteSession("s1")
    await ingestion.documents("cursor 1")
    await ingestion.chunks("doc/1", "next")
    await ingestion.deleteDocument("doc/1")
    await ingestion.clear()
    await ingestion.progress("job/1")
    await ingestion.reingest({ doc_id: "doc/1", filename: "safe.txt" })
    await ingestion.upload(new File(["safe"], "safe.txt", { type: "text/plain" }), "replace")

    expect(records).toEqual([
      { body: undefined, method: "get", path: "/api/settings" },
      { body: undefined, method: "get", path: "/api/settings/models/openai" },
      {
        body: { api_key: "secret-value", provider: "openai" },
        method: "post",
        path: "/api/settings/validate-key",
      },
      { body: settingsDraft, method: "post", path: "/api/settings" },
      { body: { title: "New" }, method: "post", path: "/api/chat/sessions" },
      { body: { title: "Renamed" }, method: "patch", path: "/api/chat/sessions/s1" },
      { body: undefined, method: "get", path: "/api/chat/sessions" },
      { body: undefined, method: "get", path: "/api/chat/sessions/s1/messages" },
      {
        body: { content: "Question", message_id: "m1" },
        method: "post",
        path: "/api/chat/sessions/s1/messages",
      },
      {
        body: { feedback: "positive", message_id: "m1", session_id: "s1" },
        method: "post",
        path: "/api/chat/feedback",
      },
      { body: {}, method: "post", path: "/api/chat/sessions/s1/cancel" },
      { body: undefined, method: "delete", path: "/api/chat/sessions/s1/messages" },
      { body: undefined, method: "delete", path: "/api/chat/sessions/s1" },
      { body: undefined, method: "get", path: "/api/ingest/documents?cursor=cursor%201" },
      { body: undefined, method: "get", path: "/api/ingest/documents/doc%2F1/chunks?cursor=next" },
      { body: undefined, method: "delete", path: "/api/ingest/documents/doc%2F1" },
      { body: undefined, method: "delete", path: "/api/ingest/clear" },
      { body: undefined, method: "get", path: "/api/ingest/progress/job%2F1" },
      {
        body: { doc_id: "doc/1", filename: "safe.txt" },
        method: "post",
        path: "/api/ingest/reingest",
      },
    ])
    expect(upload).toHaveBeenCalledWith(
      "/api/ingest/upload?action=replace",
      expect.any(FormData),
      undefined,
    )
  })

  it.each([400, 422, 429, 503])(
    "redacts exact status %s without exposing response content",
    async (status) => {
      const http: KyHttpClient = {
        delete: vi.fn(),
        get: vi.fn(() =>
          Promise.resolve(new Response("provider /private/path secret", { status })),
        ),
        patch: vi.fn(),
        post: vi.fn(),
      }
      const error = await createSettingsApi(new ApiClient(fetch, http))
        .load()
        .catch((caught: unknown) => caught)

      expect(error).toBeInstanceOf(ApiError)
      if (!(error instanceof ApiError)) {
        throw new Error("expected the typed API error")
      }
      expect(error.message).not.toContain("provider")
      expect(http.get).toHaveBeenCalledWith("/api/settings", {})
    },
  )
})

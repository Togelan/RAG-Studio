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
  if (path === "/api/personal/settings") {
    return jsonResponse(
      method === "post"
        ? { ...settingsDraft, chunks_changed: false }
        : { ...settingsDraft, api_key: "********" },
    )
  }
  if (path.startsWith("/api/personal/settings/models/")) {
    return jsonResponse({ cached: false, models: ["gpt-4o-mini"], provider: "openai" })
  }
  if (path === "/api/personal/settings/validate-key")
    return jsonResponse({ provider: "openai", valid: true })
  if (path === "/api/personal/chat/sessions") {
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
  if (path === "/api/personal/chat/feedback")
    return jsonResponse({ feedback: "like", id: "feedback-1", status: "saved" })
  if (path.startsWith("/api/personal/chat/sessions/")) {
    return method === "patch"
      ? jsonResponse({ created_at: "2026-08-15", id: "s1", title: "Renamed" })
      : jsonResponse({ session_id: "s1", status: method === "delete" ? "deleted" : "stopped" })
  }
  if (path.includes("/chunks"))
    return jsonResponse({ chunks: [], next_cursor: null, truncated: false })
  if (path.endsWith("/reindex"))
    return jsonResponse({ file_id: "job-1", message: "safe", status: "skipped" })
  if (path.startsWith("/api/personal/knowledge/documents")) {
    if (method === "delete") {
      return jsonResponse({ deleted: 0 })
    }
    return jsonResponse({ documents: [], next_cursor: null, truncated: false })
  }
  if (path === "/api/personal/knowledge/clear") return jsonResponse({ deleted: 0 })
  if (path.startsWith("/api/personal/knowledge/progress/")) {
    return jsonResponse({ file_id: "job-1", message: "done", status: "done" })
  }
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
      { body: undefined, method: "get", path: "/api/personal/settings" },
      { body: undefined, method: "get", path: "/api/personal/settings/models/openai" },
      {
        body: { api_key: "secret-value", provider: "openai" },
        method: "post",
        path: "/api/personal/settings/validate-key",
      },
      { body: settingsDraft, method: "post", path: "/api/personal/settings" },
      { body: { title: "New" }, method: "post", path: "/api/personal/chat/sessions" },
      {
        body: { title: "Renamed" },
        method: "patch",
        path: "/api/personal/chat/sessions/s1",
      },
      { body: undefined, method: "get", path: "/api/personal/chat/sessions" },
      { body: undefined, method: "get", path: "/api/personal/chat/sessions/s1/messages" },
      {
        body: { content: "Question", message_id: "m1" },
        method: "post",
        path: "/api/personal/chat/sessions/s1/messages",
      },
      {
        body: { feedback: "like", message_id: "m1", session_id: "s1" },
        method: "post",
        path: "/api/personal/chat/feedback",
      },
      { body: {}, method: "post", path: "/api/personal/chat/sessions/s1/cancel" },
      {
        body: undefined,
        method: "delete",
        path: "/api/personal/chat/sessions/s1/messages",
      },
      { body: undefined, method: "delete", path: "/api/personal/chat/sessions/s1" },
      {
        body: undefined,
        method: "get",
        path: "/api/personal/knowledge/documents?cursor=cursor%201",
      },
      {
        body: undefined,
        method: "get",
        path: "/api/personal/knowledge/documents/doc%2F1/chunks?cursor=next",
      },
      {
        body: undefined,
        method: "delete",
        path: "/api/personal/knowledge/documents/doc%2F1",
      },
      { body: undefined, method: "delete", path: "/api/personal/knowledge/clear" },
      { body: undefined, method: "get", path: "/api/personal/knowledge/progress/job%2F1" },
      {
        body: {},
        method: "post",
        path: "/api/personal/knowledge/documents/doc%2F1/reindex",
      },
    ])
    expect(upload).toHaveBeenCalledWith(
      "/api/personal/knowledge/upload?action=replace",
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
      expect(http.get).toHaveBeenCalledWith("/api/personal/settings", {})
    },
  )
})

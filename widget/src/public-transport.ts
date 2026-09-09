import { z } from "zod"

const PROOF_TIMEOUT_MS = 10_000
const STREAM_TIMEOUT_MS = 60_000

const ProofSchema = z.object({
  expires_at: z.iso.datetime(),
  proof: z.string().min(1).max(2048),
  session_id: z.uuid(),
})

const CitationSchema = z.object({
  filename: z.string().min(1).max(512),
  page: z.number().int().positive().nullable().optional(),
})

const StartSchema = z.object({ protocol: z.literal("1") })
const TokenSchema = z.object({ token: z.string() })
const CitationsSchema = z.object({ citations: z.array(CitationSchema).max(20) })
const DoneSchema = z.object({ done: z.literal(true) })
const ErrorSchema = z.object({
  code: z.string(),
  message: z.string(),
  retryable: z.boolean(),
})

export type PublicProof = z.infer<typeof ProofSchema>
export type PublicCitation = z.infer<typeof CitationSchema>

export type PublicStreamEvent =
  | { readonly type: "start" }
  | { readonly token: string; readonly type: "token" }
  | { readonly citations: readonly PublicCitation[]; readonly type: "citations" }
  | { readonly type: "done" }

type StreamPhase = "awaiting_start" | "streaming" | "cited" | "done"

export class PublicTransportError extends Error {
  constructor(
    readonly kind: "http" | "offline" | "protocol" | "stream",
    readonly status: number | null = null,
    readonly retryAfterSeconds: number | null = null,
  ) {
    super("Public widget request failed")
    this.name = "PublicTransportError"
  }
}

function endpoint(baseUrl: string, publicKey: string, suffix: string): string {
  const base = baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`
  return new URL(`api/public/widgets/${encodeURIComponent(publicKey)}/${suffix}`, base).toString()
}

function retryAfter(response: Response): number | null {
  const raw = response.headers.get("Retry-After")
  if (raw === null) return null
  const parsed = Number.parseInt(raw, 10)
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null
}

function httpError(response: Response): PublicTransportError {
  return new PublicTransportError("http", response.status, retryAfter(response))
}

async function request(
  url: string,
  body: Readonly<Record<string, string>>,
  timeout: number,
): Promise<Response> {
  try {
    const response = await globalThis.fetch(url, {
      body: JSON.stringify(body),
      credentials: "omit",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      method: "POST",
      signal: AbortSignal.timeout(timeout),
    })
    if (!response.ok) throw httpError(response)
    return response
  } catch (error) {
    if (error instanceof PublicTransportError) throw error
    if (error instanceof TypeError || error instanceof DOMException) {
      throw new PublicTransportError("offline")
    }
    throw error
  }
}

export async function bootstrapPublicWidget(
  baseUrl: string,
  publicKey: string,
): Promise<PublicProof> {
  const response = await request(endpoint(baseUrl, publicKey, "proof"), {}, PROOF_TIMEOUT_MS)
  const parsed = ProofSchema.safeParse(await response.json())
  if (!parsed.success) throw new PublicTransportError("protocol")
  return parsed.data
}

function parseFrame(frame: string): PublicStreamEvent | null {
  let eventName = ""
  const dataLines: string[] = []
  for (const line of frame.split(/\r?\n/u)) {
    if (line.startsWith("event:")) eventName = line.slice(6).trim()
    if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart())
  }
  if (eventName.length === 0 || dataLines.length === 0) return null

  let payload: unknown
  try {
    payload = JSON.parse(dataLines.join("\n"))
  } catch (error) {
    if (error instanceof SyntaxError) throw new PublicTransportError("protocol")
    throw error
  }
  switch (eventName) {
    case "start": {
      if (!StartSchema.safeParse(payload).success) throw new PublicTransportError("protocol")
      return { type: "start" }
    }
    case "token": {
      const parsed = TokenSchema.safeParse(payload)
      if (!parsed.success) throw new PublicTransportError("protocol")
      return { token: parsed.data.token, type: "token" }
    }
    case "citations": {
      const parsed = CitationsSchema.safeParse(payload)
      if (!parsed.success) throw new PublicTransportError("protocol")
      return { citations: parsed.data.citations, type: "citations" }
    }
    case "done": {
      if (!DoneSchema.safeParse(payload).success) throw new PublicTransportError("protocol")
      return { type: "done" }
    }
    case "error": {
      if (!ErrorSchema.safeParse(payload).success) throw new PublicTransportError("protocol")
      throw new PublicTransportError("stream")
    }
    default:
      throw new PublicTransportError("protocol")
  }
}

function nextPhase(phase: StreamPhase, event: PublicStreamEvent): StreamPhase {
  switch (phase) {
    case "awaiting_start":
      if (event.type === "start") return "streaming"
      break
    case "streaming":
      if (event.type === "token") return "streaming"
      if (event.type === "citations") return "cited"
      break
    case "cited":
      if (event.type === "done") return "done"
      break
    case "done":
      break
    default:
      phase satisfies never
  }
  throw new PublicTransportError("protocol")
}

export async function streamPublicWidget(
  baseUrl: string,
  publicKey: string,
  proof: PublicProof,
  message: string,
  onEvent: (event: PublicStreamEvent) => void,
): Promise<void> {
  const response = await request(
    endpoint(baseUrl, publicKey, "streams"),
    { message, proof: proof.proof },
    STREAM_TIMEOUT_MS,
  )
  if (response.body === null) throw new PublicTransportError("protocol")
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  let phase: StreamPhase = "awaiting_start"
  try {
    while (true) {
      const read = await reader.read()
      buffer += decoder.decode(read.value, { stream: !read.done })
      let boundary = buffer.search(/\r?\n\r?\n/u)
      while (boundary >= 0) {
        const event = parseFrame(buffer.slice(0, boundary))
        const separator = buffer.startsWith("\r\n\r\n", boundary) ? 4 : 2
        buffer = buffer.slice(boundary + separator)
        if (event !== null) {
          phase = nextPhase(phase, event)
          onEvent(event)
        }
        boundary = buffer.search(/\r?\n\r?\n/u)
      }
      if (read.done) break
    }
  } finally {
    reader.releaseLock()
  }
  if (phase !== "done") throw new PublicTransportError("protocol")
}

export async function cancelPublicWidget(
  baseUrl: string,
  publicKey: string,
  proof: PublicProof,
): Promise<void> {
  await request(
    endpoint(baseUrl, publicKey, `streams/${proof.session_id}/cancel`),
    { proof: proof.proof },
    PROOF_TIMEOUT_MS,
  )
}

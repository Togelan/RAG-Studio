import ky, { HTTPError } from "ky"
import type { z } from "zod"

import { browserCsrfToken, csrfHeadersForMutation, requiresCsrfProof } from "./csrf"
import { ApiContractError, apiErrorFromResponse } from "./errors"

export type JsonRequestOptions = {
  readonly headers?: Readonly<Record<string, string>>
  readonly signal?: AbortSignal
}

export type DeleteRequestOptions = JsonRequestOptions & {
  readonly body?: unknown
}

export type KyRequestOptions = {
  readonly body?: FormData
  readonly headers?: Readonly<Record<string, string>>
  readonly json?: unknown
  readonly retry?: number
  readonly signal?: AbortSignal
  readonly throwHttpErrors?: boolean
}

export type KyHttpClient = {
  readonly delete: (input: string, options: KyRequestOptions) => Promise<Response>
  readonly get: (input: string, options: KyRequestOptions) => Promise<Response>
  readonly patch: (input: string, options: KyRequestOptions) => Promise<Response>
  readonly post: (input: string, options: KyRequestOptions) => Promise<Response>
  readonly put?: (input: string, options: KyRequestOptions) => Promise<Response>
}

async function parseJsonResponse<T>(response: Response, schema: z.ZodType<T>): Promise<T> {
  const text = await response.text()
  if (response.status === 204 || text.trim() === "") {
    const parsed = schema.safeParse(undefined)
    if (!parsed.success) {
      throw new ApiContractError()
    }
    return parsed.data
  }
  let raw: unknown

  try {
    raw = JSON.parse(text)
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw new ApiContractError()
    }
    throw error
  }

  const parsed = schema.safeParse(raw)
  if (!parsed.success) {
    throw new ApiContractError()
  }

  return parsed.data
}

async function mapHttpError(error: unknown): Promise<never> {
  if (error instanceof HTTPError) {
    throw apiErrorFromResponse(error.response)
  }
  throw error
}

function signalOption(signal: AbortSignal | undefined): { readonly signal?: AbortSignal } {
  return signal === undefined ? {} : { signal }
}

function validateApiPath(path: string): void {
  if (!path.startsWith("/api/") || path.startsWith("//") || path.includes("://")) {
    throw new ApiContractError()
  }
}

function createKyHttpClient(fetchImplementation: typeof fetch): KyHttpClient {
  return ky.create({
    credentials: "same-origin",
    fetch: fetchImplementation,
    retry: 0,
  })
}

export class ApiClient {
  readonly #http: KyHttpClient
  readonly #csrfToken: () => string | null

  constructor(
    fetchImplementation: typeof fetch = globalThis.fetch.bind(globalThis),
    http: KyHttpClient = createKyHttpClient(fetchImplementation),
    csrfToken: () => string | null = browserCsrfToken,
  ) {
    this.#http = http
    this.#csrfToken = csrfToken
  }

  async #unsafeOptions(
    path: string,
    body: unknown,
    headers: Readonly<Record<string, string>> | undefined,
    signal: AbortSignal | undefined,
  ): Promise<KyRequestOptions> {
    const payload = body instanceof FormData ? { body } : { json: body }
    if (!requiresCsrfProof(path)) {
      return {
        ...(headers === undefined ? {} : { headers }),
        ...payload,
        retry: 0,
        ...signalOption(signal),
        throwHttpErrors: false,
      }
    }

    return {
      headers: {
        ...headers,
        ...(await csrfHeadersForMutation(path, {
          establish: () => this.#http.get("/api/saas/auth/csrf", signalOption(signal)),
          readToken: this.#csrfToken,
        })),
      },
      ...payload,
      retry: 0,
      ...signalOption(signal),
      throwHttpErrors: false,
    }
  }

  async #retryAfterStaleCsrf(
    response: Response,
    path: string,
    body: unknown,
    options: JsonRequestOptions,
    send: (requestOptions: KyRequestOptions) => Promise<Response>,
  ): Promise<Response> {
    if (response.status !== 403 || !requiresCsrfProof(path)) return response
    const established = await this.#http.get("/api/saas/auth/csrf", signalOption(options.signal))
    if (!established.ok) throw apiErrorFromResponse(established)
    return send(await this.#unsafeOptions(path, body, options.headers, options.signal))
  }

  async get<T>(path: string, schema: z.ZodType<T>, options: JsonRequestOptions = {}): Promise<T> {
    try {
      validateApiPath(path)
      const response = await this.#http.get(path, signalOption(options.signal))
      if (!response.ok) {
        throw apiErrorFromResponse(response)
      }
      return await parseJsonResponse(response, schema)
    } catch (error) {
      return mapHttpError(error)
    }
  }

  async post<T>(
    path: string,
    body: unknown,
    schema: z.ZodType<T>,
    options: JsonRequestOptions = {},
  ): Promise<T> {
    try {
      validateApiPath(path)
      let response = await this.#http.post(
        path,
        await this.#unsafeOptions(path, body, options.headers, options.signal),
      )
      response = await this.#retryAfterStaleCsrf(response, path, body, options, (retryOptions) =>
        this.#http.post(path, retryOptions),
      )
      if (!response.ok) {
        throw apiErrorFromResponse(response)
      }
      return await parseJsonResponse(response, schema)
    } catch (error) {
      return mapHttpError(error)
    }
  }

  async postForm<T>(
    path: string,
    body: FormData,
    schema: z.ZodType<T>,
    options: JsonRequestOptions = {},
  ): Promise<T> {
    try {
      validateApiPath(path)
      let response = await this.#http.post(
        path,
        await this.#unsafeOptions(path, body, options.headers, options.signal),
      )
      response = await this.#retryAfterStaleCsrf(response, path, body, options, (retryOptions) =>
        this.#http.post(path, retryOptions),
      )
      if (!response.ok) {
        throw apiErrorFromResponse(response)
      }
      return await parseJsonResponse(response, schema)
    } catch (error) {
      return mapHttpError(error)
    }
  }

  async postFormResponse(
    path: string,
    body: FormData,
    options: JsonRequestOptions = {},
  ): Promise<Response> {
    try {
      validateApiPath(path)
      const requestOptions = await this.#unsafeOptions(path, body, options.headers, options.signal)
      const response = await this.#http.post(path, { ...requestOptions, throwHttpErrors: false })
      return await this.#retryAfterStaleCsrf(response, path, body, options, (retryOptions) =>
        this.#http.post(path, { ...retryOptions, throwHttpErrors: false }),
      )
    } catch (error) {
      if (error instanceof HTTPError) {
        throw apiErrorFromResponse(error.response)
      }
      throw error
    }
  }

  async patch<T>(
    path: string,
    body: unknown,
    schema: z.ZodType<T>,
    options: JsonRequestOptions = {},
  ): Promise<T> {
    try {
      validateApiPath(path)
      let response = await this.#http.patch(
        path,
        await this.#unsafeOptions(path, body, options.headers, options.signal),
      )
      response = await this.#retryAfterStaleCsrf(response, path, body, options, (retryOptions) =>
        this.#http.patch(path, retryOptions),
      )
      if (!response.ok) {
        throw apiErrorFromResponse(response)
      }
      return await parseJsonResponse(response, schema)
    } catch (error) {
      return mapHttpError(error)
    }
  }

  async delete<T>(
    path: string,
    schema: z.ZodType<T>,
    options: DeleteRequestOptions = {},
  ): Promise<T> {
    try {
      validateApiPath(path)
      let response = await this.#http.delete(
        path,
        await this.#unsafeOptions(path, options.body, options.headers, options.signal),
      )
      response = await this.#retryAfterStaleCsrf(
        response,
        path,
        options.body,
        options,
        (retryOptions) => this.#http.delete(path, retryOptions),
      )
      if (!response.ok) {
        throw apiErrorFromResponse(response)
      }
      return await parseJsonResponse(response, schema)
    } catch (error) {
      return mapHttpError(error)
    }
  }

  async put<T>(
    path: string,
    body: unknown,
    schema: z.ZodType<T>,
    options: JsonRequestOptions = {},
  ): Promise<T> {
    try {
      validateApiPath(path)
      const put = this.#http.put
      if (put === undefined) {
        throw new ApiContractError()
      }
      const response = await put(
        path,
        await this.#unsafeOptions(path, body, options.headers, options.signal),
      )
      if (!response.ok) {
        throw apiErrorFromResponse(response)
      }
      return await parseJsonResponse(response, schema)
    } catch (error) {
      return mapHttpError(error)
    }
  }
}

export const apiClient = new ApiClient()

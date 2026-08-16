import ky, { HTTPError } from "ky"
import type { z } from "zod"

import { ApiContractError, apiErrorFromResponse } from "./errors"

export type JsonRequestOptions = {
  readonly signal?: AbortSignal
}

export type KyRequestOptions = {
  readonly json?: unknown
  readonly retry?: number
  readonly signal?: AbortSignal
}

export type KyHttpClient = {
  readonly delete: (input: string, options: KyRequestOptions) => Promise<Response>
  readonly get: (input: string, options: KyRequestOptions) => Promise<Response>
  readonly patch: (input: string, options: KyRequestOptions) => Promise<Response>
  readonly post: (input: string, options: KyRequestOptions) => Promise<Response>
}

async function parseJsonResponse<T>(response: Response, schema: z.ZodType<T>): Promise<T> {
  const text = await response.text()
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

  constructor(
    fetchImplementation: typeof fetch = fetch,
    http: KyHttpClient = createKyHttpClient(fetchImplementation),
  ) {
    this.#http = http
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
      const response = await this.#http.post(path, {
        json: body,
        retry: 0,
        ...signalOption(options.signal),
      })
      if (!response.ok) {
        throw apiErrorFromResponse(response)
      }
      return await parseJsonResponse(response, schema)
    } catch (error) {
      return mapHttpError(error)
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
      const response = await this.#http.patch(path, {
        json: body,
        retry: 0,
        ...signalOption(options.signal),
      })
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
    options: JsonRequestOptions = {},
  ): Promise<T> {
    try {
      validateApiPath(path)
      const response = await this.#http.delete(path, {
        retry: 0,
        ...signalOption(options.signal),
      })
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

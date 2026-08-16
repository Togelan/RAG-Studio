const GENERIC_API_MESSAGE = "The request could not be completed. Please try again."
const UNAVAILABLE_MESSAGE = "The service is temporarily unavailable. Please try again."
const RATE_LIMITED_MESSAGE = "Too many requests are in progress. Please try again shortly."
const STREAM_MESSAGE = "The response stream is unavailable. Please try again."

export class ApiError extends Error {
  readonly name = "ApiError"

  constructor(
    readonly status: number,
    readonly messageForUser: string,
    readonly retryAfterSeconds: number | null,
  ) {
    super(messageForUser)
  }
}

export class ApiContractError extends Error {
  readonly name = "ApiContractError"

  constructor() {
    super(GENERIC_API_MESSAGE)
  }
}

export class StreamProtocolError extends Error {
  readonly name = "StreamProtocolError"

  constructor() {
    super(STREAM_MESSAGE)
  }
}

export class StreamCancelledError extends Error {
  readonly name = "StreamCancelledError"

  constructor() {
    super("The response stream was cancelled.")
  }
}

function retryAfterSeconds(value: string | null): number | null {
  if (value === null) {
    return null
  }

  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null
}

export function apiErrorFromResponse(response: Response): ApiError {
  if (response.status === 429) {
    return new ApiError(
      response.status,
      RATE_LIMITED_MESSAGE,
      retryAfterSeconds(response.headers.get("Retry-After")),
    )
  }

  if (response.status >= 500) {
    return new ApiError(
      response.status,
      UNAVAILABLE_MESSAGE,
      retryAfterSeconds(response.headers.get("Retry-After")),
    )
  }

  return new ApiError(
    response.status,
    GENERIC_API_MESSAGE,
    retryAfterSeconds(response.headers.get("Retry-After")),
  )
}

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError"
}

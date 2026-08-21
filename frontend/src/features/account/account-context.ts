import { ApiContractError, ApiError, isAbortError } from "../../api/errors"
import type { AuthGateway, AuthSession, Credentials, SignupOutcome } from "../auth/auth-gateway"
import type { AccountId, WorkspaceId } from "./account-contracts"

export type AccountContextState =
  | { readonly kind: "idle" }
  | { readonly kind: "loading" }
  | { readonly kind: "selection-pending" }
  | { readonly kind: "ready"; readonly session: AuthSession }
  | { readonly kind: "confirmation-required" }
  | { readonly kind: "unauthenticated" }
  | { readonly kind: "forbidden" }
  | { readonly kind: "error"; readonly message: string }

type ContextListener = (state: AccountContextState) => void

export class AccountContextController {
  readonly #gateway: AuthGateway
  readonly #listeners = new Set<ContextListener>()
  #request: AbortController | null = null
  #revision = 0
  #state: AccountContextState

  constructor(gateway: AuthGateway, initialSession?: AuthSession) {
    this.#gateway = gateway
    this.#state =
      initialSession === undefined ? { kind: "idle" } : { kind: "ready", session: initialSession }
  }

  get state(): AccountContextState {
    return this.#state
  }

  subscribe(listener: ContextListener): () => void {
    this.#listeners.add(listener)
    return () => this.#listeners.delete(listener)
  }

  dispose(): void {
    this.#request?.abort()
    this.#request = null
    this.#listeners.clear()
  }

  async recover(): Promise<void> {
    await this.#run("loading", (signal) => this.#gateway.recover({ signal }))
  }

  async refresh(): Promise<void> {
    await this.#run("loading", (signal) => this.#gateway.refresh({ signal }))
  }

  async signIn(credentials: Credentials): Promise<void> {
    const request = this.#begin("loading")
    try {
      const session = await this.#gateway.signIn(credentials, { signal: request.signal })
      if (request.revision !== this.#revision) return
      this.#request = null
      this.#set({ kind: "ready", session })
    } catch (error) {
      if (error instanceof Error) {
        if (request.revision !== this.#revision || isAbortError(error)) return
        this.#request = null
        if (isApiDenial(error, 401)) {
          this.#set({
            kind: "error",
            message: "The request could not be completed. Please try again.",
          })
          return
        }
        this.#handle(error, request.revision)
        return
      }
      throw error
    }
  }

  async signUp(credentials: Credentials): Promise<SignupOutcome | null> {
    const request = this.#begin("loading")
    try {
      const outcome = await this.#gateway.signUp(credentials, { signal: request.signal })
      if (request.revision !== this.#revision) return null
      this.#request = null
      if (outcome.confirmation_required) this.#set({ kind: "confirmation-required" })
      else await this.recover()
      return outcome
    } catch (error) {
      if (error instanceof Error) {
        this.#handle(error, request.revision)
        return null
      }
      throw error
    }
  }

  async select(accountId: AccountId, workspaceId: WorkspaceId | null): Promise<void> {
    await this.#run("selection-pending", (signal) =>
      this.#gateway.selectContext(accountId, workspaceId, { signal }),
    )
  }

  async signOut(): Promise<void> {
    const request = this.#begin("loading")
    try {
      await this.#gateway.signOut({ signal: request.signal })
      if (request.revision !== this.#revision) return
      this.#request = null
      this.#set({ kind: "unauthenticated" })
    } catch (error) {
      if (error instanceof Error) {
        this.#handle(error, request.revision)
        return
      }
      throw error
    }
  }

  async #run(
    pending: "loading" | "selection-pending",
    operation: (signal: AbortSignal) => Promise<AuthSession>,
  ): Promise<void> {
    const request = this.#begin(pending)
    try {
      const session = await operation(request.signal)
      if (request.revision !== this.#revision) return
      this.#request = null
      this.#set({ kind: "ready", session })
    } catch (error) {
      if (error instanceof Error) {
        this.#handle(error, request.revision)
        return
      }
      throw error
    }
  }

  #begin(pending: "loading" | "selection-pending"): {
    readonly revision: number
    readonly signal: AbortSignal
  } {
    this.#request?.abort()
    this.#revision += 1
    this.#request = new AbortController()
    this.#set({ kind: pending })
    return { revision: this.#revision, signal: this.#request.signal }
  }

  #handle(error: Error, revision: number): void {
    if (revision !== this.#revision || isAbortError(error)) return
    this.#request = null
    if (isApiDenial(error, 401)) {
      this.#set({ kind: "unauthenticated" })
      return
    }
    if (isApiDenial(error, 403)) {
      this.#set({ kind: "forbidden" })
      return
    }
    if (error instanceof ApiError || error instanceof ApiContractError) {
      this.#set({ kind: "error", message: error.message })
      return
    }
    this.#set({
      kind: "error",
      message: "The request could not be completed. Please try again.",
    })
  }

  #set(state: AccountContextState): void {
    this.#state = state
    for (const listener of this.#listeners) listener(state)
  }
}

function isApiDenial(error: Error, status: 401 | 403): error is ApiError {
  return error instanceof ApiError && error.status === status
}

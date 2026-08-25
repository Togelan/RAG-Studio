import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { AuthPage } from "./AuthPage"

describe("unified RAG-Studio authentication page", () => {
  it("submits credentials only through the callback without URL or storage persistence", async () => {
    // Given: the canonical sign-in form and empty browser credential stores.
    const user = userEvent.setup()
    const authenticate = vi.fn(() => Promise.resolve())
    const initialUrl = window.location.href
    localStorage.clear()
    sessionStorage.clear()
    render(
      <AuthPage
        locale="en"
        mode="sign-in"
        onAuthenticate={authenticate}
        onModeChange={vi.fn()}
        status={{ kind: "ready" }}
      />,
    )

    // When: a user enters credentials and submits the form.
    await user.type(screen.getByLabelText("Email"), "owner@example.test")
    await user.type(screen.getByLabelText("Password"), "correct-horse")
    await user.click(screen.getByRole("button", { name: "Sign in" }))

    // Then: the callback receives credentials while URL and Web Storage stay credential-free.
    expect(authenticate).toHaveBeenCalledWith({
      email: "owner@example.test",
      password: "correct-horse",
    })
    expect(window.location.href).toBe(initialUrl)
    expect(localStorage).toHaveLength(0)
    expect(sessionStorage).toHaveLength(0)
  })

  it("renders localized recovery copy instead of a raw service error", () => {
    // Given: a provider error string returned to the presentation boundary.
    render(
      <AuthPage
        locale="en"
        mode="sign-in"
        onAuthenticate={() => Promise.resolve()}
        onModeChange={vi.fn()}
        status={{ kind: "error", message: "postgres password leaked" }}
      />,
    )

    // When: the error state is rendered.
    const alert = screen.getByRole("alert")

    // Then: only stable localized recovery copy is visible.
    expect(alert).toHaveTextContent("Sign in could not be completed")
    expect(alert).not.toHaveTextContent("postgres password leaked")
  })

  it("keeps the product hero separate from the credential task", () => {
    // Given: a visitor reaches the public sign-in surface.
    const view = render(
      <AuthPage
        locale="en"
        mode="sign-in"
        onAuthenticate={() => Promise.resolve()}
        onModeChange={vi.fn()}
        status={{ kind: "ready" }}
      />,
    )

    // When: the public hierarchy renders.
    const authSurface = within(view.container)
    const hero = authSurface.getByRole("heading", { level: 1, name: "RAG‑Studio" })

    // Then: the product hero remains distinct from the sign-in task.
    expect(hero).toBeVisible()
    expect(authSurface.getByRole("heading", { level: 2, name: "Sign in" })).toBeVisible()
  })
})

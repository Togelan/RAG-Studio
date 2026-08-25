import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { PersonalKnowledgePage } from "./PersonalKnowledgePage"

vi.mock("../../app/locale-provider", () => ({
  useLocaleContext: () => ({ t: (key: string) => key }),
}))

vi.mock("../ingestion/IngestionPanel", () => ({
  IngestionPanel: () => <section aria-label="scoped-personal-knowledge" />,
}))

describe("PersonalKnowledgePage", () => {
  it("renders document management only on the established Knowledge leaf", () => {
    render(<PersonalKnowledgePage />)

    expect(screen.getByRole("region", { name: "personal_knowledge_region" })).toBeVisible()
    expect(screen.getByRole("region", { name: "scoped-personal-knowledge" })).toBeVisible()
  })
})

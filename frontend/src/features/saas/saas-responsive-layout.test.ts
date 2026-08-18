import { readFileSync } from "node:fs"

import { describe, expect, it } from "vitest"

const styles = readFileSync("src/features/saas/saas.css", "utf8")

describe("SaaS shell responsive layout", () => {
  it("moves navigation below the header before desktop controls collide", () => {
    expect(styles).toContain("@media (max-width: 1040px)")
  })
})

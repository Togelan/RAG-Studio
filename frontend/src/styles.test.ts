import { readFileSync } from "node:fs"

import { describe, expect, it } from "vitest"

describe("Stage 2 design token contract", () => {
  it("defines the Chat workspace width as a semantic layout token", async () => {
    const styles = readFileSync("src/styles.css", "utf8")
    const chatStyles = readFileSync("src/features/chat/chat-page.css", "utf8")

    expect(styles).toContain("--rs-layout-workspace: 1280px;")
    expect(styles).toContain("--rs-layout-bottom-nav-reserve:")
    expect(chatStyles).toContain("var(--rs-layout-bottom-nav-reserve)")
  })

  it("uses the mobile drawer without a fixed bottom navigation overlap", async () => {
    const shellStyles = readFileSync("src/components/shell/app-shell.css", "utf8")

    expect(shellStyles).toContain(".rs-shell__drawer {")
    expect(shellStyles).toContain("max-width: var(--rs-layout-drawer);")
    expect(shellStyles).toContain("flex-wrap: wrap;")
    expect(shellStyles).not.toContain(".rs-shell__bottom-nav")
    expect(shellStyles).not.toContain("var(--rs-layout-bottom-nav-reserve)")
  })

  it("routes Settings and ingestion geometry through semantic tokens", async () => {
    const styles = readFileSync("src/styles.css", "utf8")
    const featureStyles = [
      readFileSync("src/features/settings/settings.css", "utf8"),
      readFileSync("src/features/ingestion/ingestion.css", "utf8"),
    ].join("\n")

    expect(styles).toContain("--rs-layout-loading-block: 120px;")
    expect(styles).toContain("--rs-layout-progress: 200px;")
    expect(featureStyles).not.toMatch(/\b(?:1|120|200)px\b/u)
  })
})

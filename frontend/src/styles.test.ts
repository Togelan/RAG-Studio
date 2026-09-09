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

  it("keeps the drawer and compact bottom navigation as distinct mobile surfaces", async () => {
    const shellStyles = readFileSync("src/components/shell/app-shell.css", "utf8")

    expect(shellStyles).toContain(".rs-shell__drawer {")
    expect(shellStyles).toContain("max-width: var(--rs-layout-drawer);")
    expect(shellStyles).toContain("flex-wrap: wrap;")
    expect(shellStyles).toMatch(
      /\.rs-shell__bottom-nav \{\s+position: fixed;[\s\S]*?display: grid;[\s\S]*?grid-template-columns: repeat\(4, minmax\(0, 1fr\)\);[\s\S]*?\}/u,
    )
  })

  it("reserves compact content space and stacks labels without horizontal compression", async () => {
    const styles = readFileSync("src/styles.css", "utf8")
    const shellStyles = readFileSync("src/components/shell/app-shell.css", "utf8")

    expect(styles).toContain("--rs-layout-bottom-nav-reserve: calc(")
    expect(shellStyles).toMatch(
      /\.rs-shell__main \{\s+padding-bottom: calc\(var\(--rs-layout-bottom-nav-reserve\) \+ var\(--rs-space-24\)\);\s+\}/u,
    )
    expect(shellStyles).toMatch(
      /\.rs-shell__bottom-nav \{\s+position: fixed;[\s\S]*?min-height: var\(--rs-layout-bottom-nav-reserve\);[\s\S]*?\}/u,
    )
    expect(shellStyles).toMatch(
      /\.rs-shell__bottom-nav \.rs-shell__nav-link,\s+\.rs-shell__bottom-nav \.rs-shell__nav-location \{\s+flex-direction: column;[\s\S]*?\}/u,
    )
    expect(shellStyles).toMatch(
      /\.rs-shell__bottom-nav \.rs-shell__nav-link span,\s+\.rs-shell__bottom-nav \.rs-shell__nav-location > span:first-of-type \{[\s\S]*?font-size: var\(--rs-font-xs\);[\s\S]*?line-height: var\(--rs-line-height-tight\);[\s\S]*?max-width: 100%;[\s\S]*?\}/u,
    )
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

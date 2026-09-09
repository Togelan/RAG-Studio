import { readFile } from "node:fs/promises"
import { resolve } from "node:path"
import { pathToFileURL } from "node:url"
import { describe, expect, it } from "vitest"

const artifactPath = resolve(process.cwd(), "dist", "rag-studio-widget.v1.js")

describe("versioned widget artifact", () => {
  it("loads as a self-registering custom-element bundle", async () => {
    const artifact = await readFile(artifactPath, "utf8")
    expect(artifact.length).toBeGreaterThan(0)
    expect(artifact).not.toContain("OPENAI_API_KEY")
    expect(artifact).not.toContain("STRIPE_SECRET")

    await import(`${pathToFileURL(artifactPath).href}?artifact-test`)
    expect(customElements.get("rag-studio-widget")).toBeDefined()
  })
})

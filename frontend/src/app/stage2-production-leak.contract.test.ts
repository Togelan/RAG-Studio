import { describe, expect, it } from "vitest"

import { localeKeys } from "../i18n/locale-inventory"

const productionModules = import.meta.glob(
  ["../**/*.{ts,tsx}", "!../**/*.test.{ts,tsx}", "!../test/**"],
  { eager: true, import: "default", query: "?raw" },
)

function sourceFor(pathSuffix: string): string {
  const entry = Object.entries(productionModules).find(([path]) => path.endsWith(pathSuffix))
  if (entry === undefined || typeof entry[1] !== "string") {
    throw new Error(`missing production source ${pathSuffix}`)
  }
  return entry[1]
}

function allProductionSource(): string {
  return Object.values(productionModules)
    .filter((value): value is string => typeof value === "string")
    .join("\n")
}

function legacyProductionSource(): string {
  return Object.entries(productionModules)
    .filter(([path, value]) => !path.includes("/features/saas/") && typeof value === "string")
    .map(([, value]) => value)
    .join("\n")
}

describe("Stage 2 production-leak contract", () => {
  it("keeps canonical React aliases and the approved Stage 3 SaaS entry only", () => {
    const app = sourceFor("/App.tsx")
    const paths = [...app.matchAll(/path="([^"]+)"/gu)].map((match) => match[1])

    expect(paths).toEqual([
      "/saas/*",
      "/",
      "/app",
      "/settings",
      "/app/settings",
      "/chat",
      "/app/chat",
      "*",
    ])
    expect(app).not.toMatch(
      /path="\/(?:auth|billing|pricing|widget|analytics|tenant|workspace)(?:\/|")/u,
    )
  })

  it("uses generated locale keys instead of locale-conditioned UI copy", () => {
    const source = legacyProductionSource()
    const keyMatches = [...source.matchAll(/\b(?:t|format)\("([^"]+)"/gu)]
    const directKeys = keyMatches
      .map((match) => match[1])
      .filter((key): key is string => key !== undefined)
    const localeKeySet = new Set<string>(localeKeys)

    expect(directKeys.every((key) => localeKeySet.has(key))).toBe(true)
    expect(source).not.toMatch(/locale\s*===\s*["'](?:en|ru)["']/u)
  })

  it("keeps polling and stream cancellation cleanup explicit", () => {
    const health = sourceFor("/features/health/health-status.tsx")
    const ingestion = sourceFor("/features/ingestion/use-ingestion.ts")
    const chat = sourceFor("/features/chat/chat-controller.ts")

    expect(health).toContain("activeRequest?.abort()")
    expect(health).toContain("window.clearInterval(timer)")
    expect(ingestion).toContain("controller.abort()")
    expect(chat).toContain("this.#abortController?.abort()")
  })

  it("rejects dangerous HTML sinks and absolute API origins from production modules", () => {
    const source = allProductionSource()

    expect(source).not.toMatch(/dangerouslySetInnerHTML|insertAdjacentHTML|\.innerHTML\s*=/u)
    expect(source).not.toMatch(/https?:\/\//u)
  })

  it("confines developer tooling imports behind the production-safe DEV gate", () => {
    const source = allProductionSource()
    const instrumentation = sourceFor("/dev/instrumentation.ts")

    expect(source.match(/react-(?:grab|scan|doctor)/gu)).toEqual(["react-grab", "react-scan"])
    expect(instrumentation).toContain("if (!import.meta.env.DEV")
    expect(instrumentation).toContain('import("react-grab")')
    expect(instrumentation).toContain('import("react-scan")')
  })
})

import { readFile } from "node:fs/promises"
import { fileURLToPath } from "node:url"

const threshold = 70
const coverageSummaryPath = fileURLToPath(
  new URL("../coverage/coverage-summary.json", import.meta.url),
)
const lowCoverage = {
  total: {
    branches: { pct: 0 },
    functions: { pct: 0 },
    lines: { pct: 0 },
    statements: { pct: 0 },
  },
}

function metrics(summary) {
  const total = summary.total
  if (total === undefined) {
    throw new Error("Coverage summary must include total metrics")
  }

  return Object.entries(total).filter(
    ([, value]) =>
      typeof value === "object" &&
      value !== null &&
      "pct" in value &&
      typeof value.pct === "number",
  )
}

function validate(summary) {
  const results = metrics(summary)
  const failing = results.filter(([, value]) => value.pct < threshold)
  if (failing.length > 0) {
    throw new Error(
      `Coverage threshold ${threshold}% failed: ${failing
        .map(([name, value]) => `${name}=${value.pct}%`)
        .join(", ")}`,
    )
  }
  return results
}

const injectedLowReport = process.argv.includes("--inject-low")
const summary = injectedLowReport
  ? lowCoverage
  : JSON.parse(await readFile(coverageSummaryPath, "utf8"))

try {
  const results = validate(summary)
  console.log(`Coverage threshold ${threshold}% passed`, Object.fromEntries(results))
} catch (error) {
  if (error instanceof Error) {
    console.error(error.message)
    process.exitCode = 1
  } else {
    throw error
  }
}

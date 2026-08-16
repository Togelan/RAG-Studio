import { resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { defineConfig, devices } from "@playwright/test"

const frontendRoot = fileURLToPath(new URL(".", import.meta.url))
const {
  CI,
  PLAYWRIGHT_BASE_URL,
  PLAYWRIGHT_DATA_ROOT,
  PLAYWRIGHT_PORT,
  PLAYWRIGHT_PYTHON,
  PLAYWRIGHT_REACT_DIST,
  PLAYWRIGHT_REPORT_NAME,
} = process.env
const port = Number(PLAYWRIGHT_PORT ?? "5191")
const baseURL = PLAYWRIGHT_BASE_URL ?? `http://127.0.0.1:${port}`
const python =
  PLAYWRIGHT_PYTHON ??
  (process.platform === "win32"
    ? resolve(frontendRoot, "..", "venv", "Scripts", "python.exe")
    : resolve(frontendRoot, "..", "venv", "bin", "python"))
const harness = resolve(frontendRoot, "..", "scripts", "run_chat_ui_fake.py")
const dataRoot =
  PLAYWRIGHT_DATA_ROOT ?? resolve(frontendRoot, "test-results", "playwright-fake-data")
const reactDist = PLAYWRIGHT_REACT_DIST ?? resolve(frontendRoot, "dist")
const task18EvidenceRoot = resolve(
  frontendRoot,
  "..",
  ".omo",
  "evidence",
  "ulw",
  "stage2-react-fr012-parity-01a000f9",
  "G001-execute-the-approved-stage-2-plan-at",
  "a1",
  "task-18-playwright",
)
export function reportNameFor(
  argumentsList: readonly string[],
  configuredName: string | undefined,
): string {
  if (configuredName !== undefined && configuredName !== "") return configuredName
  const command = argumentsList.join(" ")
  if (command.includes("@a11y")) return "a11y"
  if (command.includes("@perf")) return "perf"
  return "e2e"
}

const reportName = reportNameFor(process.argv, PLAYWRIGHT_REPORT_NAME)
const reportRoot = resolve(task18EvidenceRoot, reportName)

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  forbidOnly: Boolean(CI),
  outputDir: resolve(reportRoot, "artifacts"),
  workers: 1,
  reporter: [
    ["dot"],
    ["json", { outputFile: resolve(reportRoot, `${reportName}-results.json`) }],
    ["html", { open: "never", outputFolder: resolve(reportRoot, `${reportName}-report`) }],
  ],
  globalTeardown: "./playwright.global-teardown.ts",
  use: {
    baseURL,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], hasTouch: true } },
    { name: "firefox", use: { ...devices["Desktop Firefox"], hasTouch: true } },
    { name: "webkit", use: { ...devices["Desktop Safari"], hasTouch: true } },
  ],
  ...(PLAYWRIGHT_BASE_URL
    ? {}
    : {
        webServer: {
          command: `"${python}" "${harness}" --port ${port} --data-root "${dataRoot}"`,
          cwd: frontendRoot,
          env: {
            PYTHONPATH: resolve(frontendRoot, ".."),
            RAG_STUDIO_CHAT_RPM_LIMIT: "1000",
            RAG_STUDIO_GENERAL_RPM_LIMIT: "1000",
            RAG_STUDIO_REACT_DIST: reactDist,
            RAG_STUDIO_UI_MODE: "react",
          },
          reuseExistingServer: false,
          timeout: 120_000,
          url: baseURL,
        },
      }),
})

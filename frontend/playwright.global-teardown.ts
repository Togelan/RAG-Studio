import { execFile } from "node:child_process"
import { rm } from "node:fs/promises"
import { resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { promisify } from "node:util"

const execFileAsync = promisify(execFile)
const { PLAYWRIGHT_DATA_ROOT, PLAYWRIGHT_PORT } = process.env
const port = Number(PLAYWRIGHT_PORT ?? "5191")
const dataRoot = PLAYWRIGHT_DATA_ROOT

async function stopWindowsHarness(): Promise<void> {
  if (process.platform !== "win32") return

  const { stdout } = await execFileAsync("netstat", ["-ano", "-p", "TCP"])
  const processIds = stdout
    .split("\n")
    .flatMap(
      (line) =>
        line.match(new RegExp(`^\\s*TCP\\s+\\S+:${port}\\s+\\S+\\s+LISTENING\\s+(\\d+)`))?.[1] ??
        [],
    )

  await Promise.all(
    processIds.map(async (processId) => execFileAsync("taskkill", ["/PID", processId, "/T", "/F"])),
  )
}

// biome-ignore lint/style/noDefaultExport: framework entrypoint
export default async function teardownPlaywrightHarness(): Promise<void> {
  const frontendRoot = fileURLToPath(new URL(".", import.meta.url))
  await stopWindowsHarness()
  await rm(dataRoot ?? resolve(frontendRoot, "test-results", "playwright-fake-data"), {
    force: true,
    maxRetries: 10,
    recursive: true,
    retryDelay: 200,
  })
}

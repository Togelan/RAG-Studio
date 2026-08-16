import { readdir, readFile } from "node:fs/promises"
import { join } from "node:path"
import { fileURLToPath } from "node:url"

const forbiddenMarkers = ["react-grab", "react-scan", "react-doctor"]

async function filesUnder(directory) {
  const entries = await readdir(directory, { withFileTypes: true })
  const files = []

  for (const entry of entries) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) {
      files.push(...(await filesUnder(path)))
    } else {
      files.push(path)
    }
  }

  return files
}

const files = await filesUnder(fileURLToPath(new URL("../dist", import.meta.url)))
const sourceMaps = files.filter((file) => file.endsWith(".map"))
const textFiles = files.filter((file) => /\.(css|html|js)$/.test(file))
const bundle = await Promise.all(textFiles.map((file) => readFile(file, "utf8")))
const leakedMarker = forbiddenMarkers.find((marker) =>
  bundle.some((asset) => asset.includes(marker)),
)

if (sourceMaps.length > 0 || leakedMarker !== undefined) {
  console.error("Production audit failed", { leakedMarker, sourceMaps })
  process.exitCode = 1
} else {
  console.log("Production audit passed")
}

import { createHash } from "node:crypto"
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs"
import { relative, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import type { TestInfo } from "@playwright/test"

const frontendRoot = resolve(fileURLToPath(new URL(".", import.meta.url)), "..", "..")

function collectFiles(root: string): string[] {
  if (!existsSync(root)) return []
  return readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(root, entry.name)
    return entry.isDirectory() ? collectFiles(path) : [path]
  })
}

function hashFiles(root: string, files: readonly string[]): string {
  const hash = createHash("sha256")
  for (const path of [...files].sort()) {
    hash.update(relative(root, path).replaceAll("\\", "/"))
    hash.update(readFileSync(path))
  }
  return hash.digest("hex")
}

function fileHash(path: string): string {
  return createHash("sha256").update(readFileSync(path)).digest("hex")
}

export function bundleIdentity(): Record<string, unknown> {
  const distRoot = process.env.PLAYWRIGHT_REACT_DIST ?? resolve(frontendRoot, "dist")
  const sourceRoot = resolve(frontendRoot, "src")
  const sourceFiles = collectFiles(sourceRoot)
  const assetRoot = resolve(distRoot, "assets")
  const assetFiles = collectFiles(assetRoot)
  const indexPath = resolve(distRoot, "index.html")
  const bundleFiles = existsSync(indexPath) ? [indexPath, ...assetFiles] : assetFiles

  return {
    bundle: {
      files: bundleFiles.map((path) => ({
        path: relative(frontendRoot, path).replaceAll("\\", "/"),
        sha256: fileHash(path),
        bytes: statSync(path).size,
      })),
      sha256: hashFiles(distRoot, bundleFiles),
    },
    source: {
      files: sourceFiles.length,
      root: "frontend/src",
      sha256: hashFiles(sourceRoot, sourceFiles),
    },
  }
}

export async function attachBundleIdentity(testInfo: TestInfo): Promise<void> {
  await testInfo.attach("task18-bundle-identity.json", {
    body: JSON.stringify(bundleIdentity(), null, 2),
    contentType: "application/json",
  })
}

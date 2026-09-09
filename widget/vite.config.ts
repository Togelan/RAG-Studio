import { fileURLToPath } from "node:url"
import { defineConfig } from "vite"

const entry = fileURLToPath(new URL("./src/index.ts", import.meta.url))

export default defineConfig({
  build: {
    emptyOutDir: true,
    lib: {
      entry,
      formats: ["iife"],
      name: "RagStudioWidgetV1",
      fileName: () => "rag-studio-widget.v1.js",
    },
    minify: "oxc",
    sourcemap: false,
  },
})

import { createRoot } from "react-dom/client"

import { App } from "./App"
import { enableDevelopmentInstrumentation } from "./dev/instrumentation"
import "./styles.css"

void enableDevelopmentInstrumentation()

const rootElement = document.getElementById("root")

if (rootElement === null) {
  throw new Error("RAG-Studio root element is unavailable")
}

createRoot(rootElement).render(<App />)

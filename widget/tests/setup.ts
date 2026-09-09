import { afterEach } from "vitest"

afterEach(() => {
  document.body.replaceChildren()
  document.head.replaceChildren()
})

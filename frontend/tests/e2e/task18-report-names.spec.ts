import { expect, test } from "@playwright/test"
import config, { reportNameFor } from "../../playwright.config"

test("keeps the selected JSON and HTML reports together under its lane", () => {
  const reportName = reportNameFor(process.argv, process.env.PLAYWRIGHT_REPORT_NAME)
  const reporterConfiguration = JSON.stringify(config.reporter).replaceAll("\\\\", "/")

  expect(reporterConfiguration).toContain(
    `/task-18-playwright/${reportName}/${reportName}-results.json`,
  )
  expect(reporterConfiguration).toContain(`/task-18-playwright/${reportName}/${reportName}-report`)
})

test("@a11y @perf assigns a distinct report name to each standard Playwright lane", () => {
  expect(reportNameFor(["playwright", "test"], undefined)).toBe("e2e")
  expect(reportNameFor(["playwright", "test", "--grep", "@a11y"], undefined)).toBe("a11y")
  expect(reportNameFor(["playwright", "test", "--grep", "@perf"], undefined)).toBe("perf")
  expect(reportNameFor(["playwright", "test"], "review-rerun")).toBe("review-rerun")
})

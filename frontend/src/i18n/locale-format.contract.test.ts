import { describe, expect, it } from "vitest"

import { localeKeys } from "./locale-inventory"
import { createLocaleTranslations, formatLocaleMessage } from "./locale-runtime"

function translations() {
  const parsed = createLocaleTranslations({
    ...Object.fromEntries(localeKeys.map((key) => [key, key])),
    chat_session_message_count: "Messages: {count}",
    chat_retry_after: "Please retry in {seconds} seconds.",
    settings_upload_file_types_helper: "Files: {count}",
    ingestion_batch_limit: "Choose at most {count} files per batch.",
    ingestion_delete_document_aria: "Delete {name}",
    ingestion_delete_document_message: "This removes the indexed chunks for {name}.",
    ingestion_upload_file_progress: "{name} progress",
  })

  if (parsed === null) {
    throw new Error("test translations must be complete")
  }

  return parsed
}

describe("locale message formatter", () => {
  it("formats the authoritative ingestion count and filename templates", () => {
    const messages = translations()

    expect(formatLocaleMessage(messages, "ingestion_batch_limit", { count: 20 })).toBe(
      "Choose at most 20 files per batch.",
    )
    expect(
      formatLocaleMessage(messages, "ingestion_delete_document_aria", { name: "notes.pdf" }),
    ).toBe("Delete notes.pdf")
  })
})

import { useLocaleContext } from "../../app/locale-provider"
import { Label } from "../../components/ui/label"
import { Select } from "../../components/ui/select"
import { ChunkingSettingsSchema, ChunkingStrategySchema, type SettingsDraft } from "./settings-api"

type ChunkingSettingsSectionProps = {
  readonly draft: SettingsDraft
  readonly onDraftChange: (draft: SettingsDraft) => void
}

function numericOptions(values: readonly number[]): readonly { label: string; value: string }[] {
  return values.map((value) => ({ label: String(value), value: String(value) }))
}

export function ChunkingSettingsSection({
  draft,
  onDraftChange,
}: ChunkingSettingsSectionProps): React.JSX.Element {
  const { t } = useLocaleContext()
  const updateChunking = (next: Partial<SettingsDraft["chunking"]>): void => {
    const chunking = ChunkingSettingsSchema.parse({ ...draft.chunking, ...next })
    onDraftChange({
      ...draft,
      chunk_size: chunking.chunk_size,
      chunk_overlap: chunking.chunk_overlap,
      chunking,
    })
  }

  return (
    <section aria-labelledby="chunk-settings-title" className="rs-settings-section">
      <div className="rs-settings-section__heading">
        <div>
          <p className="rs-settings-section__eyebrow">{t("settings_index_behavior")}</p>
          <h2 id="chunk-settings-title">{t("settings_chunking_strategy_label")}</h2>
        </div>
      </div>
      <div className="rs-settings-grid rs-settings-grid--three">
        <div className="rs-field">
          <Label htmlFor="settings-strategy">{t("settings_chunking_strategy_label")}</Label>
          <Select
            id="settings-strategy"
            onChange={(event) => {
              updateChunking({ strategy: ChunkingStrategySchema.parse(event.currentTarget.value) })
            }}
            options={[
              { label: t("settings_chunking_strategy_static"), value: "static" },
              { label: t("settings_chunking_strategy_recursive"), value: "recursive" },
              { label: t("settings_chunking_strategy_parent_document"), value: "parent_document" },
              { label: t("settings_chunking_strategy_sentence_window"), value: "sentence_window" },
            ]}
            value={draft.chunking.strategy}
          />
        </div>
        {draft.chunking.strategy !== "sentence_window" ? (
          <>
            <div className="rs-field">
              <Label htmlFor="settings-chunk-size">{t("settings_chunk_size_label")}</Label>
              <Select
                id="settings-chunk-size"
                onChange={(event) => {
                  updateChunking({
                    chunk_size: ChunkingSettingsSchema.shape.chunk_size.parse(
                      Number(event.currentTarget.value),
                    ),
                  })
                }}
                options={numericOptions([256, 512, 1024])}
                value={String(draft.chunking.chunk_size)}
              />
            </div>
            <div className="rs-field">
              <Label htmlFor="settings-chunk-overlap">{t("settings_chunk_overlap_label")}</Label>
              <Select
                id="settings-chunk-overlap"
                onChange={(event) => {
                  updateChunking({
                    chunk_overlap: ChunkingSettingsSchema.shape.chunk_overlap.parse(
                      Number(event.currentTarget.value),
                    ),
                  })
                }}
                options={numericOptions([32, 64, 128])}
                value={String(draft.chunking.chunk_overlap)}
              />
            </div>
          </>
        ) : null}
        {draft.chunking.strategy === "parent_document" ? (
          <div className="rs-field">
            <Label htmlFor="settings-parent-size">{t("settings_parent_size_label")}</Label>
            <Select
              id="settings-parent-size"
              onChange={(event) => {
                updateChunking({
                  parent_size: ChunkingSettingsSchema.shape.parent_size.parse(
                    Number(event.currentTarget.value),
                  ),
                })
              }}
              options={numericOptions(
                [512, 1024, 2048, 4096].filter((size) => size >= draft.chunking.chunk_size),
              )}
              value={String(draft.chunking.parent_size ?? 2048)}
            />
          </div>
        ) : null}
        {draft.chunking.strategy === "sentence_window" ? (
          <div className="rs-field">
            <Label htmlFor="settings-window-sentences">
              {t("settings_window_sentences_label")}
            </Label>
            <Select
              id="settings-window-sentences"
              onChange={(event) => {
                updateChunking({
                  window_sentences: ChunkingSettingsSchema.shape.window_sentences.parse(
                    Number(event.currentTarget.value),
                  ),
                })
              }}
              options={numericOptions([1, 2, 3])}
              value={String(draft.chunking.window_sentences ?? 2)}
            />
          </div>
        ) : null}
      </div>
    </section>
  )
}

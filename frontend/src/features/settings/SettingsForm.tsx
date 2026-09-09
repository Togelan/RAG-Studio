import { RefreshCw, RotateCcw } from "lucide-react"

import { useLocaleContext } from "../../app/locale-provider"
import { Button } from "../../components/ui/button"
import { Input } from "../../components/ui/input"
import { Label } from "../../components/ui/label"
import { Select } from "../../components/ui/select"
import { Textarea } from "../../components/ui/textarea"
import { ChunkingSettingsSection } from "./ChunkingSettingsSection"
import { type ModelsResponse, ProviderSchema, type SettingsDraft } from "./settings-api"

type SettingsFormProps = {
  readonly apiKey: string
  readonly draft: SettingsDraft
  readonly keyIsStored: boolean
  readonly models: readonly string[]
  readonly modelsStatus?: ModelsResponse | null
  readonly onApiKeyChange: (value: string) => void
  readonly onClearStoredKey: () => void
  readonly onDraftChange: (draft: SettingsDraft) => void
  readonly onRefreshModels: () => void
  readonly onResetPrompt: () => void
}

const providerOptions = [
  { label: "OpenAI", value: "openai", disabled: true },
  { label: "DeepSeek", value: "deepseek", disabled: false },
  { label: "Anthropic", value: "anthropic", disabled: true },
  { label: "Local / Ollama", value: "ollama", disabled: true },
] as const

function numericOptions(values: readonly number[]): readonly { label: string; value: string }[] {
  return values.map((value) => ({ label: String(value), value: String(value) }))
}

export function SettingsForm({
  apiKey,
  draft,
  keyIsStored,
  models,
  modelsStatus = null,
  onApiKeyChange,
  onClearStoredKey,
  onDraftChange,
  onRefreshModels,
  onResetPrompt,
}: SettingsFormProps): React.JSX.Element {
  const { t } = useLocaleContext()
  const modelOptions = [draft.model, ...models.filter((model) => model !== draft.model)].map(
    (model) => ({ label: model, value: model }),
  )
  return (
    <div className="rs-settings-form">
      <section aria-labelledby="provider-settings-title" className="rs-settings-section">
        <div className="rs-settings-section__heading">
          <div>
            <p className="rs-settings-section__eyebrow">{t("settings_model_connection")}</p>
            <h2 id="provider-settings-title">{t("settings_provider_label")}</h2>
          </div>
          <Button
            aria-label={t("settings_refresh_models")}
            onClick={onRefreshModels}
            size="icon"
            variant="secondary"
          >
            <RefreshCw aria-hidden="true" size={17} />
          </Button>
        </div>
        <div className="rs-settings-grid rs-settings-grid--two">
          <div className="rs-field">
            <Label htmlFor="settings-provider">{t("settings_provider_label")}</Label>
            <span className="rs-select">
              <select
                className="rs-select__control"
                id="settings-provider"
                onChange={(event) => {
                  onDraftChange({
                    ...draft,
                    provider: ProviderSchema.parse(event.currentTarget.value),
                  })
                }}
                value={draft.provider}
              >
                {providerOptions.map((option) => (
                  <option disabled={option.disabled} key={option.value} value={option.value}>
                    {option.label}
                    {option.disabled ? ` — ${t("settings_provider_coming_soon")}` : ""}
                  </option>
                ))}
              </select>
            </span>
          </div>
          <div className="rs-field">
            <Label htmlFor="settings-model">{t("settings_model_label")}</Label>
            <Select
              id="settings-model"
              onChange={(event) => {
                onDraftChange({ ...draft, model: event.currentTarget.value })
              }}
              options={modelOptions}
              value={draft.model}
            />
            {modelsStatus?.cached ? (
              <small className="rs-field__hint">{t("settings_cached_model_list")}</small>
            ) : null}
            {modelsStatus?.error ? (
              <small className="rs-field__warning">{t("settings_provider_list_unavailable")}</small>
            ) : null}
          </div>
          <div className="rs-field rs-settings-grid__wide">
            <Label htmlFor="settings-api-key">{t("settings_api_key_label")}</Label>
            <Input
              autoComplete="off"
              disabled={draft.provider === "ollama"}
              id="settings-api-key"
              onChange={(event) => {
                onApiKeyChange(event.currentTarget.value)
              }}
              placeholder={
                draft.provider === "ollama"
                  ? t("settings_api_key_ollama_placeholder")
                  : keyIsStored && apiKey.length === 0
                    ? "••••••••"
                    : t("settings_api_key_placeholder")
              }
              type="password"
              value={apiKey}
            />
            <small className="rs-field__hint">{t("settings_stored_keys_helper")}</small>
            {keyIsStored ? (
              <Button onClick={onClearStoredKey} size="compact" variant="danger">
                {t("settings_clear_stored_key")}
              </Button>
            ) : null}
          </div>
        </div>
      </section>

      <section aria-labelledby="generation-settings-title" className="rs-settings-section">
        <div className="rs-settings-section__heading">
          <div>
            <p className="rs-settings-section__eyebrow">{t("settings_answer_behavior")}</p>
            <h2 id="generation-settings-title">{t("settings_generation")}</h2>
          </div>
        </div>
        <div className="rs-settings-grid rs-settings-grid--three">
          <div className="rs-field">
            <Label htmlFor="settings-temperature">
              {t("settings_temperature_label")}: {draft.temperature.toFixed(2)}
            </Label>
            <Input
              id="settings-temperature"
              max="2"
              min="0"
              onChange={(event) => {
                onDraftChange({ ...draft, temperature: Number(event.currentTarget.value) })
              }}
              step="0.01"
              type="range"
              value={draft.temperature}
            />
          </div>
          <div className="rs-field">
            <Label htmlFor="settings-max-tokens">{t("settings_max_tokens_label")}</Label>
            <Select
              id="settings-max-tokens"
              onChange={(event) => {
                onDraftChange({ ...draft, max_tokens: Number(event.currentTarget.value) })
              }}
              options={numericOptions([512, 1024, 2048, 4096, 8192, 16_384])}
              value={String(draft.max_tokens)}
            />
          </div>
          <div className="rs-field">
            <Label htmlFor="settings-top-k">{t("settings_top_k_label")}</Label>
            <Select
              id="settings-top-k"
              onChange={(event) => {
                onDraftChange({ ...draft, top_k: Number(event.currentTarget.value) })
              }}
              options={numericOptions([3, 5, 10, 20])}
              value={String(draft.top_k)}
            />
          </div>
          <div className="rs-field rs-settings-grid__wide">
            <div className="rs-field__label-row">
              <Label htmlFor="settings-system-prompt">{t("settings_system_prompt_label")}</Label>
              <Button
                className="rs-settings-reset-prompt"
                onClick={onResetPrompt}
                size="compact"
                variant="secondary"
              >
                <RotateCcw aria-hidden="true" size={15} />
                {t("settings_reset_prompt")}
              </Button>
            </div>
            <Textarea
              id="settings-system-prompt"
              onChange={(event) => {
                onDraftChange({ ...draft, system_prompt: event.currentTarget.value })
              }}
              rows={5}
              value={draft.system_prompt}
            />
          </div>
        </div>
      </section>

      <ChunkingSettingsSection draft={draft} onDraftChange={onDraftChange} />
    </div>
  )
}

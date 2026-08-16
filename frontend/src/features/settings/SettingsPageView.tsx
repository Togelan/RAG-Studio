import { Database, Save, Undo2, Workflow } from "lucide-react"
import type { RefObject } from "react"

import { useLocaleContext } from "../../app/locale-provider"
import { Button } from "../../components/ui/button"
import { Skeleton } from "../../components/ui/skeleton"

export type SaveState = "error" | "idle" | "invalid-key" | "saved" | "saving"

export function SettingsHero(): React.JSX.Element {
  const { t } = useLocaleContext()
  return (
    <header className="rs-settings-hero">
      <div>
        <p className="rs-settings-hero__eyebrow">
          <Workflow aria-hidden="true" size={16} /> {t("settings_workspace_eyebrow")}
        </p>
        <p className="rs-settings-hero__title">{t("settings_title")}</p>
        <p>{t("settings_subtitle")}</p>
      </div>
      <div
        aria-label={t("settings_local_encrypted_status")}
        className="rs-settings-hero__status"
        role="status"
      >
        <Database aria-hidden="true" size={18} />
        <span>{t("settings_local_encrypted_status")}</span>
      </div>
    </header>
  )
}

export function SettingsLoadingState(): React.JSX.Element {
  const { t } = useLocaleContext()
  return (
    <div aria-label={t("settings_loading")} className="rs-settings-loading" role="status">
      <Skeleton />
      <Skeleton />
      <Skeleton />
    </div>
  )
}

type SettingsSaveBarProps = {
  readonly dirty: boolean
  readonly onDiscard: () => void
  readonly onSubmit: () => void
  readonly saveButtonRef: RefObject<HTMLButtonElement | null>
  readonly state: SaveState
}

function SaveStatus({ dirty, state }: Pick<SettingsSaveBarProps, "dirty" | "state">) {
  const { t } = useLocaleContext()
  return (
    <div aria-live="polite">
      {state === "idle"
        ? t(dirty ? "settings_unsaved_changes" : "settings_all_changes_saved")
        : null}
      {state === "saving" ? t("settings_validating") : null}
      {state === "saved" ? t("settings_saved") : null}
      {state === "error" ? <span role="alert">{t("settings_save_error")}</span> : null}
      {state === "invalid-key" ? <span role="alert">{t("settings_invalid_key")}</span> : null}
    </div>
  )
}

export function SettingsSaveBar({
  dirty,
  onDiscard,
  onSubmit,
  saveButtonRef,
  state,
}: SettingsSaveBarProps): React.JSX.Element {
  const { t } = useLocaleContext()
  const disabled = !dirty || state === "saving"
  return (
    <form
      className={dirty ? "rs-settings-savebar rs-settings-savebar--sticky" : "rs-settings-savebar"}
      onSubmit={(event) => {
        event.preventDefault()
        onSubmit()
      }}
    >
      <SaveStatus dirty={dirty} state={state} />
      <div className="rs-settings-savebar__actions">
        <Button disabled={disabled} onClick={onDiscard} variant="secondary">
          <Undo2 aria-hidden="true" size={17} />
          {t("settings_discard_changes")}
        </Button>
        <Button disabled={disabled} ref={saveButtonRef} type="submit">
          <Save aria-hidden="true" size={17} />
          {t("settings_save")}
        </Button>
      </div>
    </form>
  )
}

export function ObservabilityNotice(): React.JSX.Element {
  const { t } = useLocaleContext()
  return (
    <section className="rs-settings-section rs-langsmith-notice">
      <div>
        <p className="rs-settings-section__eyebrow">{t("settings_observability")}</p>
        <h2>{t("settings_langsmith_title")}</h2>
      </div>
      <p>{t("settings_langsmith_desc")}</p>
      <Button disabled variant="secondary">
        {t("settings_langsmith_coming_soon")}
      </Button>
    </section>
  )
}

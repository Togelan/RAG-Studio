import { useCallback, useEffect, useRef, useState } from "react"

import { ApiContractError, ApiError, isAbortError } from "../../api/errors"
import { useLocaleContext } from "../../app/locale-provider"
import { IngestionPanel } from "../ingestion/IngestionPanel"
import { type IngestionApi, ingestionApi, type ReingestSummary } from "../ingestion/ingestion-api"
import { ReingestDialog } from "../ingestion/ReingestDialog"
import { SettingsForm } from "./SettingsForm"
import {
  ObservabilityNotice,
  type SaveState,
  SettingsHero,
  SettingsLoadingState,
  SettingsSaveBar,
} from "./SettingsPageView"
import {
  type ModelsResponse,
  type SavedSettings,
  type SettingsApi,
  type SettingsDraft,
  settingsApi,
} from "./settings-api"
import "./settings.css"

type SettingsPageProps = {
  readonly ingestion?: IngestionApi
  readonly settings?: SettingsApi
}

const DEFAULT_PROMPTS = {
  en: "You are RAG-Studio AI assistant. Answer strictly based on the provided context. If you don't know, say so.",
  ru: "Ты — AI-ассистент RAG-Studio. Отвечай строго по загруженным документам. Если не знаешь, скажи об этом.",
} as const

function savedDraft(saved: SavedSettings): SettingsDraft {
  return {
    provider: saved.provider,
    model: saved.model,
    temperature: saved.temperature,
    max_tokens: saved.max_tokens,
    system_prompt: saved.system_prompt,
    top_k: saved.top_k,
    chunk_size: saved.chunk_size,
    chunk_overlap: saved.chunk_overlap,
    chunking: saved.chunking,
  }
}

function safeSettingsMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError || error instanceof ApiContractError) return error.message
  return fallback
}

export function SettingsPage({
  ingestion = ingestionApi,
  settings = settingsApi,
}: SettingsPageProps): React.JSX.Element {
  const { locale, t } = useLocaleContext()
  const unavailableMessage = t("settings_unavailable")
  const [draft, setDraft] = useState<SettingsDraft | null>(null)
  const [baseline, setBaseline] = useState<SettingsDraft | null>(null)
  const [apiKey, setApiKey] = useState("")
  const [keyIsStored, setKeyIsStored] = useState(false)
  const [models, setModels] = useState<readonly string[]>([])
  const [modelsStatus, setModelsStatus] = useState<ModelsResponse | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveState, setSaveState] = useState<SaveState>("idle")
  const [reingestOpen, setReingestOpen] = useState(false)
  const saveButtonRef = useRef<HTMLButtonElement>(null)
  const [refreshToken, setRefreshToken] = useState(0)
  const controllers = useRef(new Set<AbortController>())
  const loadRequest = useRef(0)
  const modelRequest = useRef(0)

  const trackedController = useCallback((): AbortController => {
    const controller = new AbortController()
    controllers.current.add(controller)
    return controller
  }, [])

  useEffect(() => {
    const requestId = loadRequest.current + 1
    loadRequest.current = requestId
    const controller = trackedController()
    void settings
      .load(controller.signal)
      .then(async (loaded) => {
        if (requestId !== loadRequest.current) return
        const loadedDraft: SettingsDraft = {
          provider: loaded.provider,
          model: loaded.model,
          temperature: loaded.temperature,
          max_tokens: loaded.max_tokens,
          system_prompt: loaded.system_prompt,
          top_k: loaded.top_k,
          chunk_size: loaded.chunk_size,
          chunk_overlap: loaded.chunk_overlap,
          chunking: loaded.chunking,
        }
        setDraft(loadedDraft)
        setBaseline(loadedDraft)
        setKeyIsStored(loaded.api_key === "********")
        const modelRequestId = modelRequest.current + 1
        modelRequest.current = modelRequestId
        try {
          const response = await settings.models(loaded.provider, controller.signal)
          if (requestId !== loadRequest.current || modelRequestId !== modelRequest.current) return
          setModels(response.models)
          setModelsStatus(response)
        } catch (error) {
          if (
            !isAbortError(error) &&
            requestId === loadRequest.current &&
            modelRequestId === modelRequest.current
          ) {
            setModels([])
            setModelsStatus({
              provider: loaded.provider,
              models: [],
              cached: false,
              error: "unavailable",
            })
          }
        }
      })
      .catch((error: unknown) => {
        if (!isAbortError(error) && requestId === loadRequest.current) {
          setLoadError(safeSettingsMessage(error, unavailableMessage))
        }
      })
      .finally(() => controllers.current.delete(controller))
    return () => controller.abort()
  }, [settings, trackedController, unavailableMessage])

  useEffect(
    () => () => {
      for (const controller of controllers.current) controller.abort()
      controllers.current.clear()
    },
    [],
  )

  const refreshModels = async (): Promise<void> => {
    if (draft === null) return
    const requestId = modelRequest.current + 1
    modelRequest.current = requestId
    const controller = trackedController()
    try {
      const response = await settings.models(draft.provider, controller.signal)
      if (requestId !== modelRequest.current) return
      setModels(response.models)
      setModelsStatus(response)
      if (!response.models.includes(draft.model) && response.models.length > 0) {
        const firstModel = response.models[0]
        if (firstModel !== undefined) setDraft({ ...draft, model: firstModel })
      }
    } catch (error) {
      if (!isAbortError(error) && requestId === modelRequest.current) {
        setModels([])
        setModelsStatus({
          provider: draft.provider,
          models: [],
          cached: false,
          error: "unavailable",
        })
      }
    } finally {
      controllers.current.delete(controller)
    }
  }

  const persistSave = async (): Promise<boolean> => {
    if (draft === null) return false
    const controller = trackedController()
    setSaveState("saving")
    try {
      if (apiKey.trim().length > 0) {
        const validation = await settings.validateKey(
          draft.provider,
          apiKey.trim(),
          controller.signal,
        )
        if (!validation.valid) {
          setSaveState("invalid-key")
          return false
        }
      }
      const saved = await settings.save(draft, controller.signal)
      const nextBaseline = savedDraft(saved)
      setDraft(nextBaseline)
      setBaseline(nextBaseline)
      if (apiKey.trim().length > 0) {
        setApiKey("")
        setKeyIsStored(true)
      }
      setSaveState("saved")
      return true
    } catch (error) {
      if (!isAbortError(error)) setSaveState("error")
      return false
    } finally {
      controllers.current.delete(controller)
    }
  }

  const isDirty =
    draft !== null &&
    baseline !== null &&
    (apiKey.trim().length > 0 || JSON.stringify(draft) !== JSON.stringify(baseline))

  const requestSave = async (): Promise<void> => {
    if (!isDirty || draft === null || baseline === null) return
    const chunksDirty = JSON.stringify(draft.chunking) !== JSON.stringify(baseline.chunking)
    if (chunksDirty) {
      const controller = trackedController()
      try {
        const page = await ingestion.documents(undefined, controller.signal)
        if (page.documents.length > 0) {
          setReingestOpen(true)
          return
        }
      } catch (error) {
        if (!isAbortError(error)) setSaveState("error")
        return
      } finally {
        controllers.current.delete(controller)
      }
    }
    await persistSave()
  }

  const completeReingest = (summary: ReingestSummary): void => {
    setRefreshToken((current) => current + 1)
    setSaveState(summary.failed > 0 ? "error" : "saved")
  }

  return (
    <div className="rs-settings-page">
      <SettingsHero />

      {loadError ? (
        <p className="rs-notice rs-notice--danger" role="alert">
          {loadError}
        </p>
      ) : null}
      {draft === null && loadError === null ? <SettingsLoadingState /> : null}
      {draft ? (
        <>
          <SettingsForm
            apiKey={apiKey}
            draft={draft}
            keyIsStored={keyIsStored}
            models={models}
            modelsStatus={modelsStatus}
            onApiKeyChange={setApiKey}
            onDraftChange={(nextDraft) => {
              setDraft(nextDraft)
              setSaveState("idle")
            }}
            onRefreshModels={() => void refreshModels()}
            onResetPrompt={() => {
              setDraft({ ...draft, system_prompt: DEFAULT_PROMPTS[locale] })
              setSaveState("idle")
            }}
          />
          <SettingsSaveBar
            dirty={isDirty}
            onDiscard={() => {
              if (baseline === null) return
              setDraft(baseline)
              setApiKey("")
              setSaveState("idle")
            }}
            onSubmit={() => void requestSave()}
            saveButtonRef={saveButtonRef}
            state={saveState}
          />
          <IngestionPanel api={ingestion} refreshToken={refreshToken} />
          <ObservabilityNotice />
        </>
      ) : null}
      <ReingestDialog
        api={ingestion}
        onBeforeReingest={persistSave}
        onClose={() => setReingestOpen(false)}
        onComplete={completeReingest}
        onSkip={persistSave}
        open={reingestOpen}
        restoreFocusRef={saveButtonRef}
      />
    </div>
  )
}

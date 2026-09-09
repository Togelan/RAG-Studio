import { CircleAlert, CircleCheck, CircleDashed, KeyRound, WifiOff } from "lucide-react"
import { useEffect, useState } from "react"
import { z } from "zod"

import { apiClient } from "../../api/client"
import { useLocaleContext } from "../../app/locale-provider"
import { getShellCopy } from "../../i18n/shell-copy"

const HealthResponseSchema = z.object({
  api_key_configured: z.boolean(),
  status: z.enum(["ready", "degraded"]),
})

export type HealthGateway = {
  readonly getStatus: (signal: AbortSignal) => Promise<unknown>
}

type HealthDisplayStatus = "checking" | "ready" | "degraded" | "offline" | "no-api-key"

const HEALTH_POLL_INTERVAL_MS = 30_000

function createHealthGateway(): HealthGateway {
  return {
    getStatus: (signal: AbortSignal) =>
      apiClient.get("/api/health/status", HealthResponseSchema, { signal }),
  }
}

function labelKey(
  status: HealthDisplayStatus,
): "status_checking" | "status_ready" | "status_disconnected" | "status_no_api_key" | null {
  switch (status) {
    case "checking":
      return "status_checking"
    case "ready":
      return "status_ready"
    case "degraded":
      return null
    case "offline":
      return "status_disconnected"
    case "no-api-key":
      return "status_no_api_key"
  }
}

function StatusIcon({ status }: { readonly status: HealthDisplayStatus }): React.JSX.Element {
  switch (status) {
    case "ready":
      return <CircleCheck aria-hidden="true" size={16} />
    case "no-api-key":
      return <KeyRound aria-hidden="true" size={16} />
    case "checking":
      return <CircleDashed aria-hidden="true" size={16} />
    case "degraded":
      return <CircleAlert aria-hidden="true" size={16} />
    case "offline":
      return <WifiOff aria-hidden="true" size={16} />
  }
}

export function HealthStatus({
  gateway = createHealthGateway(),
}: {
  readonly gateway?: HealthGateway | undefined
}): React.JSX.Element {
  const [status, setStatus] = useState<HealthDisplayStatus>("checking")
  const { locale, t } = useLocaleContext()

  useEffect(() => {
    let activeRequest: AbortController | null = null
    let mounted = true

    const refresh = (): void => {
      activeRequest?.abort()
      const request = new AbortController()
      activeRequest = request
      void gateway.getStatus(request.signal).then(
        (response) => {
          if (!mounted || request.signal.aborted) {
            return
          }
          const parsedResponse = HealthResponseSchema.safeParse(response)
          if (!parsedResponse.success) {
            setStatus("offline")
            return
          }
          setStatus(
            parsedResponse.data.status === "ready"
              ? parsedResponse.data.api_key_configured
                ? "ready"
                : "no-api-key"
              : "degraded",
          )
        },
        () => {
          if (mounted && !request.signal.aborted) {
            setStatus("offline")
          }
        },
      )
    }

    refresh()
    const timer = window.setInterval(refresh, HEALTH_POLL_INTERVAL_MS)

    return (): void => {
      mounted = false
      window.clearInterval(timer)
      activeRequest?.abort()
    }
  }, [gateway])

  const translationKey = labelKey(status)
  const label = translationKey === null ? getShellCopy(locale).healthDegraded : t(translationKey)

  return (
    <p aria-live="polite" className={`rs-health rs-health--${status}`} role="status">
      <StatusIcon status={status} />
      <span>{label}</span>
    </p>
  )
}

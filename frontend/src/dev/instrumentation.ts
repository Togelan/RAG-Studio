interface ReactScanModule {
  scan: (options: { enabled: boolean; showToolbar: boolean }) => void
}

interface ReactGrabModule {
  init: (options: { enabled: boolean }) => void
}

export async function enableDevelopmentInstrumentation(): Promise<void> {
  if (!import.meta.env.DEV || import.meta.env.VITE_DISABLE_REACT_DEVTOOLS === "1") {
    return
  }

  const [{ init }, { scan }] = await Promise.all([
    import("react-grab") as Promise<ReactGrabModule>,
    import("react-scan") as Promise<ReactScanModule>,
  ])
  init({ enabled: true })
  scan({ enabled: true, showToolbar: false })
}

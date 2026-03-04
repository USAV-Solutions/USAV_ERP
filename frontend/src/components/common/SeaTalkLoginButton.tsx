import { useEffect, useMemo, useState } from 'react'
import { Box, CircularProgress, Typography } from '@mui/material'

interface SeaTalkLoginButtonProps {
  size?: 'small' | 'medium' | 'large'
  theme?: 'light' | 'dark'
  copywriting?: string
  align?: 'left' | 'center' | 'right'
}

// How long (ms) to wait for the SDK to render before giving up and showing
// the button container anyway — prevents an infinite spinner in environments
// where the SDK is slow or the MutationObserver misses the injection.
const SDK_RENDER_TIMEOUT_MS = 6000

export default function SeaTalkLoginButton({
  size = 'medium',
  theme = 'light',
  copywriting = 'Continue with SeaTalk',
  align = 'center',
}: SeaTalkLoginButtonProps) {
  const appId = import.meta.env.VITE_SEATALK_APP_ID
  const redirectUri = import.meta.env.VITE_SEATALK_REDIRECT_URI
  const [sdkLoaded, setSdkLoaded] = useState(false)
  const [buttonReady, setButtonReady] = useState(false)
  const [sdkDebugLog, setSdkDebugLog] = useState<string[]>([])

  const addDebug = (msg: string) => {
    const ts = new Date().toISOString().slice(11, 23)
    console.log(`[SeaTalkBtn ${ts}] ${msg}`)
    setSdkDebugLog((prev) => [...prev.slice(-9), `${ts} ${msg}`])
  }

  const state = useMemo(() => Math.random().toString(36).substring(2, 15), [])

  useEffect(() => {
    if (!appId || !redirectUri) {
      addDebug('MISSING env: VITE_SEATALK_APP_ID or VITE_SEATALK_REDIRECT_URI')
      return
    }

    const existing = document.getElementById('seatalk-auth-sdk') as HTMLScriptElement | null

    if (existing) {
      addDebug(`Script tag found. data-loaded=${existing.dataset.loaded}`)
      if (existing.dataset.loaded === 'true') {
        setSdkLoaded(true)
        // SDK already loaded from a previous visit — re-trigger its DOM scan
        addDebug('Re-dispatching synthetic window load event (script already loaded)')
        window.dispatchEvent(new Event('load'))
      } else {
        const handleLoad = () => {
          addDebug('Existing script fired load event')
          setSdkLoaded(true)
          addDebug('Dispatching synthetic window load event for SDK init')
          window.dispatchEvent(new Event('load'))
        }
        existing.addEventListener('load', handleLoad)
        return () => existing.removeEventListener('load', handleLoad)
      }
      return
    }

    addDebug('Appending SDK script to body')
    const script = document.createElement('script')
    script.id = 'seatalk-auth-sdk'
    script.src = 'https://static.cdn.haiserve.com/seatalk/client/shared/sop/auth.js'
    script.async = true
    script.onload = () => {
      script.dataset.loaded = 'true'
      addDebug('SDK script onload fired')
      setSdkLoaded(true)
      // The SDK listens for window.onload to scan the DOM. In an SPA,
      // that event fired long before this component mounted. Dispatch a
      // synthetic load event so the SDK runs its initialization scan.
      addDebug('Dispatching synthetic window load event for SDK init')
      window.dispatchEvent(new Event('load'))
    }
    script.onerror = () => {
      addDebug('ERROR: SDK script failed to load (network error / blocked)')
    }
    document.body.appendChild(script)
  }, [appId, redirectUri])

  useEffect(() => {
    if (!sdkLoaded) return

    addDebug('sdkLoaded=true, checking container for existing button content')

    const buttonContainer = document.getElementById('seatalk_login_button')
    if (!buttonContainer) {
      addDebug('ERROR: #seatalk_login_button element not found in DOM')
      return
    }

    const hasRenderedButton = () => {
      const childCount = buttonContainer.childElementCount
      const inner = buttonContainer.innerHTML.trim()
      return childCount > 0 || inner.length > 0
    }

    if (hasRenderedButton()) {
      addDebug('Button already rendered (childCount or innerHTML present) — showing immediately')
      setButtonReady(true)
      return
    }

    addDebug('Setting up MutationObserver on #seatalk_login_button')
    const observer = new MutationObserver(() => {
      if (hasRenderedButton()) {
        addDebug('MutationObserver fired — button content detected, showing button')
        setButtonReady(true)
        observer.disconnect()
      }
    })

    // KEY FIX: we no longer hide the container with display:none — the SDK
    // needs to see a visible element.  The spinner is shown via a sibling
    // overlay, not by hiding the SDK container itself.
    observer.observe(buttonContainer, { childList: true, subtree: true })

    // Safety timeout: if the SDK never renders (blocked CDN, SeaTalk WebView
    // quirk, etc.) we show the container anyway after SDK_RENDER_TIMEOUT_MS.
    // This makes the empty container visible so the user isn't stuck on a
    // spinner with no way to recover.
    const timeout = window.setTimeout(() => {
      if (!hasRenderedButton()) {
        addDebug(`TIMEOUT (${SDK_RENDER_TIMEOUT_MS}ms): SDK never rendered. Showing container anyway.`)
        setButtonReady(true)
      }
      observer.disconnect()
    }, SDK_RENDER_TIMEOUT_MS)

    return () => {
      observer.disconnect()
      window.clearTimeout(timeout)
    }
  }, [sdkLoaded])

  if (!appId || !redirectUri) {
    return null
  }

  // Logo size mapping
  const logoSizeMap = {
    small: 18,
    medium: 22,
    large: 26,
  }

  const showDebug = import.meta.env.DEV || import.meta.env.VITE_SEATALK_DEBUG === 'true'

  return (
    <Box sx={{ minHeight: 56 }}>
      {/* SeaTalk App Info Configuration */}
      <div
        id="seatalk_login_app_info"
        data-redirect_uri={redirectUri}
        data-appid={appId}
        data-response_type="code"
        data-state={state}
      />

      {/*
        KEY FIX: The SDK container is ALWAYS visible (no display:none).
        The SeaTalk auth.js SDK skips rendering into hidden elements.
        We overlay the loading spinner on top of the container instead of
        hiding the container while waiting.
      */}
      <Box sx={{ position: 'relative', minHeight: 44 }}>
        {/* SDK button target — always in the visible layout */}
        <div
          id="seatalk_login_button"
          data-size={size}
          data-logo_size={logoSizeMap[size]}
          data-copywriting={copywriting}
          data-theme={theme}
          data-align={align}
        />

        {/* Loading overlay — sits on top while SDK renders, disappears after */}
        {!buttonReady && (
          <Box
            sx={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 1,
              bgcolor: 'background.paper',
              zIndex: 1,
            }}
          >
            <CircularProgress size={18} />
            <Typography variant="body2" color="text.secondary">
              Loading SeaTalk login...
            </Typography>
          </Box>
        )}
      </Box>

      {/* Debug log panel — visible in DEV or when VITE_SEATALK_DEBUG=true */}
      {showDebug && sdkDebugLog.length > 0 && (
        <Box
          sx={{
            mt: 1,
            p: 1,
            bgcolor: 'grey.900',
            borderRadius: 1,
            fontSize: 10,
            fontFamily: 'monospace',
            color: 'grey.400',
            maxHeight: 120,
            overflowY: 'auto',
          }}
        >
          <Typography variant="caption" sx={{ color: 'grey.500', display: 'block', mb: 0.5 }}>
            SeaTalk SDK debug log
          </Typography>
          {sdkDebugLog.map((line, i) => (
            <div key={i}>{line}</div>
          ))}
        </Box>
      )}
    </Box>
  )
}

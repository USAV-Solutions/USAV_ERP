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

  const state = useMemo(() => Math.random().toString(36).substring(2, 15), [])

  useEffect(() => {
    if (!appId || !redirectUri) return

    const existing = document.getElementById('seatalk-auth-sdk') as HTMLScriptElement | null

    if (existing) {
      if (existing.dataset.loaded === 'true') {
        setSdkLoaded(true)
        // SDK already loaded from a previous visit — re-trigger its DOM scan
        window.dispatchEvent(new Event('load'))
      } else {
        const handleLoad = () => {
          setSdkLoaded(true)
          window.dispatchEvent(new Event('load'))
        }
        existing.addEventListener('load', handleLoad)
        return () => existing.removeEventListener('load', handleLoad)
      }
      return
    }

    const script = document.createElement('script')
    script.id = 'seatalk-auth-sdk'
    script.src = 'https://static.cdn.haiserve.com/seatalk/client/shared/sop/auth.js'
    script.async = true
    script.onload = () => {
      script.dataset.loaded = 'true'
      setSdkLoaded(true)
      // The SDK listens for window.onload to scan the DOM. In an SPA,
      // that event fired long before this component mounted. Dispatch a
      // synthetic load event so the SDK runs its initialization scan.
      window.dispatchEvent(new Event('load'))
    }
    document.body.appendChild(script)
  }, [appId, redirectUri])

  useEffect(() => {
    if (!sdkLoaded) return

    const buttonContainer = document.getElementById('seatalk_login_button')
    if (!buttonContainer) return

    const hasRenderedButton = () => {
      const childCount = buttonContainer.childElementCount
      const inner = buttonContainer.innerHTML.trim()
      return childCount > 0 || inner.length > 0
    }

    if (hasRenderedButton()) {
      setButtonReady(true)
      return
    }

    const observer = new MutationObserver(() => {
      if (hasRenderedButton()) {
        setButtonReady(true)
        observer.disconnect()
      }
    })

    observer.observe(buttonContainer, { childList: true, subtree: true })

    // Safety timeout: if the SDK never renders (blocked CDN, SeaTalk WebView
    // quirk, etc.) we show the container anyway after SDK_RENDER_TIMEOUT_MS.
    const timeout = window.setTimeout(() => {
      if (!hasRenderedButton()) {
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
        The SDK container is ALWAYS visible (no display:none).
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
    </Box>
  )
}

import { useEffect, useMemo, useState } from 'react'
import { Box, CircularProgress, Typography } from '@mui/material'

interface SeaTalkLoginButtonProps {
  size?: 'small' | 'medium' | 'large'
  theme?: 'light' | 'dark'
  copywriting?: string
  align?: 'left' | 'center' | 'right'
}

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
      } else {
        const handleLoad = () => setSdkLoaded(true)
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

    const timeout = window.setTimeout(() => {
      if (!hasRenderedButton()) {
        console.warn('SeaTalk button not ready after waiting for SDK render.')
      }
    }, 5000)

    return () => {
      observer.disconnect()
      window.clearTimeout(timeout)
    }
  }, [sdkLoaded])

  if (!appId || !redirectUri) {
    console.error('SeaTalk configuration missing. Check VITE_SEATALK_APP_ID and VITE_SEATALK_REDIRECT_URI.')
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

      {/* SeaTalk Login Button */}
      <div
        id="seatalk_login_button"
        data-size={size}
        data-logo_size={logoSizeMap[size]}
        data-copywriting={copywriting}
        data-theme={theme}
        data-align={align}
        style={{ display: buttonReady ? 'block' : 'none' }}
      />

      {!buttonReady && (
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 1 }}>
          <CircularProgress size={18} />
          <Typography variant="body2" color="text.secondary">
            Loading SeaTalk login...
          </Typography>
        </Box>
      )}
    </Box>
  )
}

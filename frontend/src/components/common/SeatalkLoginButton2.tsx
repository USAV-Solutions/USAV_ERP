import { useEffect, useMemo, useState } from 'react'
import { Box, Button, CircularProgress, Typography } from '@mui/material'

interface SeaTalkLoginButtonProps {
  size?: 'small' | 'medium' | 'large'
  theme?: 'light' | 'dark'
  copywriting?: string
  align?: 'left' | 'center' | 'right'
}

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

  // 1. Detect if the user is viewing this inside the SeaTalk Mobile App
  const isSeaTalkApp = useMemo(() => {
    return /SeaTalk/i.test(navigator.userAgent)
  }, [])

  useEffect(() => {
    if (!appId || !redirectUri) return

    // If we are INSIDE SeaTalk, we don't need the external auth.js SDK
    if (isSeaTalkApp) {
      setButtonReady(true)
      return
    }

    // --- EXTERNAL BROWSER LOGIC: Load the external auth.js SDK ---
    const existing = document.getElementById('seatalk-auth-sdk') as HTMLScriptElement | null

    if (existing) {
      if (existing.dataset.loaded === 'true') {
        setSdkLoaded(true)
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
      window.dispatchEvent(new Event('load'))
    }
    document.body.appendChild(script)
  }, [appId, redirectUri, isSeaTalkApp])

  useEffect(() => {
    // Skip the MutationObserver entirely if we are inside the SeaTalk app
    if (!sdkLoaded || isSeaTalkApp) return

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
        setButtonReady(true)
      }
      observer.disconnect()
    }, SDK_RENDER_TIMEOUT_MS)

    return () => {
      observer.disconnect()
      window.clearTimeout(timeout)
    }
  }, [sdkLoaded, isSeaTalkApp])

  // --- INTERNAL SEATALK ONE-TAP HANDLER ---
  const handleNativeOneTap = async () => {
    try {
      // Note: Replace `window.seatalk.getAuthCode` with the exact JS bridge 
      // method provided in your SeaTalk Open Platform documentation.
      // @ts-ignore - bypassing TS error for window.seatalk injection
      if (window.seatalk && window.seatalk.getAuthCode) {
        // @ts-ignore
        const authCode = await window.seatalk.getAuthCode({ app_id: appId })
        
        // Silently send the code to your backend instead of a full page redirect
        const response = await fetch('/auth/seatalk/callback', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code: authCode, state: state })
        })

        if (response.ok) {
          // Success! Update your React context/state or reload the page
          window.location.reload()
        } else {
          console.error('Failed to authenticate with backend')
        }
      } else {
        console.warn('SeaTalk JS bridge not found on window object.')
      }
    } catch (error) {
      console.error('One-Tap login failed:', error)
    }
  }

  if (!appId || !redirectUri) {
    return null
  }

  const logoSizeMap = { small: 18, medium: 22, large: 26 }

  return (
    <Box sx={{ minHeight: 56, display: 'flex', justifyContent: align === 'center' ? 'center' : align === 'right' ? 'flex-end' : 'flex-start' }}>
      
      {/* CONDITIONAL RENDER: 
        If inside SeaTalk, show a native React button that fires the JS SDK.
        If outside, render the external seatalk containers.
      */}
      {isSeaTalkApp ? (
        <Button
          variant={theme === 'dark' ? 'contained' : 'outlined'}
          color="primary"
          size={size}
          onClick={handleNativeOneTap}
          sx={{ textTransform: 'none', fontWeight: 'bold' }}
        >
          {copywriting}
        </Button>
      ) : (
        <Box sx={{ width: '100%' }}>
          <div
            id="seatalk_login_app_info"
            data-redirect_uri={redirectUri}
            data-appid={appId}
            data-response_type="code"
            data-state={state}
          />
          <Box sx={{ position: 'relative', minHeight: 44 }}>
            <div
              id="seatalk_login_button"
              data-size={size}
              data-logo_size={logoSizeMap[size]}
              data-copywriting={copywriting}
              data-theme={theme}
              data-align={align}
            />
            {!buttonReady && (
              <Box
                sx={{
                  position: 'absolute',
                  inset: 0,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: align === 'center' ? 'center' : align === 'right' ? 'flex-end' : 'flex-start',
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
      )}
    </Box>
  )
}
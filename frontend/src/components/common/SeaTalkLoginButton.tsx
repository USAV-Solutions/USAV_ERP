import { useEffect } from 'react'
import { Box } from '@mui/material'

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

  useEffect(() => {
    // Load SeaTalk SDK script
    const script = document.createElement('script')
    script.src = 'https://static.cdn.haiserve.com/seatalk/client/shared/sop/auth.js'
    script.async = true
    document.body.appendChild(script)

    return () => {
      // Cleanup script on unmount
      document.body.removeChild(script)
    }
  }, [])

  if (!appId || !redirectUri) {
    console.error('SeaTalk configuration missing. Check VITE_SEATALK_APP_ID and VITE_SEATALK_REDIRECT_URI.')
    return null
  }

  // Generate a random state for CSRF protection
  const state = Math.random().toString(36).substring(2, 15)

  // Logo size mapping
  const logoSizeMap = {
    small: 18,
    medium: 22,
    large: 26,
  }

  return (
    <Box>
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
      />
    </Box>
  )
}

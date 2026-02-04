import { useEffect, useState, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Box, CircularProgress, Typography, Alert } from '@mui/material'
import axios from 'axios'
import { useAuth } from '../hooks/useAuth'

export default function SeaTalkCallback() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { loginWithToken } = useAuth()
  const [error, setError] = useState<string | null>(null)
  const hasExchanged = useRef(false)

  useEffect(() => {
    // Prevent multiple executions (React 18 StrictMode runs effects twice)
    if (hasExchanged.current) {
      return
    }

    const code = searchParams.get('code')
    const state = searchParams.get('state')
    const errorParam = searchParams.get('error')

    if (errorParam) {
      setError('SeaTalk login was cancelled or failed.')
      return
    }

    if (!code) {
      setError('No authorization code received from SeaTalk.')
      return
    }

    hasExchanged.current = true

    // Exchange the code for a token via our backend
    const exchangeCode = async () => {
      try {
        const response = await axios.get('/api/v1/auth/seatalk/callback', {
          params: { code, state }
        })

        const { access_token } = response.data
        
        // Use the token to log in
        await loginWithToken(access_token)
        navigate('/')
      } catch (err: any) {
        console.error('SeaTalk login error:', err)
        setError(
          err.response?.data?.detail || 
          'Failed to complete SeaTalk login. Please try again.'
        )
      }
    }

    exchangeCode()
  }, [searchParams, navigate, loginWithToken])

  if (error) {
    return (
      <Box
        sx={{
          minHeight: '100vh',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          bgcolor: 'background.default',
          p: 3,
        }}
      >
        <Alert severity="error" sx={{ mb: 2, maxWidth: 400 }}>
          {error}
        </Alert>
        <Typography
          component="a"
          href="/login"
          sx={{ color: 'primary.main', textDecoration: 'underline', cursor: 'pointer' }}
        >
          Return to Login
        </Typography>
      </Box>
    )
  }

  return (
    <Box
      sx={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        bgcolor: 'background.default',
      }}
    >
      <CircularProgress size={48} sx={{ mb: 2 }} />
      <Typography variant="h6" color="text.secondary">
        Completing SeaTalk login...
      </Typography>
    </Box>
  )
}

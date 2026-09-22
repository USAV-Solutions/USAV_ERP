import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import { ThemeProvider, CssBaseline } from '@mui/material'
import App from './App'
import { theme } from './theme'
import { AuthProvider } from './hooks/useAuth'
import { TrackingSyncProvider } from './context/TrackingSyncContext'
import TrackingSyncPanel from './components/tracking/TrackingSyncPanel'
import { FbaImportProvider } from './context/FbaImportContext'
import FbaImportPanel from './components/fba/FbaImportPanel'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000,
      retry: 1,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ThemeProvider theme={theme}>
          <CssBaseline />
          <AuthProvider>
            <TrackingSyncProvider>
              <FbaImportProvider>
                <App />
                <TrackingSyncPanel />
                <FbaImportPanel />
              </FbaImportProvider>
            </TrackingSyncProvider>
          </AuthProvider>
        </ThemeProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
)

import { useState } from 'react'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { UploadFile } from '@mui/icons-material'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { importOrdersFromApi, importOrdersFromFile } from '../../api/orders'
import type { SalesImportApiSource } from '../../types/orders'

const API_SOURCES: SalesImportApiSource[] = [
  'ECWID',
  'EBAY_MEKONG',
  'EBAY_USAV',
  'EBAY_DRAGON',
  'WALMART',
]

export default function OrderImportButton() {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<'api' | 'csv'>('api')
  const [apiSource, setApiSource] = useState<SalesImportApiSource>('ECWID')
  const [since, setSince] = useState('')
  const [until, setUntil] = useState('')
  const [csvFile, setCsvFile] = useState<File | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const apiMutation = useMutation({
    mutationFn: () =>
      importOrdersFromApi({
        source: apiSource,
        since: new Date(since).toISOString(),
        until: new Date(until).toISOString(),
      }),
    onSuccess: (data) => {
      setMessage(`Imported ${data.new_orders} orders (${data.new_items} items).`)
      queryClient.invalidateQueries({ queryKey: ['orders'] })
      queryClient.invalidateQueries({ queryKey: ['syncStatus'] })
    },
    onError: (err: { response?: { data?: { detail?: string } }; message?: string }) => {
      setError(err.response?.data?.detail || err.message || 'Import failed.')
    },
  })

  const csvMutation = useMutation({
    mutationFn: () => {
      if (!csvFile) {
        throw new Error('Please choose a CSV file.')
      }
      return importOrdersFromFile('CSV_GENERIC', csvFile)
    },
    onSuccess: (data) => {
      setMessage(
        `Imported ${data.new_orders} orders (${data.new_items} items). Rows seen: ${data.source_rows_seen}, skipped: ${data.source_rows_skipped}.`,
      )
      queryClient.invalidateQueries({ queryKey: ['orders'] })
      queryClient.invalidateQueries({ queryKey: ['syncStatus'] })
    },
    onError: (err: { response?: { data?: { detail?: string } }; message?: string }) => {
      setError(err.response?.data?.detail || err.message || 'CSV import failed.')
    },
  })

  const isLoading = apiMutation.isPending || csvMutation.isPending

  const closeDialog = () => {
    if (isLoading) return
    setOpen(false)
    setMessage(null)
    setError(null)
    setCsvFile(null)
    apiMutation.reset()
    csvMutation.reset()
  }

  const runImport = () => {
    setMessage(null)
    setError(null)
    if (mode === 'api') {
      apiMutation.mutate()
      return
    }
    csvMutation.mutate()
  }

  const canRunApi = Boolean(since && until && new Date(since) < new Date(until))
  const canRun = mode === 'api' ? canRunApi : Boolean(csvFile)

  return (
    <>
      <Button variant="contained" startIcon={<UploadFile />} onClick={() => setOpen(true)}>
        Import Orders
      </Button>
      <Dialog open={open} onClose={closeDialog} fullWidth maxWidth="sm">
        <DialogTitle>Import Sales Orders</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <FormControl fullWidth size="small">
              <InputLabel>Mode</InputLabel>
              <Select value={mode} label="Mode" onChange={(e) => setMode(e.target.value as 'api' | 'csv')}>
                <MenuItem value="api">API source</MenuItem>
                <MenuItem value="csv">CSV file</MenuItem>
              </Select>
            </FormControl>

            {mode === 'api' ? (
              <Stack spacing={2}>
                <FormControl fullWidth size="small">
                  <InputLabel>API Source</InputLabel>
                  <Select
                    value={apiSource}
                    label="API Source"
                    onChange={(e) => setApiSource(e.target.value as SalesImportApiSource)}
                  >
                    {API_SOURCES.map((source) => (
                      <MenuItem key={source} value={source}>
                        {source}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <TextField
                  type="datetime-local"
                  label="Since"
                  value={since}
                  onChange={(e) => setSince(e.target.value)}
                  InputLabelProps={{ shrink: true }}
                  fullWidth
                />
                <TextField
                  type="datetime-local"
                  label="Until"
                  value={until}
                  onChange={(e) => setUntil(e.target.value)}
                  InputLabelProps={{ shrink: true }}
                  fullWidth
                />
              </Stack>
            ) : (
              <Box>
                <Button component="label" variant="outlined">
                  Choose CSV
                  <input
                    type="file"
                    hidden
                    accept=".csv,text/csv"
                    onChange={(e) => setCsvFile(e.target.files?.[0] ?? null)}
                  />
                </Button>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  {csvFile ? csvFile.name : 'No file selected'}
                </Typography>
              </Box>
            )}

            {error && <Alert severity="error">{error}</Alert>}
            {message && <Alert severity="success">{message}</Alert>}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={closeDialog} disabled={isLoading}>
            Close
          </Button>
          <Button
            onClick={runImport}
            variant="contained"
            disabled={!canRun || isLoading}
            startIcon={isLoading ? <CircularProgress size={16} /> : undefined}
          >
            {isLoading ? 'Importing...' : 'Start Import'}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}


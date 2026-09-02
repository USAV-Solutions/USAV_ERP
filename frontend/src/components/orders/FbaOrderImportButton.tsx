/**
 * FbaOrderImportButton – replaces the plain CSV upload for the Orders → FBA tab.
 *
 * The user drops the two RAW Seller Central exports (All-Orders .txt +
 * Amazon-Fulfilled-Shipments .csv). The server merges them, scrapes missing
 * buyer names, and imports the orders — progress shows in <FbaImportPanel />.
 */
import { useEffect, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Link,
  Stack,
  Typography,
} from '@mui/material'
import { CheckCircle, OpenInNew, UploadFile } from '@mui/icons-material'
import { useQuery } from '@tanstack/react-query'

import { checkFbaAuth, getFbaPeriodHint } from '../../api/fba'
import { useFbaImport } from '../../context/FbaImportContext'
import { isFbaImportActive } from '../../types/fba'

interface DropZoneProps {
  label: string
  accept: string
  file: File | null
  onFile: (f: File | null) => void
}

function DropZone({ label, accept, file, onFile }: DropZoneProps) {
  const [over, setOver] = useState(false)
  return (
    <Box
      onDragOver={(e) => {
        e.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setOver(false)
        onFile(e.dataTransfer.files?.[0] ?? null)
      }}
      sx={{
        border: '2px dashed',
        borderColor: over ? 'primary.main' : file ? 'success.main' : 'divider',
        borderRadius: 1,
        p: 2,
        textAlign: 'center',
        bgcolor: over ? 'action.hover' : 'transparent',
        transition: 'all 0.15s',
      }}
    >
      <Typography variant="body2" sx={{ mb: 1 }}>
        {label}
      </Typography>
      <Button component="label" size="small" variant="outlined" startIcon={<UploadFile />}>
        {file ? 'Replace file' : 'Choose or drop file'}
        <input
          type="file"
          hidden
          accept={accept}
          onChange={(e) => onFile(e.target.files?.[0] ?? null)}
        />
      </Button>
      <Typography variant="caption" display="block" sx={{ mt: 0.5 }} color={file ? 'success.main' : 'text.secondary'}>
        {file ? file.name : 'No file selected'}
      </Typography>
    </Box>
  )
}

export default function FbaOrderImportButton() {
  const { job, start, openPanel, isMutating } = useFbaImport()
  const [open, setOpen] = useState(false)
  const [txtFile, setTxtFile] = useState<File | null>(null)
  const [csvFile, setCsvFile] = useState<File | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [authState, setAuthState] = useState<
    'unknown' | 'checking' | 'logged_in' | 'signed_out' | 'unverified'
  >('unknown')
  const [authDetail, setAuthDetail] = useState<string | null>(null)

  const hint = useQuery({ queryKey: ['fbaPeriodHint'], queryFn: getFbaPeriodHint, enabled: open })

  useEffect(() => {
    if (!open) {
      setTxtFile(null)
      setCsvFile(null)
      setError(null)
      setAuthState('unknown')
      setAuthDetail(null)
    }
  }, [open])

  const active = isFbaImportActive(job)

  const runAuthCheck = async () => {
    setAuthState('checking')
    setAuthDetail(null)
    try {
      const res = await checkFbaAuth()
      setAuthState(res.state)
      setAuthDetail(res.detail)
    } catch {
      setAuthState('unverified')
      setAuthDetail('Could not run the browser check.')
    }
  }

  const submit = async () => {
    setError(null)
    if (!txtFile || !csvFile) {
      setError('Both files are required.')
      return
    }
    try {
      await start({ allOrdersTxt: txtFile, fulfillmentCsv: csvFile })
      setOpen(false)
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      setError(err.response?.data?.detail || err.message || 'Import failed to start.')
    }
  }

  return (
    <>
      <Button
        variant="contained"
        startIcon={active ? <CircularProgress size={16} color="inherit" /> : <UploadFile />}
        onClick={() => (active ? openPanel() : setOpen(true))}
      >
        {active ? 'FBA import running' : 'Import Orders'}
      </Button>

      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Import FBA Orders</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Typography variant="body2" color="text.secondary">
              Download both reports from Seller Central, then drop the raw files here — the
              server merges them, fills in missing buyer names, and imports the orders.
            </Typography>

            {hint.data && (
              <Alert severity="info" icon={false}>
                <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
                  Event date range: {hint.data.option_label}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {hint.data.last_import_date
                    ? `Last FBA order imported ${new Date(hint.data.last_import_date).toLocaleDateString()} · covering ${hint.data.days_needed} day(s).`
                    : 'No prior FBA import found — use the widest range.'}
                </Typography>
              </Alert>
            )}

            {(hint.data?.reports ?? []).map((r) => (
              <Box key={r.save_as} sx={{ pl: 1, borderLeft: '3px solid', borderColor: 'divider' }}>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  {r.name}
                </Typography>
                <Typography variant="caption" display="block" color="text.secondary">
                  Open{' '}
                  <Link href={r.url} target="_blank" rel="noopener">
                    the report page <OpenInNew sx={{ fontSize: 12, verticalAlign: 'middle' }} />
                  </Link>{' '}
                  → pick <strong>{hint.data?.option_label}</strong> → click{' '}
                  <strong>“{r.button}”</strong> → download as {r.file_format}.
                </Typography>
              </Box>
            ))}

            <DropZone
              label="1 · All Orders report (.txt, tab-delimited)"
              accept=".txt,text/plain"
              file={txtFile}
              onFile={setTxtFile}
            />
            <DropZone
              label="2 · Amazon Fulfilled Shipments report (.csv)"
              accept=".csv,text/csv"
              file={csvFile}
              onFile={setCsvFile}
            />

            <Stack direction="row" spacing={1} alignItems="center">
              <Button size="small" onClick={runAuthCheck} disabled={authState === 'checking'}>
                {authState === 'checking' ? 'Checking login…' : 'Check Seller Central login'}
              </Button>
              {authState === 'logged_in' && (
                <Chip size="small" color="success" icon={<CheckCircle />} label="Logged in" />
              )}
              {authState === 'signed_out' && (
                <Chip size="small" color="warning" label="Signed out — refresh the profile" />
              )}
              {authState === 'unverified' && (
                <Chip size="small" color="default" label="Couldn’t verify" />
              )}
            </Stack>
            {(authState === 'signed_out' || authState === 'unverified') && authDetail && (
              <Alert severity={authState === 'signed_out' ? 'warning' : 'info'}>
                {authDetail}
                {authState === 'signed_out' && (
                  <>
                    {' '}You can still import now — orders arrive without buyer names.
                  </>
                )}
              </Alert>
            )}

            {error && <Alert severity="error">{error}</Alert>}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={submit}
            disabled={!txtFile || !csvFile || isMutating}
            startIcon={isMutating ? <CircularProgress size={16} /> : undefined}
          >
            {isMutating ? 'Starting…' : 'Start Import'}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}

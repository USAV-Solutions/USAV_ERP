/**
 * FbaImportPanel – the background monitor for the server-side FBA import.
 *
 * Right-side drawer. The job runs on the server, so closing this panel does not
 * stop it — reopen any time from the navbar chip (<GlobalFbaImportChip />).
 */
import { useMemo, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Drawer,
  IconButton,
  LinearProgress,
  Stack,
  Step,
  StepLabel,
  Stepper,
  Tooltip,
  Typography,
} from '@mui/material'
import { Close, Stop } from '@mui/icons-material'
import { DataGrid, type GridColDef } from '@mui/x-data-grid'

import { useFbaImport } from '../../context/FbaImportContext'
import { isFbaImportActive, type BuyerNameItem, type FbaImportStatus } from '../../types/fba'
import FbaImportResultChip from './FbaImportResultChip'

const DRAWER_WIDTH = 560
const PHASES = ['parsing', 'scraping', 'ingesting', 'done'] as const
const PHASE_STEP_LABEL: Record<string, string> = {
  parsing: 'Merge reports',
  scraping: 'Buyer names',
  ingesting: 'Import orders',
  done: 'Done',
}

const STATUS_LABEL: Record<FbaImportStatus, string> = {
  idle: 'No job',
  running: 'Running…',
  completed: 'Completed',
  completed_with_warnings: 'Completed with warnings',
  aborted: 'Aborted',
  failed: 'Failed',
}
const STATUS_COLOR: Record<FbaImportStatus, 'default' | 'info' | 'warning' | 'success' | 'error'> = {
  idle: 'default',
  running: 'info',
  completed: 'success',
  completed_with_warnings: 'warning',
  aborted: 'default',
  failed: 'error',
}

const columns: GridColDef<BuyerNameItem>[] = [
  { field: 'order_id', headerName: 'Amazon order', flex: 1, minWidth: 170 },
  {
    field: 'result',
    headerName: 'Result',
    width: 130,
    sortable: false,
    renderCell: (params) => <FbaImportResultChip result={params.value} />,
  },
  { field: 'buyer_name', headerName: 'Buyer name', flex: 1, minWidth: 140 },
  {
    field: 'detail',
    headerName: 'Detail',
    flex: 1.2,
    minWidth: 160,
    sortable: false,
    renderCell: (params) => (
      <Tooltip title={params.value || ''}>
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {params.value || '—'}
        </span>
      </Tooltip>
    ),
  },
]

function CountChip({ label, value, color }: { label: string; value: number; color?: 'success' | 'warning' | 'error' | 'default' }) {
  if (!value) return null
  return <Chip size="small" color={color} variant="outlined" label={`${label}: ${value}`} />
}

export default function FbaImportPanel() {
  const { job, panelOpen, closePanel, abort, isMutating } = useFbaImport()
  const [confirmAbort, setConfirmAbort] = useState(false)

  const rows = useMemo(
    () => (job?.items ?? []).map((it) => ({ ...it, id: it.order_id })),
    [job?.items],
  )

  const status = job?.status ?? 'idle'
  const active = isFbaImportActive(job)
  const activeStep = job?.phase ? PHASES.indexOf(job.phase as (typeof PHASES)[number]) : 0
  const scrapePct =
    job && job.total_names > 0 ? Math.round((job.scraped_names / job.total_names) * 100) : 0
  const c = job?.counts ?? {}

  return (
    <>
      <Drawer
        anchor="right"
        open={panelOpen}
        onClose={closePanel}
        sx={{ '& .MuiDrawer-paper': { width: { xs: '100%', sm: DRAWER_WIDTH }, p: 2 } }}
      >
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            FBA Import
          </Typography>
          <Chip size="small" label={STATUS_LABEL[status]} color={STATUS_COLOR[status]} />
          <IconButton onClick={closePanel} size="small" aria-label="Close">
            <Close />
          </IconButton>
        </Stack>

        {!job || status === 'idle' ? (
          <Typography variant="body2" color="text.secondary">
            No FBA import has been run yet. Start one from the “Import Orders” button on the
            Orders → FBA tab.
          </Typography>
        ) : (
          <>
            <Stepper activeStep={activeStep} alternativeLabel sx={{ my: 2 }}>
              {PHASES.map((p) => (
                <Step key={p} completed={activeStep > PHASES.indexOf(p) || status.startsWith('completed')}>
                  <StepLabel>{PHASE_STEP_LABEL[p]}</StepLabel>
                </Step>
              ))}
            </Stepper>

            {job.phase === 'scraping' && job.total_names > 0 && (
              <>
                <Typography variant="body2" color="text.secondary">
                  Buyer names {job.scraped_names} / {job.total_names} ({scrapePct}%)
                </Typography>
                <LinearProgress
                  variant={active ? 'determinate' : 'determinate'}
                  value={scrapePct}
                  sx={{ my: 1, height: 8, borderRadius: 1 }}
                />
              </>
            )}
            {active && job.phase !== 'scraping' && (
              <LinearProgress sx={{ my: 1, height: 8, borderRadius: 1 }} />
            )}

            <Stack direction="row" spacing={2} sx={{ my: 1 }} flexWrap="wrap" useFlexGap>
              <Typography variant="body2">
                <strong>{job.fba_order_rows}</strong> FBA order rows · <strong>{job.merged_rows}</strong> merged lines
              </Typography>
              <Typography variant="body2">
                <strong>{job.orders_created}</strong> new orders · <strong>{job.items_created}</strong> new lines
              </Typography>
            </Stack>

            <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
              <CountChip label="Names found" value={c.FOUND ?? 0} color="success" />
              <CountChip label="Not on page" value={c.NOT_FOUND ?? 0} />
              <CountChip label="Errors" value={c.ERROR ?? 0} color="error" />
              <CountChip label="Login expired" value={c.AUTH_EXPIRED ?? 0} color="warning" />
              <CountChip label="Skipped" value={c.SKIPPED ?? 0} />
            </Stack>

            {job.message && (
              <Typography variant="body2" sx={{ mb: 1 }}>
                {job.message}
              </Typography>
            )}
            {job.warnings.map((w, i) => (
              <Alert key={i} severity="warning" sx={{ mb: 1 }}>
                {w}
              </Alert>
            ))}
            {job.last_error && status === 'failed' && (
              <Alert severity="error" sx={{ mb: 1 }}>
                {job.last_error}
              </Alert>
            )}

            {job.items.length > 0 && (
              <Box sx={{ height: 360, mb: 1 }}>
                <DataGrid
                  rows={rows}
                  columns={columns}
                  density="compact"
                  disableRowSelectionOnClick
                  pageSizeOptions={[25, 50, 100]}
                  initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
                />
              </Box>
            )}

            <Stack direction="row" spacing={1} alignItems="center">
              {job.cancel_requested && active && (
                <Typography variant="caption" color="text.secondary">
                  <CircularProgress size={12} sx={{ mr: 0.5 }} />
                  Aborting…
                </Typography>
              )}
              <Box sx={{ flexGrow: 1 }} />
              {active && (
                <Button
                  color="error"
                  variant="outlined"
                  startIcon={<Stop />}
                  disabled={isMutating || job.cancel_requested}
                  onClick={() => setConfirmAbort(true)}
                >
                  Abort
                </Button>
              )}
              <Button onClick={closePanel}>{active ? 'Close (keeps running)' : 'Close'}</Button>
            </Stack>
          </>
        )}
      </Drawer>

      <Dialog open={confirmAbort} onClose={() => setConfirmAbort(false)}>
        <DialogTitle>Abort FBA import?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Stops before orders are written unless ingestion has already started. Re-run the
            import with the same files — already-imported orders are updated in place, not
            duplicated.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmAbort(false)}>Keep running</Button>
          <Button
            color="error"
            disabled={isMutating}
            onClick={async () => {
              await abort()
              setConfirmAbort(false)
            }}
          >
            Abort
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}

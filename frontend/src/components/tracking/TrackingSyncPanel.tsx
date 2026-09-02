/**
 * TrackingSyncPanel – the background job monitor.
 *
 * A right-side drawer. The job runs on the server, so closing this panel does not
 * stop it — reopen any time from the navbar chip (<GlobalTrackingChip />).
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
  Link,
  Stack,
  Tooltip,
  Typography,
} from '@mui/material'
import { Close, OpenInNew, Stop } from '@mui/icons-material'
import { DataGrid, type GridColDef } from '@mui/x-data-grid'

import { useTrackingSync } from '../../context/TrackingSyncContext'
import { isTrackingJobActive, type TrackingItem, type TrackingJobStatus } from '../../types/tracking'
import TrackingResultChip from './TrackingResultChip'
import TrackingCooldownBanner from './TrackingCooldownBanner'

const DRAWER_WIDTH = 560

const STATUS_LABEL: Record<TrackingJobStatus, string> = {
  idle: 'No job',
  running: 'Checking…',
  paused_rate_limit: 'Paused — rate limited',
  completed: 'Completed',
  aborted: 'Aborted',
  failed: 'Failed',
}

const STATUS_COLOR: Record<TrackingJobStatus, 'default' | 'info' | 'warning' | 'success' | 'error'> = {
  idle: 'default',
  running: 'info',
  paused_rate_limit: 'warning',
  completed: 'success',
  aborted: 'default',
  failed: 'error',
}

const columns: GridColDef<TrackingItem>[] = [
  { field: 'order_number', headerName: 'Order #', flex: 1, minWidth: 130 },
  {
    field: 'tracking_number',
    headerName: 'Tracking',
    flex: 1.2,
    minWidth: 170,
    renderCell: (params) => (
      <Link
        href={params.row.parcelsapp_url}
        target="_blank"
        rel="noopener"
        sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}
        onClick={(e) => e.stopPropagation()}
      >
        {params.value}
        <OpenInNew sx={{ fontSize: 14 }} />
      </Link>
    ),
  },
  {
    field: 'result',
    headerName: 'Result',
    width: 130,
    sortable: false,
    renderCell: (params) => <TrackingResultChip result={params.value} />,
  },
  {
    field: 'detail',
    headerName: 'Detail',
    flex: 1.4,
    minWidth: 180,
    sortable: false,
    renderCell: (params) => (
      <Tooltip title={params.value || ''}>
        <span
          style={{
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            color: 'var(--mui-palette-text-secondary, #666)',
          }}
        >
          {params.value || '—'}
        </span>
      </Tooltip>
    ),
  },
  {
    field: 'checked_at',
    headerName: 'Checked',
    width: 130,
    sortable: false,
    renderCell: (params) =>
      params.value ? new Date(params.value as string).toLocaleTimeString() : '—',
  },
]

function CountChip({ label, value, color }: { label: string; value: number; color?: 'success' | 'info' | 'warning' | 'error' | 'default' }) {
  if (!value) return null
  return <Chip size="small" color={color} variant="outlined" label={`${label}: ${value}`} />
}

export default function TrackingSyncPanel() {
  const { job, panelOpen, closePanel, abort, isMutating } = useTrackingSync()
  const [confirmAbort, setConfirmAbort] = useState(false)

  const rows = useMemo(
    () => (job?.items ?? []).map((it, i) => ({ ...it, id: `${it.tracking_number}-${i}` })),
    [job?.items],
  )

  const status = job?.status ?? 'idle'
  const active = isTrackingJobActive(job)
  const pct = job && job.total > 0 ? Math.round((job.processed / job.total) * 100) : 0
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
            Tracking Sync
          </Typography>
          <Chip size="small" label={STATUS_LABEL[status]} color={STATUS_COLOR[status]} />
          <IconButton onClick={closePanel} size="small" aria-label="Close">
            <Close />
          </IconButton>
        </Stack>

        {!job || status === 'idle' ? (
          <Typography variant="body2" color="text.secondary">
            No tracking sync has been run yet. Start one with the
            “Check Tracking” button on the Orders page.
          </Typography>
        ) : (
          <>
            <Typography variant="body2" color="text.secondary">
              {job.processed} / {job.total} orders checked ({pct}%)
            </Typography>
            <LinearProgress
              variant={active && job.total === 0 ? 'indeterminate' : 'determinate'}
              value={pct}
              sx={{ my: 1, height: 8, borderRadius: 1 }}
            />

            <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
              <CountChip label="Delivered" value={c.DELIVERED ?? 0} color="success" />
              <CountChip label="In transit" value={c.SHIPPING ?? 0} color="info" />
              <CountChip label="Label created" value={c.PENDING ?? 0} />
              <CountChip label="Not found" value={c.NOT_FOUND ?? 0} color="warning" />
              <CountChip label="Unknown" value={c.UNKNOWN ?? 0} color="warning" />
              <CountChip label="Errors" value={c.ERROR ?? 0} color="error" />
              <CountChip label="Skipped" value={c.SKIPPED_TBA ?? 0} />
            </Stack>

            {job.current && (
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                Now checking: {job.current.order_number} · {job.current.tracking_number}
              </Typography>
            )}
            {job.message && (
              <Typography variant="body2" sx={{ mb: 1 }}>
                {job.message}
              </Typography>
            )}
            {job.last_error && status !== 'running' && (
              <Alert severity={status === 'failed' ? 'error' : 'warning'} sx={{ mb: 1 }}>
                Last problem: {job.last_error}
              </Alert>
            )}

            <TrackingCooldownBanner />

            <Box sx={{ height: 380, mb: 1 }}>
              <DataGrid
                rows={rows}
                columns={columns}
                density="compact"
                disableRowSelectionOnClick
                pageSizeOptions={[25, 50, 100]}
                initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
              />
            </Box>

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
              <Button onClick={closePanel}>
                {active ? 'Close (keeps running)' : 'Close'}
              </Button>
            </Stack>
          </>
        )}
      </Drawer>

      <Dialog open={confirmAbort} onClose={() => setConfirmAbort(false)}>
        <DialogTitle>Abort tracking sync?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            The scraper stops immediately. Orders already checked keep their new
            status — the rest stay unchanged and are picked up next run.
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

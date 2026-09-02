/**
 * GlobalTrackingChip – navbar indicator for a running/paused tracking sync.
 *
 * Visible on every route while a job is active (or just finished). Click to
 * reopen the monitor panel.
 */
import { Chip, CircularProgress } from '@mui/material'
import { LocalShipping, Warning } from '@mui/icons-material'

import { useTrackingSync } from '../../context/TrackingSyncContext'
import { isTrackingJobActive } from '../../types/tracking'

export default function GlobalTrackingChip() {
  const { job, openPanel } = useTrackingSync()
  if (!job || job.status === 'idle') return null

  const active = isTrackingJobActive(job)
  // Show a terminal job only briefly, then let the chip fade out.
  const finishedRecently =
    (job.status === 'completed' || job.status === 'failed') &&
    !!job.finished_at &&
    Date.now() - new Date(job.finished_at).getTime() < 5 * 60 * 1000
  if (!active && !finishedRecently) return null

  const progress = job.total > 0 ? `${job.processed}/${job.total}` : ''

  if (job.status === 'paused_rate_limit') {
    return (
      <Chip
        icon={<Warning />}
        color="warning"
        variant="filled"
        size="small"
        onClick={openPanel}
        label={`Tracking paused ${progress}`}
        sx={{ mr: 1, color: 'inherit' }}
      />
    )
  }

  if (job.status === 'running') {
    return (
      <Chip
        icon={<CircularProgress size={14} color="inherit" />}
        color="info"
        variant="filled"
        size="small"
        onClick={openPanel}
        label={`Tracking ${progress}`}
        sx={{ mr: 1, color: 'inherit' }}
      />
    )
  }

  return (
    <Chip
      icon={<LocalShipping />}
      color={job.status === 'failed' ? 'error' : 'success'}
      variant="outlined"
      size="small"
      onClick={openPanel}
      label={job.status === 'failed' ? 'Tracking failed' : `Tracking done ${progress}`}
      sx={{ mr: 1, color: 'inherit', borderColor: 'currentColor' }}
    />
  )
}

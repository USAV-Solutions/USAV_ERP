/**
 * TrackingSyncButton – toolbar trigger for the parcelsapp tracking check.
 *
 * Idle / finished  → "Check Tracking (N)"  → confirm → start job + open monitor
 * Running / paused  → "Tracking n/m" / "Tracking paused"  → open monitor
 *
 * The job runs on the server; this button and <GlobalTrackingChip /> both just
 * open the shared <TrackingSyncPanel />.
 */
import { useState } from 'react'
import {
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
} from '@mui/material'
import { LocalShipping } from '@mui/icons-material'

import { useTrackingSync } from '../../context/TrackingSyncContext'
import { useTrackingEligibleCount } from '../../hooks/useTrackingEligibleCount'
import { isTrackingJobActive } from '../../types/tracking'

export default function TrackingSyncButton() {
  const { job, openPanel, start, isMutating } = useTrackingSync()
  const { count } = useTrackingEligibleCount(true)
  const [confirmOpen, setConfirmOpen] = useState(false)

  const active = isTrackingJobActive(job)

  const label = (() => {
    if (job?.status === 'running') {
      return `Tracking ${job.processed}/${job.total}`
    }
    if (job?.status === 'paused_rate_limit') {
      return 'Tracking paused'
    }
    return `Check Tracking${count != null ? ` (${count})` : ''}`
  })()

  const handleClick = () => {
    if (active) {
      openPanel()
    } else {
      setConfirmOpen(true)
    }
  }

  const handleStart = async () => {
    setConfirmOpen(false)
    try {
      await start()
    } catch {
      openPanel() // 409 (already running) etc. — just show the monitor
    }
  }

  return (
    <>
      <Button
        variant="outlined"
        color={job?.status === 'paused_rate_limit' ? 'warning' : 'primary'}
        startIcon={
          job?.status === 'running' ? <CircularProgress size={16} /> : <LocalShipping />
        }
        onClick={handleClick}
        disabled={isMutating}
      >
        {label}
      </Button>

      <Dialog open={confirmOpen} onClose={() => setConfirmOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Check tracking statuses?</DialogTitle>
        <DialogContent>
          <DialogContentText component="div">
            Checks {count ?? 'all'} pending self-fulfilled orders against
            parcelsapp and updates their shipping status.
            <br />
            <br />
            Runs in the background — you can close the monitor and keep working.
            parcelsapp rate-limits after roughly 50 checks; the job pauses and
            offers a retry probe when that happens.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleStart} disabled={isMutating}>
            Start check
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}

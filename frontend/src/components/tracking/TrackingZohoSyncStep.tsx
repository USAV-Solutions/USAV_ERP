/**
 * TrackingZohoSyncStep – the final step of the tracking check.
 *
 * After the scrape finishes, this pushes the orders whose shipping status
 * actually changed to Zoho (they were marked DIRTY by the scraper). Same
 * queue-and-poll flow as the Orders page "Range Sync", via useOrderZohoSync.
 */
import { useEffect, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Collapse,
  LinearProgress,
  Link,
  Paper,
  Stack,
  Typography,
} from '@mui/material'
import { CloudSync, CheckCircle } from '@mui/icons-material'

import { useOrderZohoSync } from '../../hooks/useOrderZohoSync'

interface Props {
  orderIds: number[]
  /** true once the scrape job has stopped (completed / aborted / failed). */
  jobFinished: boolean
}

export default function TrackingZohoSyncStep({ orderIds, jobFinished }: Props) {
  const { phase, progress, failures, error, run, reset, isRunning } = useOrderZohoSync()
  const [showFailures, setShowFailures] = useState(false)

  // A new run of the scrape → forget the previous Zoho-sync result.
  useEffect(() => {
    if (!jobFinished) reset()
  }, [jobFinished, reset])

  if (!jobFinished || orderIds.length === 0) return null

  const done = phase === 'done'
  const pct =
    progress.total > 0
      ? Math.round(((progress.synced + (done ? progress.failed : 0)) / progress.total) * 100)
      : 0

  return (
    <Paper variant="outlined" sx={{ p: 1.5, mb: 2, borderColor: 'primary.light' }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
        <Typography variant="subtitle2" sx={{ flexGrow: 1 }}>
          Final step — sync {orderIds.length} fulfillment update
          {orderIds.length === 1 ? '' : 's'} to Zoho
        </Typography>
        {phase === 'idle' && (
          <Button
            size="small"
            variant="contained"
            startIcon={<CloudSync />}
            onClick={() => run(orderIds)}
          >
            Sync to Zoho
          </Button>
        )}
        {isRunning && (
          <Typography variant="caption" color="text.secondary">
            <CircularProgress size={12} sx={{ mr: 0.5 }} />
            {phase === 'queueing' ? 'Queueing…' : 'Syncing…'}
          </Typography>
        )}
        {done && !error && (
          <Button size="small" onClick={() => run(orderIds)}>
            Re-sync
          </Button>
        )}
      </Stack>

      {phase === 'idle' && (
        <Typography variant="caption" color="text.secondary">
          These orders had their shipping status changed by the check and are
          marked dirty for Zoho.
        </Typography>
      )}

      {(isRunning || done) && (
        <>
          <LinearProgress
            variant={isRunning && progress.total === 0 ? 'indeterminate' : 'determinate'}
            value={pct}
            sx={{ my: 1, height: 6, borderRadius: 1 }}
          />
          <Typography variant="caption" color="text.secondary">
            {progress.synced} synced
            {progress.pending + progress.syncing > 0 &&
              ` · ${progress.pending + progress.syncing} in progress`}
            {progress.failed > 0 && ` · ${progress.failed} failed`}
          </Typography>
        </>
      )}

      {done && !error && progress.failed === 0 && (
        <Alert
          icon={<CheckCircle fontSize="inherit" />}
          severity="success"
          sx={{ mt: 1, py: 0 }}
        >
          {progress.synced} order{progress.synced === 1 ? '' : 's'} synced to Zoho.
        </Alert>
      )}
      {error && (
        <Alert severity="warning" sx={{ mt: 1, py: 0 }}>
          {error}
        </Alert>
      )}
      {failures.length > 0 && (
        <Box sx={{ mt: 1 }}>
          <Link
            component="button"
            variant="caption"
            onClick={() => setShowFailures((v) => !v)}
          >
            {showFailures ? 'Hide' : 'Show'} {failures.length} failure
            {failures.length === 1 ? '' : 's'}
          </Link>
          <Collapse in={showFailures}>
            <Box
              component="ul"
              sx={{ m: 0, pl: 2, maxHeight: 120, overflowY: 'auto', fontSize: '0.75rem' }}
            >
              {failures.map((f, i) => (
                <li key={i}>{f}</li>
              ))}
            </Box>
          </Collapse>
        </Box>
      )}
    </Paper>
  )
}

/**
 * TrackingCooldownBanner – shown while a job is paused on a parcelsapp rate limit.
 *
 * The countdown is advisory only. Resume unlocks solely on a successful probe
 * (last_probe_result === 'OK'); the timer never enables it.
 */
import { useEffect, useState } from 'react'
import {
  Alert,
  AlertTitle,
  Box,
  Button,
  CircularProgress,
  FormControlLabel,
  Stack,
  Switch,
  Typography,
} from '@mui/material'
import { Search, PlayArrow } from '@mui/icons-material'

import { useTrackingSync } from '../../context/TrackingSyncContext'

function useCountdown(target: string | null): string | null {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!target) return
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [target])
  if (!target) return null
  const ms = new Date(target).getTime() - now
  if (ms <= 0) return null
  const total = Math.floor(ms / 1000)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`
}

export default function TrackingCooldownBanner() {
  const { job, probe, resume, toggleAutoProbe, isMutating } = useTrackingSync()
  const countdown = useCountdown(job?.cooldown_until ?? null)

  if (!job || job.status !== 'paused_rate_limit') return null

  const probeCleared = job.last_probe_result === 'OK'
  const probedAndBlocked =
    job.last_probe_result === 'RATE_LIMITED' || job.last_probe_result === 'ERROR'

  return (
    <Alert severity="warning" icon={false} sx={{ mb: 2 }}>
      <AlertTitle>
        Rate limit reached — {job.processed} / {job.total} checked
      </AlertTitle>

      <Typography variant="body2" sx={{ mb: 1 }}>
        parcelsapp is throttling this server. Progress is saved. The cooldown
        length is unknown{countdown ? `; earliest suggested retry ~${countdown} (advisory)` : '.'}
      </Typography>

      {probedAndBlocked && (
        <Typography variant="body2" color="error" sx={{ mb: 1 }}>
          Last probe: still throttled — waiting longer before the next attempt.
        </Typography>
      )}
      {probeCleared && (
        <Typography variant="body2" color="success.main" sx={{ mb: 1 }}>
          Probe cleared — safe to resume.
        </Typography>
      )}

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems={{ sm: 'center' }}>
        <Button
          size="small"
          variant="outlined"
          startIcon={isMutating ? <CircularProgress size={16} /> : <Search />}
          disabled={isMutating}
          onClick={() => probe()}
        >
          Probe 1 order
        </Button>
        <Button
          size="small"
          variant="contained"
          startIcon={<PlayArrow />}
          disabled={!probeCleared || isMutating}
          onClick={() => resume()}
        >
          Resume ({job.remaining})
        </Button>
        <Box sx={{ flexGrow: 1 }} />
        <FormControlLabel
          control={
            <Switch
              size="small"
              checked={job.auto_probe}
              disabled={isMutating}
              onChange={(e) => toggleAutoProbe(e.target.checked)}
            />
          }
          label={
            <Typography variant="body2">
              Auto-probe every {job.auto_probe_interval_minutes} min
            </Typography>
          }
        />
      </Stack>
      {!probeCleared && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
          Resume unlocks only after a probe succeeds — not when the timer ends.
        </Typography>
      )}
    </Alert>
  )
}

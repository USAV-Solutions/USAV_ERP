/**
 * GlobalFbaImportChip – navbar indicator for a running/just-finished FBA import.
 * Click to reopen the monitor panel from any route.
 */
import { Chip, CircularProgress } from '@mui/material'
import { Inventory2, Warning } from '@mui/icons-material'

import { useFbaImport } from '../../context/FbaImportContext'
import { isFbaImportActive } from '../../types/fba'

const PHASE_LABEL: Record<string, string> = {
  parsing: 'merging',
  scraping: 'buyer names',
  ingesting: 'importing',
  done: 'done',
}

export default function GlobalFbaImportChip() {
  const { job, openPanel } = useFbaImport()
  if (!job || job.status === 'idle') return null

  const active = isFbaImportActive(job)
  const finishedRecently =
    !active &&
    !!job.finished_at &&
    Date.now() - new Date(job.finished_at).getTime() < 5 * 60 * 1000
  if (!active && !finishedRecently) return null

  if (active) {
    const phase = job.phase ? PHASE_LABEL[job.phase] ?? job.phase : ''
    const progress =
      job.phase === 'scraping' && job.total_names > 0
        ? ` ${job.scraped_names}/${job.total_names}`
        : ''
    return (
      <Chip
        icon={<CircularProgress size={14} color="inherit" />}
        color="info"
        variant="filled"
        size="small"
        onClick={openPanel}
        label={`FBA import — ${phase}${progress}`}
        sx={{ mr: 1, color: 'inherit' }}
      />
    )
  }

  if (job.status === 'failed') {
    return (
      <Chip
        icon={<Warning />}
        color="error"
        variant="outlined"
        size="small"
        onClick={openPanel}
        label="FBA import failed"
        sx={{ mr: 1, color: 'inherit', borderColor: 'currentColor' }}
      />
    )
  }

  return (
    <Chip
      icon={<Inventory2 />}
      color={job.status === 'completed_with_warnings' ? 'warning' : 'success'}
      variant="outlined"
      size="small"
      onClick={openPanel}
      label={
        job.status === 'completed_with_warnings'
          ? `FBA import — done with warnings`
          : `FBA import — ${job.orders_created} new`
      }
      sx={{ mr: 1, color: 'inherit', borderColor: 'currentColor' }}
    />
  )
}

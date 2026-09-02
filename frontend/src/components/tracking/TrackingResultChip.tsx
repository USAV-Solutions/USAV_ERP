/**
 * TrackingResultChip – renders a single scraped tracking result.
 * Mirrors the ZohoSyncStatusChip pattern for visual consistency.
 */
import { Chip, type ChipProps } from '@mui/material'
import type { TrackingItemResult } from '../../types/tracking'

const COLOR_MAP: Record<string, ChipProps['color']> = {
  DELIVERED: 'success',
  SHIPPING: 'info',
  PENDING: 'default',
  NOT_FOUND: 'warning',
  UNKNOWN: 'warning',
  ERROR: 'error',
  RATE_LIMITED: 'error',
  SKIPPED_TBA: 'default',
}

const LABEL_MAP: Record<string, string> = {
  DELIVERED: 'Delivered',
  SHIPPING: 'In transit',
  PENDING: 'Label created',
  NOT_FOUND: 'Not found',
  UNKNOWN: 'Unknown',
  ERROR: 'Error',
  RATE_LIMITED: 'Rate limited',
  SKIPPED_TBA: 'Skipped (TBA)',
}

export interface TrackingResultChipProps extends Omit<ChipProps, 'color' | 'label'> {
  result?: TrackingItemResult | null
}

export default function TrackingResultChip({
  result,
  size = 'small',
  ...props
}: TrackingResultChipProps) {
  if (!result) {
    return <Chip label="Queued" size={size} color="default" variant="outlined" {...props} />
  }
  return (
    <Chip
      label={LABEL_MAP[result] ?? result}
      size={size}
      color={COLOR_MAP[result] ?? 'default'}
      {...props}
    />
  )
}

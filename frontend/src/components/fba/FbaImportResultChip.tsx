/**
 * FbaImportResultChip – renders a single buyer-name lookup result.
 */
import { Chip, type ChipProps } from '@mui/material'
import type { BuyerNameResult } from '../../types/fba'

const COLOR_MAP: Record<string, ChipProps['color']> = {
  FOUND: 'success',
  NOT_FOUND: 'default',
  ERROR: 'error',
  SKIPPED: 'default',
  AUTH_EXPIRED: 'warning',
}

const LABEL_MAP: Record<string, string> = {
  FOUND: 'Name found',
  NOT_FOUND: 'Not on page',
  ERROR: 'Error',
  SKIPPED: 'Skipped',
  AUTH_EXPIRED: 'Login expired',
}

export interface FbaImportResultChipProps extends Omit<ChipProps, 'color' | 'label'> {
  result?: BuyerNameResult | null
}

export default function FbaImportResultChip({
  result,
  size = 'small',
  ...props
}: FbaImportResultChipProps) {
  if (!result) {
    return <Chip label="Queued" size={size} color="default" variant="outlined" {...props} />
  }
  return (
    <Chip
      label={LABEL_MAP[result] ?? result}
      size={size}
      color={COLOR_MAP[result] ?? 'default'}
      variant={result === 'FOUND' ? 'filled' : 'outlined'}
      {...props}
    />
  )
}

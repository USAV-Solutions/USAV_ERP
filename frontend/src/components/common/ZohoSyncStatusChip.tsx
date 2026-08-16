import { Chip, type ChipProps } from '@mui/material'

export type ZohoSyncStatusValue =
  | 'PENDING'
  | 'QUEUED'
  | 'SYNCING'
  | 'DIRTY'
  | 'SYNCED'
  | 'ERROR'
  | 'ALREADY_SYNCED'
  | string

const ZOHO_SYNC_COLOR_MAP: Record<string, ChipProps['color']> = {
  DIRTY: 'info',
  SYNCED: 'success',
  ALREADY_SYNCED: 'success',
  ERROR: 'error',
  PENDING: 'warning',
  QUEUED: 'warning',
  SYNCING: 'warning',
}

export interface ZohoSyncStatusChipProps extends Omit<ChipProps, 'color' | 'label'> {
  status?: ZohoSyncStatusValue | null
  label?: string
}

export function ZohoSyncStatusChip({
  status,
  label,
  size = 'small',
  ...props
}: ZohoSyncStatusChipProps) {
  if (!status) {
    return <Chip label="-" size={size} color="default" {...props} />
  }

  const color = ZOHO_SYNC_COLOR_MAP[status] || 'default'
  const displayLabel = label || status.replace(/_/g, ' ')

  return <Chip label={displayLabel} size={size} color={color} {...props} />
}

export default ZohoSyncStatusChip

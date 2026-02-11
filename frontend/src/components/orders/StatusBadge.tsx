/**
 * StatusBadge – coloured Chip for OrderStatus and OrderItemStatus values.
 */
import { Chip, type ChipProps } from '@mui/material'
import type { OrderStatus, OrderItemStatus } from '../../types/orders'

// ── Order Status config ──────────────────────────────────────────────

const ORDER_STATUS_CFG: Record<OrderStatus, { label: string; color: ChipProps['color'] }> = {
  PENDING:       { label: 'Pending',       color: 'warning' },
  PROCESSING:    { label: 'Processing',    color: 'primary' },
  READY_TO_SHIP: { label: 'Ready to Ship', color: 'info' },
  SHIPPED:       { label: 'Shipped',       color: 'success' },
  DELIVERED:     { label: 'Delivered',      color: 'success' },
  CANCELLED:     { label: 'Cancelled',     color: 'default' },
  REFUNDED:      { label: 'Refunded',      color: 'default' },
  ON_HOLD:       { label: 'On Hold',       color: 'warning' },
  ERROR:         { label: 'Error',         color: 'error' },
}

// ── Item Status config ───────────────────────────────────────────────

const ITEM_STATUS_CFG: Record<OrderItemStatus, { label: string; color: ChipProps['color'] }> = {
  UNMATCHED: { label: 'Unmatched', color: 'error' },
  MATCHED:   { label: 'Matched',   color: 'info' },
  ALLOCATED: { label: 'Allocated', color: 'primary' },
  SHIPPED:   { label: 'Shipped',   color: 'success' },
  CANCELLED: { label: 'Cancelled', color: 'default' },
}

// ── Component ────────────────────────────────────────────────────────

interface StatusBadgeProps {
  status: OrderStatus | OrderItemStatus
  size?: 'small' | 'medium'
  /** If true, renders item-level config instead of order-level */
  itemLevel?: boolean
}

export default function StatusBadge({ status, size = 'small', itemLevel = false }: StatusBadgeProps) {
  const cfg = itemLevel
    ? (ITEM_STATUS_CFG as Record<string, { label: string; color: ChipProps['color'] }>)[status]
    : (ORDER_STATUS_CFG as Record<string, { label: string; color: ChipProps['color'] }>)[status]

  if (!cfg) {
    return <Chip label={status} size={size} />
  }

  return (
    <Chip
      label={cfg.label}
      color={cfg.color}
      size={size}
      variant="filled"
    />
  )
}

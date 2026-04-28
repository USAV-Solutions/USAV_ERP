/**
 * OrderItemsPanel – Inline expandable panel showing order line items.
 *
 * Renders inside a collapsed table row. For each item shows name, SKU,
 * quantity, price, status, linked variant SKU, and action buttons.
 *
 * Match action uses an Autocomplete that searches variants by product
 * name or SKU via GET /variants/search?q=...
 */
import { useState, type MouseEvent, type ReactNode } from 'react'
import {
  Box,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  IconButton,
  Tooltip,
  CircularProgress,
  Alert,
  Chip,
  Stack,
  Button,
} from '@mui/material'
import {
  LinkOff,
  Link as LinkIcon,
  CheckCircle,
} from '@mui/icons-material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  getOrder,
  matchItem,
  confirmItem,
  rejectItem,
} from '../../api/orders'
import VariantSearchAutocomplete from '../common/VariantSearchAutocomplete'
import StatusBadge from './StatusBadge'
import type {
  OrderDetail,
  OrderItemDetail,
  VariantSearchResult,
} from '../../types/orders'

// ── Props ────────────────────────────────────────────────────────────

interface OrderItemsPanelProps {
  orderId: number
  headerAction?: ReactNode
}

export default function OrderItemsPanel({ orderId, headerAction }: OrderItemsPanelProps) {
  const queryClient = useQueryClient()

  const { data: order, isLoading, error } = useQuery<OrderDetail>({
    queryKey: ['order', orderId],
    queryFn: () => getOrder(orderId),
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['order', orderId] })
    queryClient.invalidateQueries({ queryKey: ['orders'] })
    queryClient.invalidateQueries({ queryKey: ['syncStatus'] })
  }

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
        <CircularProgress size={24} />
      </Box>
    )
  }

  if (error) {
    return (
      <Alert severity="error" sx={{ m: 2 }}>
        Failed to load order items.
      </Alert>
    )
  }

  if (!order || !order.items.length) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ py: 2, px: 2 }}>
        No line items.
      </Typography>
    )
  }

  return (
    <Box sx={{ p: 1.5, bgcolor: 'action.hover' }}>
      <Stack
        direction="row"
        spacing={2}
        alignItems="center"
        sx={{ mb: 1.25, flexWrap: 'nowrap', overflow: 'hidden' }}
      >
        <Box sx={{ minWidth: 160, maxWidth: 260, flexShrink: 1, overflow: 'hidden' }}>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
            Customer
          </Typography>
          <Typography variant="body2" sx={{ fontSize: '0.82rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {order.customer_name || 'No customer'}
          </Typography>
        </Box>
        <Box sx={{ minWidth: 180, maxWidth: 300, flexShrink: 1, overflow: 'hidden' }}>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
            Email
          </Typography>
          <Typography variant="body2" sx={{ fontSize: '0.82rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {order.customer_email || '-'}
          </Typography>
        </Box>
        <Box sx={{ minWidth: 120, maxWidth: 180, flexShrink: 0 }}>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
            External ID
          </Typography>
          <Typography variant="body2" sx={{ fontSize: '0.82rem' }}>
            {order.external_order_number || order.external_order_id}
          </Typography>
        </Box>
        <Box sx={{ minWidth: 80, flexShrink: 0 }}>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
            Items
          </Typography>
          <Typography variant="body2" sx={{ fontSize: '0.82rem' }}>
            {order.items.length}
          </Typography>
        </Box>
        {headerAction && (
          <Box sx={{ marginLeft: 'auto', flexShrink: 0 }}>
            {headerAction}
          </Box>
        )}
      </Stack>
      <Box sx={{ mb: 1.25 }}>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
          Shipping Address
        </Typography>
        <Typography variant="body2" sx={{ fontSize: '0.82rem' }}>
          {[
            order.shipping_address_line1,
            order.shipping_address_line2,
            order.shipping_city,
            order.shipping_state,
            order.shipping_postal_code,
            order.shipping_country,
          ]
            .filter(Boolean)
            .join(', ') || '—'}
        </Typography>
      </Box>
      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        Line Items
      </Typography>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Item Name</TableCell>
            <TableCell>Ext SKU</TableCell>
            <TableCell align="center">Qty</TableCell>
            <TableCell align="right">Unit</TableCell>
            <TableCell align="right">Total</TableCell>
            <TableCell align="center">Status</TableCell>
            <TableCell>Variant SKU</TableCell>
            <TableCell align="center">Actions</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {order.items.map((item: OrderItemDetail) => (
            <ItemRow key={item.id} item={item} onAction={invalidate} />
          ))}
          <TableRow>
            <TableCell colSpan={3} />
            <TableCell align="right" sx={{ fontWeight: 600 }}>
              Line Total
            </TableCell>
            <TableCell align="right" sx={{ fontWeight: 600 }}>
              {order.items
                .reduce((sum, item) => sum + Number(item.total_price || 0), 0)
                .toFixed(2)}
            </TableCell>
            <TableCell colSpan={3} />
          </TableRow>
        </TableBody>
      </Table>
    </Box>
  )
}

// ── Item Row with actions ────────────────────────────────────────────

function ItemRow({ item, onAction }: { item: OrderItemDetail; onAction: () => void }) {
  const [selectedVariant, setSelectedVariant] = useState<VariantSearchResult | null>(null)
  const [showMatch, setShowMatch] = useState(false)

  const matchMutation = useMutation({
    mutationFn: () =>
      matchItem(item.id, {
        variant_id: selectedVariant!.id,
      }),
    onSuccess: () => {
      setShowMatch(false)
      setSelectedVariant(null)
      onAction()
    },
  })

  const confirmMutation = useMutation({
    mutationFn: () => confirmItem(item.id),
    onSuccess: onAction,
  })

  const rejectMutation = useMutation({
    mutationFn: () => rejectItem(item.id),
    onSuccess: onAction,
  })

  const anyPending =
    matchMutation.isPending || confirmMutation.isPending || rejectMutation.isPending

  return (
    <>
      <TableRow>
        <TableCell>
          <Typography
            variant="body2"
            sx={{ maxWidth: 280, whiteSpace: 'normal', overflowWrap: 'anywhere', wordBreak: 'break-word' }}
          >
            {item.item_name}
          </Typography>
          {item.external_asin && (
            <Typography variant="caption" color="text.secondary">
              ASIN: {item.external_asin}
            </Typography>
          )}
        </TableCell>
        <TableCell>
          <Typography variant="body2">{item.external_sku || '—'}</Typography>
        </TableCell>
        <TableCell align="center">{item.quantity}</TableCell>
        <TableCell align="right">{parseFloat(item.unit_price).toFixed(2)}</TableCell>
        <TableCell align="right">{parseFloat(item.total_price).toFixed(2)}</TableCell>
        <TableCell align="center">
          <StatusBadge status={item.status} itemLevel />
        </TableCell>
        <TableCell>
          {item.variant_sku ? (
            <Chip label={item.variant_sku} size="small" variant="outlined" color="primary" />
          ) : item.variant_id ? (
            <Chip label={`V#${item.variant_id}`} size="small" variant="outlined" />
          ) : (
            '—'
          )}
        </TableCell>
        <TableCell align="center">
          <Stack direction="row" spacing={0.5} justifyContent="center">
            {item.status === 'UNMATCHED' && (
              <Tooltip title="Match to variant">
                <IconButton
                  size="small"
                  color="primary"
                  onClick={(e: MouseEvent) => {
                    e.stopPropagation()
                    setShowMatch(!showMatch)
                  }}
                  disabled={anyPending}
                >
                  <LinkIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            )}
            {item.status === 'MATCHED' && (
              <>
                <Tooltip title="Confirm match">
                  <IconButton
                    size="small"
                    color="success"
                    onClick={(e: MouseEvent) => {
                      e.stopPropagation()
                      confirmMutation.mutate()
                    }}
                    disabled={anyPending}
                  >
                    <CheckCircle fontSize="small" />
                  </IconButton>
                </Tooltip>
                <Tooltip title="Reject match">
                  <IconButton
                    size="small"
                    color="error"
                    onClick={(e: MouseEvent) => {
                      e.stopPropagation()
                      rejectMutation.mutate()
                    }}
                    disabled={anyPending}
                  >
                    <LinkOff fontSize="small" />
                  </IconButton>
                </Tooltip>
              </>
            )}
          </Stack>
        </TableCell>
      </TableRow>

      {/* Inline match form with variant search */}
      {showMatch && (
        <TableRow>
          <TableCell colSpan={8} sx={{ py: 1, backgroundColor: 'background.paper' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, pl: 1 }}>
              <VariantSearchAutocomplete value={selectedVariant} onChange={setSelectedVariant} />
              <Button
                size="small"
                variant="contained"
                onClick={() => matchMutation.mutate()}
                disabled={!selectedVariant || matchMutation.isPending}
                startIcon={
                  matchMutation.isPending ? <CircularProgress size={14} /> : <LinkIcon />
                }
              >
                Match
              </Button>
              <Button size="small" onClick={() => setShowMatch(false)}>
                Cancel
              </Button>
              {matchMutation.isError && (
                <Alert severity="error" variant="outlined" sx={{ py: 0, ml: 1 }}>
                  {(matchMutation.error as Error)?.message || 'Match failed'}
                </Alert>
              )}
            </Box>
          </TableCell>
        </TableRow>
      )}

      {/* Matching notes */}
      {item.matching_notes && (
        <TableRow>
          <TableCell colSpan={8} sx={{ py: 0.5, borderBottom: 'none' }}>
            <Typography variant="caption" color="text.secondary" sx={{ pl: 1 }}>
              Note: {item.matching_notes}
            </Typography>
          </TableCell>
        </TableRow>
      )}
    </>
  )
}

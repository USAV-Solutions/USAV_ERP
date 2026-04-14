/**
 * ResolutionModal – Order detail drawer with SKU resolution actions.
 *
 * Shows full order info + line items.  For each UNMATCHED / MATCHED item
 * the user can:
 *   - Match:   enter a variant ID, optionally learn for future auto-match
 *   - Confirm: accept an auto-match
 *   - Reject:  reset a bad match back to UNMATCHED
 */
import { useState, type ChangeEvent } from 'react'
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Typography,
  Box,
  Divider,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Checkbox,
  FormControlLabel,
  IconButton,
  Tooltip,
  CircularProgress,
  Alert,
  Chip,
  Stack,
} from '@mui/material'
import {
  Close,
  LinkOff,
  Link as LinkIcon,
  CheckCircle,
} from '@mui/icons-material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getOrder, matchItem, confirmItem, rejectItem } from '../../api/orders'
import StatusBadge from './StatusBadge'
import type { OrderDetail, OrderItemDetail } from '../../types/orders'

// ── Platform display helpers ─────────────────────────────────────────

const PLATFORM_LABELS: Record<string, string> = {
  AMAZON: 'Amazon',
  EBAY_MEKONG: 'eBay Mekong',
  EBAY_USAV: 'eBay USAV',
  EBAY_DRAGON: 'eBay Dragon',
  ECWID: 'Ecwid',
  WALMART: 'Walmart',
  ZOHO: 'Zoho',
  MANUAL: 'Manual',
}

// ── Props ────────────────────────────────────────────────────────────

interface ResolutionModalProps {
  orderId: number | null
  onClose: () => void
}

export default function ResolutionModal({ orderId, onClose }: ResolutionModalProps) {
  const queryClient = useQueryClient()

  // Fetch full order detail
  const { data: order, isLoading, error } = useQuery<OrderDetail>({
    queryKey: ['order', orderId],
    queryFn: () => getOrder(orderId!),
    enabled: orderId !== null,
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['order', orderId] })
    queryClient.invalidateQueries({ queryKey: ['orders'] })
    queryClient.invalidateQueries({ queryKey: ['syncStatus'] })
  }

  if (orderId === null) return null

  return (
    <Dialog open={orderId !== null} onClose={onClose} maxWidth="lg" fullWidth>
      <DialogTitle sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Box>
          Order Detail
          {order && (
            <Typography variant="subtitle2" color="text.secondary">
              {PLATFORM_LABELS[order.platform] ?? order.platform} &mdash;{' '}
              {order.external_order_number || order.external_order_id}
            </Typography>
          )}
        </Box>
        <IconButton onClick={onClose} size="small">
          <Close />
        </IconButton>
      </DialogTitle>

      <DialogContent dividers>
        {isLoading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress />
          </Box>
        )}

        {error && (
          <Alert severity="error">Failed to load order.</Alert>
        )}

        {order && (
          <Box>
            {/* Header info */}
            <OrderHeaderSection order={order} onRefresh={invalidate} />

            <Divider sx={{ my: 2 }} />

            {/* Line items */}
            <Typography variant="h6" gutterBottom>
              Line Items ({order.items.length})
            </Typography>

            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Item Name</TableCell>
                    <TableCell>Ext SKU</TableCell>
                    <TableCell align="center">Qty</TableCell>
                    <TableCell align="right">Unit Price</TableCell>
                    <TableCell align="right">Total</TableCell>
                    <TableCell align="center">Status</TableCell>
                    <TableCell>Variant</TableCell>
                    <TableCell align="center">Actions</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {order.items.map((item: OrderItemDetail) => (
                    <ItemRow key={item.id} item={item} onAction={invalidate} />
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Box>
        )}
      </DialogContent>

      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  )
}

// ── Sub-components ───────────────────────────────────────────────────

function OrderHeaderSection({
  order,
}: {
  order: OrderDetail
  onRefresh: () => void
}) {
  return (
    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
      {/* Customer */}
      <Box sx={{ minWidth: 200 }}>
        <Typography variant="subtitle2" color="text.secondary">Customer</Typography>
        <Typography>{order.customer_name || '—'}</Typography>
        <Typography variant="body2" color="text.secondary">
          {order.customer_email || ''}
        </Typography>
      </Box>

      {/* Shipping */}
      <Box sx={{ minWidth: 200 }}>
        <Typography variant="subtitle2" color="text.secondary">Ship To</Typography>
        <Typography variant="body2">
          {[order.shipping_address_line1, order.shipping_address_line2]
            .filter(Boolean)
            .join(', ')}
        </Typography>
        <Typography variant="body2">
          {[order.shipping_city, order.shipping_state, order.shipping_postal_code]
            .filter(Boolean)
            .join(', ')}{' '}
          {order.shipping_country}
        </Typography>
      </Box>

      {/* Financial */}
      <Box sx={{ minWidth: 160 }}>
        <Typography variant="subtitle2" color="text.secondary">Total</Typography>
        <Typography variant="h6">
          {order.currency} {parseFloat(order.total_amount).toFixed(2)}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          Sub: {parseFloat(order.subtotal_amount).toFixed(2)} | Tax:{' '}
          {parseFloat(order.tax_amount).toFixed(2)} | Ship:{' '}
          {parseFloat(order.shipping_amount).toFixed(2)}
        </Typography>
      </Box>

      {/* Status */}
      <Box sx={{ minWidth: 140 }}>
        <Typography variant="subtitle2" color="text.secondary">Status</Typography>
        <StatusBadge status={order.status} size="medium" />
        {order.ordered_at && (
          <Typography variant="caption" display="block" mt={0.5}>
            Ordered: {new Date(order.ordered_at).toLocaleDateString()}
          </Typography>
        )}
      </Box>

      {/* Tracking */}
      {order.tracking_number && (
        <Box sx={{ minWidth: 160 }}>
          <Typography variant="subtitle2" color="text.secondary">Tracking</Typography>
          <Typography variant="body2">
            {order.carrier}: {order.tracking_number}
          </Typography>
        </Box>
      )}

      {/* Notes / Error */}
      {(order.processing_notes || order.error_message) && (
        <Box sx={{ minWidth: 200, maxWidth: 400 }}>
          {order.error_message && (
            <Alert severity="error" variant="outlined" sx={{ mb: 1 }}>
              {order.error_message}
            </Alert>
          )}
          {order.processing_notes && (
            <Typography variant="body2" color="text.secondary">
              Notes: {order.processing_notes}
            </Typography>
          )}
        </Box>
      )}
    </Box>
  )
}

function ItemRow({ item, onAction }: { item: OrderItemDetail; onAction: () => void }) {
  const [matchVariantId, setMatchVariantId] = useState('')
  const [learn, setLearn] = useState(true)
  const [showMatch, setShowMatch] = useState(false)

  const matchMutation = useMutation({
    mutationFn: () =>
      matchItem(item.id, {
        variant_id: parseInt(matchVariantId, 10),
        learn,
      }),
    onSuccess: () => {
      setShowMatch(false)
      setMatchVariantId('')
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
      <TableRow hover>
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
          <Typography variant="body2">
            {item.external_sku || '—'}
          </Typography>
        </TableCell>
        <TableCell align="center">{item.quantity}</TableCell>
        <TableCell align="right">{parseFloat(item.unit_price).toFixed(2)}</TableCell>
        <TableCell align="right">{parseFloat(item.total_price).toFixed(2)}</TableCell>
        <TableCell align="center">
          <StatusBadge status={item.status} itemLevel />
        </TableCell>
        <TableCell>
          {item.variant_id ? (
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
                  onClick={() => setShowMatch(!showMatch)}
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
                    onClick={() => confirmMutation.mutate()}
                    disabled={anyPending}
                  >
                    <CheckCircle fontSize="small" />
                  </IconButton>
                </Tooltip>
                <Tooltip title="Reject match">
                  <IconButton
                    size="small"
                    color="error"
                    onClick={() => rejectMutation.mutate()}
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

      {/* Inline match form */}
      {showMatch && (
        <TableRow>
          <TableCell colSpan={8} sx={{ py: 1, backgroundColor: 'action.hover' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, pl: 1 }}>
              <TextField
                size="small"
                label="Variant ID"
                type="number"
                value={matchVariantId}
                onChange={(e: ChangeEvent<HTMLInputElement>) => setMatchVariantId(e.target.value)}
                sx={{ width: 130 }}
              />
              <FormControlLabel
                control={
                  <Checkbox
                    checked={learn}
                    onChange={(e: ChangeEvent<HTMLInputElement>) => setLearn(e.target.checked)}
                    size="small"
                  />
                }
                label="Learn for auto-match"
              />
              <Button
                size="small"
                variant="contained"
                onClick={() => matchMutation.mutate()}
                disabled={!matchVariantId || matchMutation.isPending}
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

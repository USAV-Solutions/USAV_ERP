/**
 * OrderItemsPanel – Inline expandable panel showing order line items.
 *
 * Renders inside a collapsed table row. For each item shows name, SKU,
 * quantity, price, status, linked variant SKU, and action buttons.
 *
 * Match action uses an Autocomplete that searches variants by product
 * name or SKU via GET /variants/search?q=...
 */
import React, { useState, type MouseEvent } from 'react'
import {
  Box,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  IconButton,
  Tooltip,
  CircularProgress,
  Alert,
  Chip,
  Stack,
  Autocomplete,
  AutocompleteRenderInputParams,
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
  searchVariants,
} from '../../api/orders'
import StatusBadge from './StatusBadge'
import type {
  OrderDetail,
  OrderItemDetail,
  VariantSearchResult,
} from '../../types/orders'

// ── Props ────────────────────────────────────────────────────────────

interface OrderItemsPanelProps {
  orderId: number
}

export default function OrderItemsPanel({ orderId }: OrderItemsPanelProps) {
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
    <Box sx={{ py: 1, px: 2 }}>
      {/* Mini header with order info */}
      <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 1 }}>
        <Typography variant="subtitle2" color="text.secondary">
          {order.customer_name || 'No customer'} — {order.items.length} item(s)
        </Typography>
        {order.customer_email && (
          <Typography variant="caption" color="text.secondary">
            {order.customer_email}
          </Typography>
        )}
      </Stack>

      <Table size="small" sx={{ backgroundColor: 'action.hover', borderRadius: 1 }}>
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
        </TableBody>
      </Table>
    </Box>
  )
}

// ── Item Row with actions ────────────────────────────────────────────

function ItemRow({ item, onAction }: { item: OrderItemDetail; onAction: () => void }) {
  const [selectedVariant, setSelectedVariant] = useState<VariantSearchResult | null>(null)
  const [searchInput, setSearchInput] = useState('')
  const [showMatch, setShowMatch] = useState(false)

  // Variant search query
  const { data: variantOptions = [], isFetching: searchLoading } = useQuery<VariantSearchResult[]>({
    queryKey: ['variantSearch', searchInput],
    queryFn: () => searchVariants(searchInput),
    enabled: searchInput.length >= 1,
    staleTime: 30_000,
  })

  const matchMutation = useMutation({
    mutationFn: () =>
      matchItem(item.id, {
        variant_id: selectedVariant!.id,
      }),
    onSuccess: () => {
      setShowMatch(false)
      setSelectedVariant(null)
      setSearchInput('')
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
          <Typography variant="body2" noWrap sx={{ maxWidth: 280 }}>
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
              <Autocomplete<VariantSearchResult>
                size="small"
                sx={{ width: 360 }}
                options={variantOptions}
                loading={searchLoading}
                value={selectedVariant}
                onChange={(_e, value) => setSelectedVariant(value)}
                onInputChange={(_e, value) => setSearchInput(value)}
                getOptionLabel={(opt: VariantSearchResult) => `${opt.full_sku} — ${opt.product_name}`}
                isOptionEqualToValue={(opt: VariantSearchResult, val: VariantSearchResult) => opt.id === val.id}
                renderOption={(props, opt: VariantSearchResult) => (
                  <li {...(props as React.HTMLAttributes<HTMLLIElement>)} key={opt.id}>
                    <Box>
                      <Typography variant="body2" fontWeight={600}>
                        {opt.full_sku}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {opt.product_name}
                        {opt.color_code && ` · ${opt.color_code}`}
                        {opt.condition_code && ` · ${opt.condition_code}`}
                      </Typography>
                    </Box>
                  </li>
                )}
                renderInput={(params: AutocompleteRenderInputParams) => (
                  <TextField
                    {...params}
                    label="Search variant by name or SKU"
                    placeholder="Type to search..."
                  />
                )}
                noOptionsText={searchInput.length < 1 ? 'Type to search...' : 'No variants found'}
              />
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

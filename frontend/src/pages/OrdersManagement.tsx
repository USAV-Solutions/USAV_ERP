/**
 * OrdersManagement – the main Orders page.
 *
 * Layout:
 *   - Sync status banner (platform states + aggregate counters)
 *   - Filter bar: platform, order status, item status, search
 *   - Paginated MUI Table of OrderBrief rows with expandable item rows
 *   - OrderSyncButton in the header
 */
import { useState, Fragment } from 'react'
import {
  Box,
  Typography,
  Paper,
  Grid,
  Card,
  CardContent,
  Chip,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  CircularProgress,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Alert,
  Tooltip,
  IconButton,
  Stack,
  Collapse,
  Snackbar,
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  LinearProgress,
  TextField,
} from '@mui/material'
import {
  Refresh,
  Warning,
  KeyboardArrowDown,
  KeyboardArrowUp,
  CloudSync,
} from '@mui/icons-material'
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'

import { listOrders, getSyncStatus, updateOrderStatus, updateShippingStatus, deleteOrder } from '../api/orders'
import { forceSyncOrder } from '../api/sync'
import type {
  OrderBrief,
  OrderListResponse,
  OrderPlatform,
  OrderStatus,
  OrderItemStatus,
  ShippingStatus,
  SyncStatusResponse,
  ZohoSyncStatus,
} from '../types/orders'

import OrderSyncButton from '../components/orders/OrderSyncButton'
import AdminDateRangeSync from '../components/orders/AdminDateRangeSync'
import OrderItemsPanel from '../components/orders/OrderItemsPanel'
import { useAuth } from '../hooks/useAuth'
import SearchField from '../components/common/SearchField'
import { useDebouncedValue } from '../hooks/useDebouncedValue'
import LongPressTableRow from '../components/common/LongPressTableRow'
import HoldActionPromptDialog from '../components/common/HoldActionPromptDialog'
import TablePaginationWithPageJump from '../components/common/TablePaginationWithPageJump'

// ── Label maps ───────────────────────────────────────────────────────

const PLATFORM_LABELS: Record<OrderPlatform, string> = {
  AMAZON: 'Amazon',
  EBAY_MEKONG: 'eBay Mekong',
  EBAY_USAV: 'eBay USAV',
  EBAY_DRAGON: 'eBay Dragon',
  ECWID: 'Ecwid',
  ZOHO: 'Zoho',
  MANUAL: 'Manual',
}

const ORDER_STATUS_OPTIONS: OrderStatus[] = [
  'PENDING',
  'PROCESSING',
  'READY_TO_SHIP',
  'SHIPPED',
  'DELIVERED',
  'CANCELLED',
  'REFUNDED',
  'ON_HOLD',
  'ERROR',
]

const ITEM_STATUS_OPTIONS: OrderItemStatus[] = [
  'UNMATCHED',
  'MATCHED',
  'ALLOCATED',
  'SHIPPED',
  'CANCELLED',
]

const SHIPPING_STATUS_OPTIONS: ShippingStatus[] = [
  'PENDING',
  'ON_HOLD',
  'CANCELLED',
  'PACKED',
  'SHIPPING',
  'DELIVERED',
]

const ZOHO_SYNC_COLOR: Record<ZohoSyncStatus, 'default' | 'success' | 'error' | 'warning'> = {
  PENDING: 'warning',
  DIRTY: 'warning',
  SYNCED: 'success',
  ERROR: 'error',
}

// ── Component ────────────────────────────────────────────────────────

export default function OrdersManagement() {
  const queryClient = useQueryClient()
  const { hasRole } = useAuth()

  // Pagination
  const [page, setPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(25)

  // Filters
  const [platformFilter, setPlatformFilter] = useState<OrderPlatform | ''>('')
  const [statusFilter, setStatusFilter] = useState<OrderStatus | ''>('')
  const [itemStatusFilter, setItemStatusFilter] = useState<OrderItemStatus | ''>('')
  const [searchInput, setSearchInput] = useState('')
  const debouncedSearch = useDebouncedValue(searchInput, 250)

  // Expanded order rows
  const [expandedOrderId, setExpandedOrderId] = useState<number | null>(null)

  // Force-sync state
  const [syncingOrderId, setSyncingOrderId] = useState<number | null>(null)
  const [snackbarOpen, setSnackbarOpen] = useState(false)
  const [snackbarMessage, setSnackbarMessage] = useState('')
  const [snackbarSeverity, setSnackbarSeverity] = useState<'success' | 'error'>('success')
  const [shippingUpdatingId, setShippingUpdatingId] = useState<number | null>(null)
  const [holdPromptOpen, setHoldPromptOpen] = useState(false)
  const [selectedOrder, setSelectedOrder] = useState<OrderBrief | null>(null)
  const [editOrderStatus, setEditOrderStatus] = useState<OrderStatus>('PENDING')
  const [editShippingStatus, setEditShippingStatus] = useState<ShippingStatus>('PENDING')
  const [editNotes, setEditNotes] = useState('')

  // Bulk Zoho sync (matched orders only)
  const [bulkDialogOpen, setBulkDialogOpen] = useState(false)
  const [bulkLoading, setBulkLoading] = useState(false)
  const [bulkError, setBulkError] = useState<string | null>(null)
  const [bulkTotal, setBulkTotal] = useState(0)
  const [bulkProgress, setBulkProgress] = useState({ queued: 0, success: 0, failed: 0 })
  const [bulkDone, setBulkDone] = useState(false)

  // ── Queries ──────────────────────────────────────────────────────

  const {
    data: syncStatus,
  } = useQuery<SyncStatusResponse>({
    queryKey: ['syncStatus'],
    queryFn: getSyncStatus,
    refetchInterval: 15_000,
  })

  const {
    data: ordersData,
    isLoading: ordersLoading,
  } = useQuery<OrderListResponse>({
    queryKey: ['orders', page, rowsPerPage, platformFilter, statusFilter, itemStatusFilter, debouncedSearch],
    queryFn: () =>
      listOrders({
        skip: page * rowsPerPage,
        limit: rowsPerPage,
        platform: platformFilter || undefined,
        status: statusFilter || undefined,
        item_status: itemStatusFilter || undefined,
        search: debouncedSearch || undefined,
      }),
  })

  // ── Handlers ─────────────────────────────────────────────────────

  const forceSyncMutation = useMutation({
    mutationFn: (orderId: number) => forceSyncOrder(orderId),
    onMutate: (orderId) => setSyncingOrderId(orderId),
    onSuccess: (_data, orderId) => {
      setSnackbarSeverity('success')
      setSnackbarMessage(`Order #${orderId} queued for Zoho sync.`)
      setSnackbarOpen(true)
      setSyncingOrderId(null)
    },
    onError: (error: { response?: { data?: { detail?: string } }; message?: string }, orderId) => {
      const detail = error.response?.data?.detail || error.message || 'Force sync failed.'
      setSnackbarSeverity('error')
      setSnackbarMessage(`Order #${orderId}: ${detail}`)
      setSnackbarOpen(true)
      setSyncingOrderId(null)
    },
  })

  const updateShippingMutation = useMutation({
    mutationFn: ({ orderId, shipping_status }: { orderId: number; shipping_status: ShippingStatus }) =>
      updateShippingStatus(orderId, { shipping_status }),
    onMutate: ({ orderId }) => setShippingUpdatingId(orderId),
    onSuccess: () => {
      setSnackbarSeverity('success')
      setSnackbarMessage('Shipping status updated — Zoho sync queued.')
      setSnackbarOpen(true)
      queryClient.invalidateQueries({ queryKey: ['orders'] })
    },
    onError: (error: { response?: { data?: { detail?: string } }; message?: string }) => {
      const detail = error.response?.data?.detail || error.message || 'Update failed.'
      setSnackbarSeverity('error')
      setSnackbarMessage(detail)
      setSnackbarOpen(true)
    },
    onSettled: () => setShippingUpdatingId(null),
  })

  const saveHoldOrderMutation = useMutation({
    mutationFn: async () => {
      if (!selectedOrder) {
        throw new Error('No order selected')
      }

      await updateOrderStatus(selectedOrder.id, {
        status: editOrderStatus,
        notes: editNotes,
      })

      await updateShippingStatus(selectedOrder.id, {
        shipping_status: editShippingStatus,
      })
    },
    onSuccess: async () => {
      setSnackbarSeverity('success')
      setSnackbarMessage('Order updated successfully.')
      setSnackbarOpen(true)
      setHoldPromptOpen(false)
      setSelectedOrder(null)
      await queryClient.invalidateQueries({ queryKey: ['orders'] })
    },
    onError: (error: { response?: { data?: { detail?: string } }; message?: string }) => {
      const detail = error.response?.data?.detail || error.message || 'Order update failed.'
      setSnackbarSeverity('error')
      setSnackbarMessage(detail)
      setSnackbarOpen(true)
    },
  })

  const deleteOrderMutation = useMutation({
    mutationFn: () => {
      if (!selectedOrder) {
        throw new Error('No order selected')
      }
      return deleteOrder(selectedOrder.id)
    },
    onSuccess: async () => {
      setSnackbarSeverity('success')
      setSnackbarMessage('Order deleted successfully.')
      setSnackbarOpen(true)
      setHoldPromptOpen(false)
      setSelectedOrder(null)
      await queryClient.invalidateQueries({ queryKey: ['orders'] })
      await queryClient.invalidateQueries({ queryKey: ['syncStatus'] })
    },
    onError: (error: { response?: { data?: { detail?: string } }; message?: string }) => {
      const detail = error.response?.data?.detail || error.message || 'Order delete failed.'
      setSnackbarSeverity('error')
      setSnackbarMessage(detail)
      setSnackbarOpen(true)
    },
  })

  const openHoldPrompt = (order: OrderBrief) => {
    setSelectedOrder(order)
    setEditOrderStatus(order.status)
    setEditShippingStatus(order.shipping_status)
    setEditNotes('')
    setHoldPromptOpen(true)
  }

  const handleForceSync = (orderId: number, e: React.MouseEvent) => {
    e.stopPropagation() // prevent row expand
    forceSyncMutation.mutate(orderId)
  }

  const handleBulkSync = async () => {
    setBulkLoading(true)
    setBulkError(null)
    setBulkDone(false)
    setBulkProgress({ queued: 0, success: 0, failed: 0 })

    try {
      // Fetch all orders (cap at 2000 to avoid runaway)
      const pageSize = 500
      let skip = 0
      let eligibleIds: number[] = []

      // eslint-disable-next-line no-constant-condition
      while (true) {
        const batch = await listOrders({ skip, limit: pageSize })
        const matched = batch.items.filter((o) => o.unmatched_count === 0).map((o) => o.id)
        eligibleIds = eligibleIds.concat(matched)

        if (batch.items.length < pageSize || eligibleIds.length >= 2000) {
          break
        }
        skip += pageSize
      }

      setBulkTotal(eligibleIds.length)

      if (!eligibleIds.length) {
        setBulkDone(true)
        return
      }

      let firstError: string | null = null

      // Sequentially queue to avoid API burst
      for (const id of eligibleIds) {
        try {
          await forceSyncOrder(id)
          setBulkProgress((p) => ({ queued: p.queued + 1, success: p.success + 1, failed: p.failed }))
        } catch (err: any) {
          setBulkProgress((p) => ({ queued: p.queued + 1, success: p.success, failed: p.failed + 1 }))
          if (!firstError) {
            firstError = err?.message || 'One or more orders failed to queue.'
          }
        }
      }

      if (firstError) {
        setBulkError(firstError)
      }

      setBulkDone(true)
      await queryClient.invalidateQueries({ queryKey: ['orders'] })
      await queryClient.invalidateQueries({ queryKey: ['syncStatus'] })
    } catch (err: any) {
      setBulkError(err?.message || 'Failed to load orders for bulk sync.')
    } finally {
      setBulkLoading(false)
    }
  }

  const resetFilters = () => {
    setPlatformFilter('')
    setStatusFilter('')
    setItemStatusFilter('')
    setSearchInput('')
    setPage(0)
  }

  const bulkPercent = bulkTotal ? Math.min(Math.round((bulkProgress.queued / bulkTotal) * 100), 100) : 0
  const columnCount = hasRole(['ADMIN']) ? 10 : 9

  const handleShippingStatusChange = (
    orderId: number,
    shipping_status: ShippingStatus,
    e: { stopPropagation: () => void },
  ) => {
    e.stopPropagation()
    updateShippingMutation.mutate({ orderId, shipping_status })
  }

  // ── Render ───────────────────────────────────────────────────────

  return (
    <Box>
      {/* Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h4">Orders Management</Typography>
        <Stack direction="row" spacing={1}>
          <Tooltip title="Refresh">
            <IconButton
              onClick={() => {
                queryClient.invalidateQueries({ queryKey: ['orders'] })
                queryClient.invalidateQueries({ queryKey: ['syncStatus'] })
              }}
            >
              <Refresh />
            </IconButton>
          </Tooltip>
          {hasRole(['ADMIN']) && <AdminDateRangeSync />}
          {hasRole(['ADMIN']) && (
            <Button
              variant="outlined"
              onClick={() => {
                setBulkDialogOpen(true)
                setBulkError(null)
                setBulkDone(false)
                setBulkTotal(0)
                setBulkProgress({ queued: 0, success: 0, failed: 0 })
              }}
            >
              Sync matched to Zoho
            </Button>
          )}
          <OrderSyncButton />
        </Stack>
      </Box>

      {/* Summary Cards */}
      {syncStatus && (
        <Grid container spacing={2} sx={{ mb: 3 }}>
          <Grid item xs={6} sm={3}>
            <Card>
              <CardContent sx={{ py: 1.5 }}>
                <Typography color="text.secondary" variant="body2">
                  Total Orders
                </Typography>
                <Typography variant="h5">{syncStatus.total_orders}</Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={6} sm={3}>
            <Card>
              <CardContent sx={{ py: 1.5 }}>
                <Typography color="text.secondary" variant="body2">
                  Unmatched Items
                </Typography>
                <Typography variant="h5" color="error.main">
                  {syncStatus.total_unmatched_items}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={6} sm={3}>
            <Card>
              <CardContent sx={{ py: 1.5 }}>
                <Typography color="text.secondary" variant="body2">
                  Matched Items
                </Typography>
                <Typography variant="h5" color="info.main">
                  {syncStatus.total_matched_items}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={6} sm={3}>
            <Card>
              <CardContent sx={{ py: 1.5 }}>
                <Typography color="text.secondary" variant="body2">
                  Platforms
                </Typography>
                <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
                  {syncStatus.platforms.map((p) => (
                    <Chip
                      key={p.platform_name}
                      label={p.platform_name}
                      size="small"
                      color={
                        p.current_status === 'SYNCING'
                          ? 'primary'
                          : p.current_status === 'ERROR'
                            ? 'error'
                            : 'default'
                      }
                      variant="outlined"
                    />
                  ))}
                </Stack>
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      )}

      {/* Platform error alerts */}
      {syncStatus?.platforms
        .filter((p) => p.current_status === 'ERROR')
        .map((p) => (
          <Alert
            key={p.platform_name}
            severity="warning"
            icon={<Warning />}
            sx={{ mb: 1 }}
          >
            <strong>{p.platform_name}</strong> sync is in ERROR state.{' '}
            {p.last_error_message && <em>{p.last_error_message}</em>}
          </Alert>
        ))}

      {/* Filters */}
      <Paper sx={{ p: 2, mb: 2 }}>
        <Grid container spacing={2} alignItems="center">
          <Grid item xs={12} md={3}>
            <SearchField
              fullWidth
              size="small"
              placeholder="Search order ID or customer..."
              value={searchInput}
              onChange={(value) => {
                setSearchInput(value)
                setPage(0)
              }}
            />
          </Grid>
          <Grid item xs={6} md={2.5}>
            <FormControl fullWidth size="small">
              <InputLabel>Platform</InputLabel>
              <Select
                value={platformFilter}
                onChange={(e) => {
                  setPlatformFilter(e.target.value as OrderPlatform | '')
                  setPage(0)
                }}
                label="Platform"
              >
                <MenuItem value="">All</MenuItem>
                {(Object.keys(PLATFORM_LABELS) as OrderPlatform[]).map((p) => (
                  <MenuItem key={p} value={p}>
                    {PLATFORM_LABELS[p]}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={6} md={2.5}>
            <FormControl fullWidth size="small">
              <InputLabel>Order Status</InputLabel>
              <Select
                value={statusFilter}
                onChange={(e) => {
                  setStatusFilter(e.target.value as OrderStatus | '')
                  setPage(0)
                }}
                label="Order Status"
              >
                <MenuItem value="">All</MenuItem>
                {ORDER_STATUS_OPTIONS.map((s) => (
                  <MenuItem key={s} value={s}>
                    {s.replace(/_/g, ' ')}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={6} md={2.5}>
            <FormControl fullWidth size="small">
              <InputLabel>Item Status</InputLabel>
              <Select
                value={itemStatusFilter}
                onChange={(e) => {
                  setItemStatusFilter(e.target.value as OrderItemStatus | '')
                  setPage(0)
                }}
                label="Item Status"
              >
                <MenuItem value="">All</MenuItem>
                {ITEM_STATUS_OPTIONS.map((s) => (
                  <MenuItem key={s} value={s}>
                    {s}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={6} md={1.5}>
            <Tooltip title="Reset filters">
              <IconButton onClick={resetFilters} size="small">
                <Refresh fontSize="small" />
              </IconButton>
            </Tooltip>
          </Grid>
        </Grid>
      </Paper>

      {/* Orders Table */}
      <Paper>
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell sx={{ width: 40 }} />
                <TableCell>Order #</TableCell>
                <TableCell>Platform</TableCell>
                <TableCell>Customer</TableCell>
                <TableCell align="center">Unmatched</TableCell>
                <TableCell align="right">Total</TableCell>
                <TableCell>Shipping Status</TableCell>
                <TableCell>Zoho Sync</TableCell>
                <TableCell>Ordered</TableCell>
                {hasRole(['ADMIN']) && <TableCell align="center">Zoho</TableCell>}
              </TableRow>
            </TableHead>
            <TableBody>
              {ordersLoading ? (
                <TableRow>
                  <TableCell colSpan={columnCount} align="center" sx={{ py: 4 }}>
                    <CircularProgress />
                  </TableCell>
                </TableRow>
              ) : !ordersData?.items.length ? (
                <TableRow>
                  <TableCell colSpan={columnCount} align="center" sx={{ py: 4 }}>
                    No orders found
                  </TableCell>
                </TableRow>
              ) : (
                ordersData.items.map((order: OrderBrief) => {
                  const isExpanded = expandedOrderId === order.id
                  return (
                    <Fragment key={order.id}>
                      <LongPressTableRow
                        hover
                        payload={order}
                        onLongPress={openHoldPrompt}
                        enableLongPress={hasRole(['ADMIN'])}
                        rowSx={{ cursor: 'pointer', '& > *': { borderBottom: isExpanded ? 'unset' : undefined } }}
                        onClick={() => setExpandedOrderId(isExpanded ? null : order.id)}
                      >
                        <TableCell sx={{ width: 40, px: 1 }}>
                          <IconButton size="small">
                            {isExpanded ? <KeyboardArrowUp /> : <KeyboardArrowDown />}
                          </IconButton>
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2" fontWeight={500}>
                            {order.external_order_number || order.external_order_id}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Chip
                            size="small"
                            label={PLATFORM_LABELS[order.platform] ?? order.platform}
                            variant="outlined"
                          />
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2">
                            {order.customer_name || '—'}
                          </Typography>
                        </TableCell>
                        <TableCell align="center">
                          {order.unmatched_count > 0 ? (
                            <Chip
                              label={order.unmatched_count}
                              size="small"
                              color="error"
                              variant="filled"
                            />
                          ) : (
                            <Chip label="0" size="small" color="success" variant="outlined" />
                          )}
                        </TableCell>
                        <TableCell align="right">
                          <Typography variant="body2">
                            {order.currency} {parseFloat(order.total_amount).toFixed(2)}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <FormControl size="small" fullWidth>
                            <Select
                              value={order.shipping_status}
                              size="small"
                              onClick={(e) => e.stopPropagation()}
                              onChange={(e) => handleShippingStatusChange(order.id, e.target.value as ShippingStatus, e)}
                              disabled={shippingUpdatingId === order.id}
                            >
                              {SHIPPING_STATUS_OPTIONS.map((s) => (
                                <MenuItem key={s} value={s}>
                                  {s.replace(/_/g, ' ')}
                                </MenuItem>
                              ))}
                            </Select>
                          </FormControl>
                        </TableCell>
                        <TableCell>
                          <Chip
                            size="small"
                            variant="outlined"
                            color={ZOHO_SYNC_COLOR[order.zoho_sync_status]}
                            label={order.zoho_sync_status}
                          />
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2">
                            {order.ordered_at
                              ? new Date(order.ordered_at).toLocaleDateString()
                              : '—'}
                          </Typography>
                        </TableCell>
                        {hasRole(['ADMIN']) && (
                          <TableCell align="center">
                            <Tooltip title="Sync this order to Zoho">
                              <span>
                                <IconButton
                                  size="small"
                                  color="primary"
                                  onClick={(e) => handleForceSync(order.id, e)}
                                  disabled={syncingOrderId === order.id}
                                >
                                  {syncingOrderId === order.id ? (
                                    <CircularProgress size={18} />
                                  ) : (
                                    <CloudSync fontSize="small" />
                                  )}
                                </IconButton>
                              </span>
                            </Tooltip>
                          </TableCell>
                        )}
                      </LongPressTableRow>
                      {/* Expandable items panel */}
                      <TableRow>
                        <TableCell sx={{ py: 0 }} colSpan={columnCount}>
                          <Collapse in={isExpanded} timeout="auto" unmountOnExit>
                            <OrderItemsPanel orderId={order.id} />
                          </Collapse>
                        </TableCell>
                      </TableRow>
                    </Fragment>
                  )
                })
              )}
            </TableBody>
          </Table>
        </TableContainer>
        <TablePaginationWithPageJump
          count={ordersData?.total ?? 0}
          page={page}
          rowsPerPage={rowsPerPage}
          rowsPerPageOptions={[10, 25, 50, 100]}
          onPageChange={(nextPage) => setPage(nextPage)}
          onRowsPerPageChange={(nextRowsPerPage) => {
            setRowsPerPage(nextRowsPerPage)
            setPage(0)
          }}
        />
      </Paper>

      {/* Bulk Zoho sync dialog */}
      <Dialog
        open={bulkDialogOpen}
        onClose={bulkLoading ? undefined : () => setBulkDialogOpen(false)}
        fullWidth
        maxWidth="sm"
      >
        <DialogTitle>Sync matched orders to Zoho</DialogTitle>
        <DialogContent dividers>
          <Stack spacing={2}>
            <Typography variant="body2" color="text.secondary">
              Only orders with 0 unmatched items will be queued. Fetches up to 2000 orders and queues
              them sequentially to avoid API spikes.
            </Typography>
            <Stack spacing={1}>
              <Typography variant="body2">
                Eligible orders: {bulkTotal}
              </Typography>
              <Typography variant="body2">
                Success: {bulkProgress.success} · Failed: {bulkProgress.failed}
              </Typography>
              <LinearProgress
                variant={bulkTotal ? 'determinate' : 'indeterminate'}
                value={bulkTotal ? bulkPercent : undefined}
              />
              {bulkTotal > 0 && (
                <Typography variant="caption" color="text.secondary">
                  {bulkPercent}%
                </Typography>
              )}
            </Stack>
            {bulkLoading && (
              <Alert severity="info" icon={<CircularProgress size={16} />}>
                Queueing matched orders to Zoho...
              </Alert>
            )}
            {bulkDone && !bulkLoading && !bulkError && bulkTotal > 0 && (
              <Alert severity="success">All matched orders queued successfully.</Alert>
            )}
            {bulkDone && !bulkLoading && bulkTotal === 0 && (
              <Alert severity="info">No matched orders found to sync.</Alert>
            )}
            {bulkError && (
              <Alert severity="warning" sx={{ whiteSpace: 'pre-line' }}>
                {bulkError}
              </Alert>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setBulkDialogOpen(false)} disabled={bulkLoading}>
            Close
          </Button>
          <Button onClick={handleBulkSync} variant="contained" disabled={bulkLoading}>
            {bulkLoading ? 'Syncing…' : 'Start sync'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Force-sync feedback */}
      <Snackbar
        open={snackbarOpen}
        autoHideDuration={4000}
        onClose={() => setSnackbarOpen(false)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert
          onClose={() => setSnackbarOpen(false)}
          severity={snackbarSeverity}
          variant="filled"
          sx={{ width: '100%' }}
        >
          {snackbarMessage}
        </Alert>
      </Snackbar>

      <HoldActionPromptDialog
        open={holdPromptOpen}
        onClose={() => {
          setHoldPromptOpen(false)
          setSelectedOrder(null)
        }}
        title="Edit Order"
        onSave={() => saveHoldOrderMutation.mutate()}
        onDelete={() => deleteOrderMutation.mutate()}
        saveDisabled={!selectedOrder}
        deleteDisabled={!selectedOrder || !hasRole(['ADMIN'])}
        saveLoading={saveHoldOrderMutation.isPending}
        deleteLoading={deleteOrderMutation.isPending}
        deleteConfirmTitle="Delete Order"
        deleteConfirmMessage={
          <Typography>
            Delete order <strong>{selectedOrder?.external_order_number || selectedOrder?.external_order_id}</strong>? This action cannot be undone.
          </Typography>
        }
      >
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField
            label="Order"
            value={selectedOrder ? selectedOrder.external_order_number || selectedOrder.external_order_id : ''}
            fullWidth
            disabled
          />
          <TextField
            label="Customer"
            value={selectedOrder?.customer_name || ''}
            fullWidth
            disabled
          />
          <FormControl fullWidth size="small">
            <InputLabel>Order Status</InputLabel>
            <Select
              value={editOrderStatus}
              onChange={(e) => setEditOrderStatus(e.target.value as OrderStatus)}
              label="Order Status"
            >
              {ORDER_STATUS_OPTIONS.map((s) => (
                <MenuItem key={s} value={s}>
                  {s.replace(/_/g, ' ')}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl fullWidth size="small">
            <InputLabel>Shipping Status</InputLabel>
            <Select
              value={editShippingStatus}
              onChange={(e) => setEditShippingStatus(e.target.value as ShippingStatus)}
              label="Shipping Status"
            >
              {SHIPPING_STATUS_OPTIONS.map((s) => (
                <MenuItem key={s} value={s}>
                  {s.replace(/_/g, ' ')}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <TextField
            label="Processing Notes"
            value={editNotes}
            onChange={(e) => setEditNotes(e.target.value)}
            multiline
            minRows={3}
            fullWidth
          />
        </Stack>
      </HoldActionPromptDialog>
    </Box>
  )
}

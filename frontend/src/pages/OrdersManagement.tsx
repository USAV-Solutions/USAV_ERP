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
  TextField,
  InputAdornment,
  Chip,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TablePagination,
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
} from '@mui/material'
import {
  Search,
  Refresh,
  Warning,
  KeyboardArrowDown,
  KeyboardArrowUp,
} from '@mui/icons-material'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { listOrders, getOrder, getSyncStatus } from '../api/orders'
import type {
  OrderBrief,
  OrderListResponse,
  OrderDetail,
  OrderPlatform,
  OrderStatus,
  OrderItemStatus,
  SyncStatusResponse,
} from '../types/orders'

import StatusBadge from '../components/orders/StatusBadge'
import OrderSyncButton from '../components/orders/OrderSyncButton'
import AdminDateRangeSync from '../components/orders/AdminDateRangeSync'
import OrderItemsPanel from '../components/orders/OrderItemsPanel'
import { useAuth } from '../hooks/useAuth'

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
  const [search, setSearch] = useState('')

  // Expanded order rows
  const [expandedOrderId, setExpandedOrderId] = useState<number | null>(null)

  // ── Queries ──────────────────────────────────────────────────────

  const {
    data: syncStatus,
    isLoading: syncLoading,
  } = useQuery<SyncStatusResponse>({
    queryKey: ['syncStatus'],
    queryFn: getSyncStatus,
    refetchInterval: 15_000,
  })

  const {
    data: ordersData,
    isLoading: ordersLoading,
  } = useQuery<OrderListResponse>({
    queryKey: ['orders', page, rowsPerPage, platformFilter, statusFilter, itemStatusFilter, search],
    queryFn: () =>
      listOrders({
        skip: page * rowsPerPage,
        limit: rowsPerPage,
        platform: platformFilter || undefined,
        status: statusFilter || undefined,
        item_status: itemStatusFilter || undefined,
        search: search || undefined,
      }),
  })

  // ── Handlers ─────────────────────────────────────────────────────

  const resetFilters = () => {
    setPlatformFilter('')
    setStatusFilter('')
    setItemStatusFilter('')
    setSearch('')
    setPage(0)
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
            <TextField
              fullWidth
              size="small"
              placeholder="Search order ID or customer..."
              value={search}
              onChange={(e) => {
                setSearch(e.target.value)
                setPage(0)
              }}
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start">
                    <Search fontSize="small" />
                  </InputAdornment>
                ),
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
                <TableCell align="center">Items</TableCell>
                <TableCell align="center">Unmatched</TableCell>
                <TableCell align="right">Total</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Ordered</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {ordersLoading ? (
                <TableRow>
                  <TableCell colSpan={9} align="center" sx={{ py: 4 }}>
                    <CircularProgress />
                  </TableCell>
                </TableRow>
              ) : !ordersData?.items.length ? (
                <TableRow>
                  <TableCell colSpan={9} align="center" sx={{ py: 4 }}>
                    No orders found
                  </TableCell>
                </TableRow>
              ) : (
                ordersData.items.map((order: OrderBrief) => {
                  const isExpanded = expandedOrderId === order.id
                  return (
                    <Fragment key={order.id}>
                      <TableRow
                        hover
                        sx={{ cursor: 'pointer', '& > *': { borderBottom: isExpanded ? 'unset' : undefined } }}
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
                        <TableCell align="center">{order.item_count}</TableCell>
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
                          <StatusBadge status={order.status} />
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2">
                            {order.ordered_at
                              ? new Date(order.ordered_at).toLocaleDateString()
                              : '—'}
                          </Typography>
                        </TableCell>
                      </TableRow>
                      {/* Expandable items panel */}
                      <TableRow>
                        <TableCell sx={{ py: 0 }} colSpan={9}>
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
        <TablePagination
          rowsPerPageOptions={[10, 25, 50, 100]}
          component="div"
          count={ordersData?.total ?? 0}
          rowsPerPage={rowsPerPage}
          page={page}
          onPageChange={(_, p) => setPage(p)}
          onRowsPerPageChange={(e) => {
            setRowsPerPage(parseInt(e.target.value, 10))
            setPage(0)
          }}
        />
      </Paper>
    </Box>
  )
}

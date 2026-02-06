import { useState } from 'react'
import {
  Box,
  Typography,
  Button,
  Paper,
  Grid,
  Card,
  CardContent,
  TextField,
  InputAdornment,
  Chip,
  IconButton,
  Tooltip,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TablePagination,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Alert,
  Snackbar,
  CircularProgress,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
} from '@mui/material'
import {
  Search,
  Sync,
  CheckCircle,
  Error as ErrorIcon,
  LocalShipping,
  Cancel,
  Refresh,
  Info,
} from '@mui/icons-material'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axiosClient from '../api/axiosClient'
import { ORDERS } from '../api/endpoints'
import { Order, OrderSummary, OrderPlatform, OrderStatus, SyncResult } from '../types/orders'
import { useAuth } from '../hooks/useAuth'

const platformLabels: Record<OrderPlatform, string> = {
  AMAZON: '📦 Amazon',
  EBAY_MEKONG: '🏪 eBay Mekong',
  EBAY_USAV: '🏪 eBay USAV',
  EBAY_DRAGON: '🏪 eBay Dragon',
  ECWID: '🛒 Ecwid',
  ZOHO: '📊 Zoho',
  MANUAL: '✍️ Manual',
}

const statusColors: Record<OrderStatus, 'default' | 'primary' | 'secondary' | 'success' | 'warning' | 'error'> = {
  PENDING: 'warning',
  PROCESSING: 'primary',
  READY_TO_SHIP: 'secondary',
  SHIPPED: 'success',
  CANCELLED: 'default',
  ERROR: 'error',
}

const statusLabels: Record<OrderStatus, string> = {
  PENDING: '⏳ Pending',
  PROCESSING: '⚙️ Processing',
  READY_TO_SHIP: '📦 Ready to Ship',
  SHIPPED: '✅ Shipped',
  CANCELLED: '❌ Cancelled',
  ERROR: '🚨 Error',
}

export default function OrdersManagement() {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  
  const [page, setPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(25)
  const [searchQuery, setSearchQuery] = useState('')
  const [platformFilter, setPlatformFilter] = useState<OrderPlatform | ''>('')
  const [statusFilter, setStatusFilter] = useState<OrderStatus | ''>('')
  const [syncDialogOpen, setSyncDialogOpen] = useState(false)
  const [selectedPlatform, setSelectedPlatform] = useState<OrderPlatform>('ECWID')
  const [syncDate, setSyncDate] = useState(new Date().toISOString().split('T')[0])
  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'success' as 'success' | 'error' | 'info' })

  // Fetch order summary
  const { data: summary } = useQuery<OrderSummary>({
    queryKey: ['orderSummary'],
    queryFn: async () => {
      const response = await axiosClient.get(ORDERS.SUMMARY)
      return response.data
    },
  })

  // Fetch orders
  const { data: ordersData, isLoading } = useQuery({
    queryKey: ['orders', page, rowsPerPage, platformFilter, statusFilter],
    queryFn: async () => {
      const params = new URLSearchParams({
        skip: (page * rowsPerPage).toString(),
        limit: rowsPerPage.toString(),
      })
      if (platformFilter) params.append('platform', platformFilter)
      if (statusFilter) params.append('status', statusFilter)
      
      const response = await axiosClient.get(`${ORDERS.LIST}?${params}`)
      return response.data
    },
  })

  // Sync orders mutation
  const syncMutation = useMutation({
    mutationFn: async ({ platform, date }: { platform: OrderPlatform; date: string }) => {
      const params = date ? `?order_date=${date}` : ''
      const response = await axiosClient.post(`${ORDERS.SYNC(platform)}${params}`)
      return response.data as SyncResult
    },
    onSuccess: (data) => {
      setSnackbar({
        open: true,
        message: `Sync completed: ${data.new_orders} new, ${data.existing_orders} existing, ${data.errors} errors`,
        severity: data.errors > 0 ? 'warning' : 'success',
      })
      queryClient.invalidateQueries({ queryKey: ['orders'] })
      queryClient.invalidateQueries({ queryKey: ['orderSummary'] })
      setSyncDialogOpen(false)
    },
    onError: (error: any) => {
      setSnackbar({
        open: true,
        message: error.response?.data?.detail || 'Sync failed',
        severity: 'error',
      })
    },
  })

  const handleSync = () => {
    syncMutation.mutate({ platform: selectedPlatform, date: syncDate })
  }

  const handleChangePage = (_: unknown, newPage: number) => {
    setPage(newPage)
  }

  const handleChangeRowsPerPage = (event: React.ChangeEvent<HTMLInputElement>) => {
    setRowsPerPage(parseInt(event.target.value, 10))
    setPage(0)
  }

  const filteredOrders = ordersData?.items?.filter((order: Order) => {
    if (!searchQuery) return true
    const query = searchQuery.toLowerCase()
    return (
      order.external_order_id.toLowerCase().includes(query) ||
      order.customer_name?.toLowerCase().includes(query) ||
      order.customer_email?.toLowerCase().includes(query)
    )
  }) || []

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h4">Orders Management</Typography>
        <Button
          variant="contained"
          startIcon={<Sync />}
          onClick={() => setSyncDialogOpen(true)}
          disabled={syncMutation.isPending}
        >
          Sync Orders
        </Button>
      </Box>

      {/* Summary Cards */}
      {summary && (
        <Grid container spacing={2} sx={{ mb: 3 }}>
          <Grid item xs={12} sm={6} md={3}>
            <Card>
              <CardContent>
                <Typography color="text.secondary" gutterBottom>Total Orders</Typography>
                <Typography variant="h4">{summary.total_orders}</Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} sm={6} md={3}>
            <Card>
              <CardContent>
                <Typography color="text.secondary" gutterBottom>Pending</Typography>
                <Typography variant="h4" color="warning.main">{summary.pending_orders}</Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} sm={6} md={3}>
            <Card>
              <CardContent>
                <Typography color="text.secondary" gutterBottom>Ready to Ship</Typography>
                <Typography variant="h4" color="primary.main">{summary.ready_to_ship_orders}</Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} sm={6} md={3}>
            <Card>
              <CardContent>
                <Typography color="text.secondary" gutterBottom>Unmatched Items</Typography>
                <Typography variant="h4" color="error.main">{summary.unmatched_items}</Typography>
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      )}

      {/* Filters */}
      <Paper sx={{ p: 2, mb: 2 }}>
        <Grid container spacing={2} alignItems="center">
          <Grid item xs={12} md={4}>
            <TextField
              fullWidth
              placeholder="Search orders..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start">
                    <Search />
                  </InputAdornment>
                ),
              }}
            />
          </Grid>
          <Grid item xs={12} md={4}>
            <FormControl fullWidth>
              <InputLabel>Platform</InputLabel>
              <Select
                value={platformFilter}
                onChange={(e) => {
                  setPlatformFilter(e.target.value as OrderPlatform | '')
                  setPage(0)
                }}
                label="Platform"
              >
                <MenuItem value="">All Platforms</MenuItem>
                {Object.entries(platformLabels).map(([value, label]) => (
                  <MenuItem key={value} value={value}>{label}</MenuItem>
                ))}
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12} md={4}>
            <FormControl fullWidth>
              <InputLabel>Status</InputLabel>
              <Select
                value={statusFilter}
                onChange={(e) => {
                  setStatusFilter(e.target.value as OrderStatus | '')
                  setPage(0)
                }}
                label="Status"
              >
                <MenuItem value="">All Statuses</MenuItem>
                {Object.entries(statusLabels).map(([value, label]) => (
                  <MenuItem key={value} value={value}>{label}</MenuItem>
                ))}
              </Select>
            </FormControl>
          </Grid>
        </Grid>
      </Paper>

      {/* Orders Table */}
      <Paper>
        <TableContainer>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Order ID</TableCell>
                <TableCell>Platform</TableCell>
                <TableCell>Customer</TableCell>
                <TableCell>Items</TableCell>
                <TableCell>Total</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Ordered</TableCell>
                <TableCell>Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={8} align="center">
                    <CircularProgress />
                  </TableCell>
                </TableRow>
              ) : filteredOrders.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} align="center">
                    No orders found
                  </TableCell>
                </TableRow>
              ) : (
                filteredOrders.map((order: Order) => (
                  <TableRow key={order.id} hover>
                    <TableCell>{order.external_order_number || order.external_order_id}</TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        label={platformLabels[order.platform]}
                      />
                    </TableCell>
                    <TableCell>
                      <Box>
                        <Typography variant="body2">{order.customer_name}</Typography>
                        <Typography variant="caption" color="text.secondary">
                          {order.customer_email}
                        </Typography>
                      </Box>
                    </TableCell>
                    <TableCell>{order.items?.length || 0}</TableCell>
                    <TableCell>
                      {order.currency} {parseFloat(order.total_amount).toFixed(2)}
                    </TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        color={statusColors[order.status]}
                        label={statusLabels[order.status]}
                      />
                    </TableCell>
                    <TableCell>
                      {order.ordered_at 
                        ? new Date(order.ordered_at).toLocaleDateString()
                        : '-'
                      }
                    </TableCell>
                    <TableCell>
                      <Tooltip title="View Details">
                        <IconButton size="small">
                          <Info />
                        </IconButton>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </TableContainer>
        <TablePagination
          rowsPerPageOptions={[10, 25, 50, 100]}
          component="div"
          count={ordersData?.total || 0}
          rowsPerPage={rowsPerPage}
          page={page}
          onPageChange={handleChangePage}
          onRowsPerPageChange={handleChangeRowsPerPage}
        />
      </Paper>

      {/* Sync Dialog */}
      <Dialog open={syncDialogOpen} onClose={() => setSyncDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Sync Orders from Platform</DialogTitle>
        <DialogContent>
          <Box sx={{ mt: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
            <FormControl fullWidth>
              <InputLabel>Platform</InputLabel>
              <Select
                value={selectedPlatform}
                onChange={(e) => setSelectedPlatform(e.target.value as OrderPlatform)}
                label="Platform"
              >
                <MenuItem value="ECWID">🛒 Ecwid</MenuItem>
                <MenuItem value="EBAY_MEKONG">🏪 eBay Mekong</MenuItem>
                <MenuItem value="EBAY_USAV">🏪 eBay USAV</MenuItem>
                <MenuItem value="EBAY_DRAGON">🏪 eBay Dragon</MenuItem>
              </Select>
            </FormControl>
            <TextField
              fullWidth
              type="date"
              label="Order Date"
              value={syncDate}
              onChange={(e) => setSyncDate(e.target.value)}
              InputLabelProps={{ shrink: true }}
              helperText="Select the date to fetch orders from"
            />
            <Alert severity="info">
              This will fetch all orders from the selected platform for the specified date.
              Existing orders will be skipped.
            </Alert>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSyncDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={handleSync}
            variant="contained"
            startIcon={syncMutation.isPending ? <CircularProgress size={20} /> : <Sync />}
            disabled={syncMutation.isPending}
          >
            {syncMutation.isPending ? 'Syncing...' : 'Sync Orders'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Snackbar */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={6000}
        onClose={() => setSnackbar({ ...snackbar, open: false })}
      >
        <Alert
          onClose={() => setSnackbar({ ...snackbar, open: false })}
          severity={snackbar.severity}
          sx={{ width: '100%' }}
        >
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  )
}

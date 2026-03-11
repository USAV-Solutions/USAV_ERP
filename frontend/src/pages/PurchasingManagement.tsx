import { Fragment, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Chip,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid,
  MenuItem,
  Paper,
  Snackbar,
  Stack,
  IconButton,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
  LinearProgress,
} from '@mui/material'
import { Add, CloudSync, KeyboardArrowDown, KeyboardArrowUp } from '@mui/icons-material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  createPurchaseOrder,
  createVendor,
  importPurchasesFromZoho,
  listPurchaseOrders,
  listPurchaseOrdersPaged,
  listVendors,
} from '../api/purchasing'
import { forceSyncPurchase } from '../api/sync'
import type {
  PurchaseOrder,
  PurchaseOrderCreate,
  VendorCreate,
} from '../types/purchasing'
import { useAuth } from '../hooks/useAuth'

const statusColor = {
  CREATED: 'default',
  BILLED: 'warning',
  DELIVERED: 'success',
} as const

const itemStatusColor = {
  UNMATCHED: 'error',
  MATCHED: 'info',
  RECEIVED: 'success',
} as const

export default function PurchasingManagement() {
  const queryClient = useQueryClient()
  const { hasRole } = useAuth()

  const [selectedPoId, setSelectedPoId] = useState<number | null>(null)
  const [createVendorOpen, setCreateVendorOpen] = useState(false)
  const [createPoOpen, setCreatePoOpen] = useState(false)
  const [bulkDialogOpen, setBulkDialogOpen] = useState(false)
  const [bulkLoading, setBulkLoading] = useState(false)
  const [bulkError, setBulkError] = useState<string | null>(null)
  const [bulkTotal, setBulkTotal] = useState(0)
  const [bulkProgress, setBulkProgress] = useState({ queued: 0, success: 0, failed: 0 })
  const [bulkDone, setBulkDone] = useState(false)
  const [syncingPoId, setSyncingPoId] = useState<number | null>(null)
  const [expandedPoId, setExpandedPoId] = useState<number | null>(null)
  const [snackbar, setSnackbar] = useState<{ open: boolean; msg: string; severity: 'success' | 'error' }>({
    open: false,
    msg: '',
    severity: 'success',
  })

  const [vendorForm, setVendorForm] = useState<VendorCreate>({ name: '', is_active: true })
  const [poForm, setPoForm] = useState<PurchaseOrderCreate>({
    po_number: '',
    vendor_id: 0,
    order_date: new Date().toISOString().slice(0, 10),
    total_amount: 0,
    currency: 'USD',
    notes: '',
    items: [],
  })

  const { data: vendors = [] } = useQuery({ queryKey: ['vendors'], queryFn: listVendors })
  const { data: orders = [], isLoading: loadingOrders } = useQuery({
    queryKey: ['purchases'],
    queryFn: listPurchaseOrders,
  })

  const createVendorMutation = useMutation({
    mutationFn: createVendor,
    onSuccess: async () => {
      setCreateVendorOpen(false)
      setVendorForm({ name: '', is_active: true })
      await queryClient.invalidateQueries({ queryKey: ['vendors'] })
      setSnackbar({ open: true, msg: 'Vendor created.', severity: 'success' })
    },
    onError: () => setSnackbar({ open: true, msg: 'Failed to create vendor.', severity: 'error' }),
  })

  const createPoMutation = useMutation({
    mutationFn: createPurchaseOrder,
    onSuccess: async (po) => {
      setCreatePoOpen(false)
      setPoForm({
        po_number: '',
        vendor_id: 0,
        order_date: new Date().toISOString().slice(0, 10),
        total_amount: 0,
        currency: 'USD',
        notes: '',
        items: [],
      })
      setSelectedPoId(po.id)
      await queryClient.invalidateQueries({ queryKey: ['purchases'] })
      setSnackbar({ open: true, msg: 'Purchase order created.', severity: 'success' })
    },
    onError: () => setSnackbar({ open: true, msg: 'Failed to create purchase order.', severity: 'error' }),
  })

  const importZohoMutation = useMutation({
    mutationFn: importPurchasesFromZoho,
    onSuccess: async (res) => {
      await queryClient.invalidateQueries({ queryKey: ['vendors'] })
      await queryClient.invalidateQueries({ queryKey: ['purchases'] })
      setSnackbar({
        open: true,
        severity: 'success',
        msg:
          `Zoho import done: ${res.purchase_orders_created} PO created, ${res.purchase_orders_updated} PO updated, ` +
          `${res.vendors_created} vendor created, ${res.vendors_updated} vendor updated.`,
      })
    },
    onError: () => {
      setSnackbar({ open: true, msg: 'Failed to import purchasing list from Zoho.', severity: 'error' })
    },
  })

  const forceSyncPoMutation = useMutation({
    mutationFn: (poId: number) => forceSyncPurchase(poId),
    onMutate: (poId) => setSyncingPoId(poId),
    onSuccess: (_data, poId) => {
      setSnackbar({ open: true, msg: `Purchase order #${poId} queued for Zoho sync.`, severity: 'success' })
      setSyncingPoId(null)
    },
    onError: (error: { response?: { data?: { detail?: string } }; message?: string }, poId) => {
      const detail = error.response?.data?.detail || error.message || 'Sync failed.'
      setSnackbar({ open: true, msg: `Purchase order #${poId}: ${detail}`, severity: 'error' })
      setSyncingPoId(null)
    },
  })

  const canSyncPo = (po: PurchaseOrder) =>
    po.items.length > 0 && po.items.every((item) => item.status !== 'UNMATCHED' && !!item.variant_id)

  const handleBulkSync = async () => {
    setBulkLoading(true)
    setBulkError(null)
    setBulkDone(false)
    setBulkProgress({ queued: 0, success: 0, failed: 0 })

    try {
      const pageSize = 200
      let skip = 0
      let eligibleIds: number[] = []

      // eslint-disable-next-line no-constant-condition
      while (true) {
        const batch = await listPurchaseOrdersPaged({ skip, limit: pageSize })
        const matched = batch.filter((po) => canSyncPo(po)).map((po) => po.id)
        eligibleIds = eligibleIds.concat(matched)

        if (batch.length < pageSize || eligibleIds.length >= 2000) {
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
      for (const poId of eligibleIds) {
        try {
          await forceSyncPurchase(poId)
          setBulkProgress((p) => ({ queued: p.queued + 1, success: p.success + 1, failed: p.failed }))
        } catch (err: any) {
          setBulkProgress((p) => ({ queued: p.queued + 1, success: p.success, failed: p.failed + 1 }))
          if (!firstError) {
            firstError = err?.response?.data?.detail || err?.message || 'One or more purchase orders failed to queue.'
          }
        }
      }

      if (firstError) {
        setBulkError(firstError)
      }

      setBulkDone(true)
      await queryClient.invalidateQueries({ queryKey: ['purchases'] })
    } catch (err: any) {
      setBulkError(err?.message || 'Failed to load purchase orders for bulk sync.')
    } finally {
      setBulkLoading(false)
    }
  }

  const bulkPercent = bulkTotal ? Math.min(Math.round((bulkProgress.queued / bulkTotal) * 100), 100) : 0

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h4">Purchasing</Typography>
        <Stack direction="row" spacing={1}>
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
          <Button
            variant="outlined"
            onClick={() => importZohoMutation.mutate()}
            disabled={importZohoMutation.isPending}
          >
            {importZohoMutation.isPending ? 'Importing...' : 'Import from Zoho'}
          </Button>
          <Button startIcon={<Add />} variant="outlined" onClick={() => setCreateVendorOpen(true)}>
            Add Vendor
          </Button>
          <Button startIcon={<Add />} variant="contained" onClick={() => setCreatePoOpen(true)}>
            Create PO
          </Button>
        </Stack>
      </Box>

      <Grid container spacing={2}>
        <Grid item xs={12}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" sx={{ mb: 1 }}>
              Purchase Orders
            </Typography>
            {loadingOrders ? (
              <Typography variant="body2">Loading...</Typography>
            ) : (
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell sx={{ width: 44 }} />
                      <TableCell>PO #</TableCell>
                      <TableCell>Vendor</TableCell>
                      <TableCell>Status</TableCell>
                      <TableCell align="center">Items</TableCell>
                      <TableCell align="right">Total</TableCell>
                      {hasRole(['ADMIN']) && <TableCell align="center">Zoho</TableCell>}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {orders.map((po) => {
                      const expanded = expandedPoId === po.id
                      return (
                        <Fragment key={po.id}>
                          <TableRow
                            hover
                            selected={selectedPoId === po.id}
                            onClick={() => {
                              setSelectedPoId(po.id)
                              setExpandedPoId(expanded ? null : po.id)
                            }}
                            sx={{ cursor: 'pointer', '& > *': { borderBottom: expanded ? 'unset' : undefined } }}
                          >
                            <TableCell sx={{ px: 1 }}>
                              <IconButton size="small">
                                {expanded ? <KeyboardArrowUp /> : <KeyboardArrowDown />}
                              </IconButton>
                            </TableCell>
                            <TableCell>{po.po_number}</TableCell>
                            <TableCell>{po.vendor?.name || po.vendor_id}</TableCell>
                            <TableCell>
                              <Chip size="small" color={statusColor[po.deliver_status]} label={po.deliver_status} />
                            </TableCell>
                            <TableCell align="center">{po.items?.length ?? 0}</TableCell>
                            <TableCell align="right">
                              {po.total_amount} {po.currency}
                            </TableCell>
                            {hasRole(['ADMIN']) && (
                              <TableCell align="center">
                                <Button
                                  size="small"
                                  variant="outlined"
                                  startIcon={syncingPoId === po.id ? <CircularProgress size={14} /> : <CloudSync />}
                                  disabled={!canSyncPo(po) || syncingPoId === po.id}
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    forceSyncPoMutation.mutate(po.id)
                                  }}
                                >
                                  Sync
                                </Button>
                              </TableCell>
                            )}
                          </TableRow>
                          <TableRow>
                            <TableCell colSpan={hasRole(['ADMIN']) ? 7 : 6} sx={{ py: 0 }}>
                              <Collapse in={expanded} timeout="auto" unmountOnExit>
                                <Box sx={{ p: 1.5, bgcolor: 'action.hover' }}>
                                  <Typography variant="subtitle2" sx={{ mb: 1 }}>
                                    Line Items
                                  </Typography>
                                  <Table size="small">
                                    <TableHead>
                                      <TableRow>
                                        <TableCell>Item Name</TableCell>
                                        <TableCell>Item SKU</TableCell>
                                        <TableCell align="center">Qty</TableCell>
                                        <TableCell align="center">Status</TableCell>
                                      </TableRow>
                                    </TableHead>
                                    <TableBody>
                                      {(po.items || []).map((item) => (
                                        <TableRow key={item.id}>
                                          <TableCell>{item.external_item_name}</TableCell>
                                          <TableCell>{item.variant_sku || '-'}</TableCell>
                                          <TableCell align="center">{item.quantity}</TableCell>
                                          <TableCell align="center">
                                            <Chip size="small" color={itemStatusColor[item.status]} label={item.status} />
                                          </TableCell>
                                        </TableRow>
                                      ))}
                                      {!po.items?.length && (
                                        <TableRow>
                                          <TableCell colSpan={4} align="center">
                                            No line items.
                                          </TableCell>
                                        </TableRow>
                                      )}
                                    </TableBody>
                                  </Table>
                                </Box>
                              </Collapse>
                            </TableCell>
                          </TableRow>
                        </Fragment>
                      )
                    })}
                  </TableBody>
                </Table>
              </TableContainer>
            )}
          </Paper>
        </Grid>
      </Grid>

      <Dialog open={createVendorOpen} onClose={() => setCreateVendorOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Add Vendor</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label="Name"
              value={vendorForm.name}
              onChange={(e) => setVendorForm((prev) => ({ ...prev, name: e.target.value }))}
              required
            />
            <TextField
              label="Email"
              value={vendorForm.email || ''}
              onChange={(e) => setVendorForm((prev) => ({ ...prev, email: e.target.value }))}
            />
            <TextField
              label="Phone"
              value={vendorForm.phone || ''}
              onChange={(e) => setVendorForm((prev) => ({ ...prev, phone: e.target.value }))}
            />
            <TextField
              label="Address"
              value={vendorForm.address || ''}
              onChange={(e) => setVendorForm((prev) => ({ ...prev, address: e.target.value }))}
              multiline
              minRows={2}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateVendorOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={!vendorForm.name}
            onClick={() => createVendorMutation.mutate(vendorForm)}
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={createPoOpen} onClose={() => setCreatePoOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Create Purchase Order</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label="PO Number"
              value={poForm.po_number}
              onChange={(e) => setPoForm((prev) => ({ ...prev, po_number: e.target.value }))}
              required
            />
            <TextField
              select
              label="Vendor"
              value={poForm.vendor_id || ''}
              onChange={(e) => setPoForm((prev) => ({ ...prev, vendor_id: Number(e.target.value) }))}
              required
            >
              {vendors.map((v) => (
                <MenuItem key={v.id} value={v.id}>
                  {v.name}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              label="Order Date"
              type="date"
              value={poForm.order_date}
              onChange={(e) => setPoForm((prev) => ({ ...prev, order_date: e.target.value }))}
              InputLabelProps={{ shrink: true }}
            />
            <TextField
              label="Expected Delivery Date"
              type="date"
              value={poForm.expected_delivery_date || ''}
              onChange={(e) =>
                setPoForm((prev) => ({ ...prev, expected_delivery_date: e.target.value || undefined }))
              }
              InputLabelProps={{ shrink: true }}
            />
            <TextField
              label="Total Amount"
              type="number"
              value={poForm.total_amount}
              onChange={(e) => setPoForm((prev) => ({ ...prev, total_amount: Number(e.target.value) }))}
            />
            <TextField
              label="Currency"
              value={poForm.currency || 'USD'}
              onChange={(e) => setPoForm((prev) => ({ ...prev, currency: e.target.value }))}
            />
            <TextField
              label="Notes"
              value={poForm.notes || ''}
              onChange={(e) => setPoForm((prev) => ({ ...prev, notes: e.target.value }))}
              multiline
              minRows={2}
            />
            <Alert severity="info">Create PO first. Line items can be loaded from integrations and matched below.</Alert>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreatePoOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={!poForm.po_number || !poForm.vendor_id || !poForm.order_date}
            onClick={() => createPoMutation.mutate(poForm)}
          >
            Create
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog
        open={bulkDialogOpen}
        onClose={bulkLoading ? undefined : () => setBulkDialogOpen(false)}
        fullWidth
        maxWidth="sm"
      >
        <DialogTitle>Sync matched purchase orders to Zoho</DialogTitle>
        <DialogContent dividers>
          <Stack spacing={2}>
            <Typography variant="body2" color="text.secondary">
              Only purchase orders with no unmatched items are queued.
            </Typography>
            <Stack spacing={1}>
              <Typography variant="body2">Eligible purchase orders: {bulkTotal}</Typography>
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
                Queueing matched purchase orders to Zoho...
              </Alert>
            )}
            {bulkDone && !bulkLoading && !bulkError && bulkTotal > 0 && (
              <Alert severity="success">All matched purchase orders queued successfully.</Alert>
            )}
            {bulkDone && !bulkLoading && bulkTotal === 0 && (
              <Alert severity="info">No matched purchase orders found to sync.</Alert>
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
            {bulkLoading ? 'Syncing...' : 'Start sync'}
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={snackbar.open}
        autoHideDuration={4000}
        onClose={() => setSnackbar((prev) => ({ ...prev, open: false }))}
      >
        <Alert severity={snackbar.severity} sx={{ width: '100%' }}>
          {snackbar.msg}
        </Alert>
      </Snackbar>
    </Box>
  )
}

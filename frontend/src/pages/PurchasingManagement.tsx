import { useMemo, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid,
  MenuItem,
  Paper,
  Snackbar,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import { Add, Done } from '@mui/icons-material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  createPurchaseOrder,
  createVendor,
  getPurchaseOrder,
  importPurchasesFromZoho,
  listPurchaseOrders,
  listVendors,
  markPurchaseDelivered,
  matchPurchaseItem,
} from '../api/purchasing'
import type {
  ItemReceipt,
  PurchaseOrder,
  PurchaseOrderCreate,
  PurchaseOrderItem,
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
  const [receiveOpen, setReceiveOpen] = useState(false)
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

  const [matchVariantByItemId, setMatchVariantByItemId] = useState<Record<number, string>>({})
  const [receiptByItemId, setReceiptByItemId] = useState<Record<number, ItemReceipt>>({})

  const { data: vendors = [] } = useQuery({ queryKey: ['vendors'], queryFn: listVendors })
  const { data: orders = [], isLoading: loadingOrders } = useQuery({
    queryKey: ['purchases'],
    queryFn: listPurchaseOrders,
  })

  const { data: selectedOrder, isLoading: loadingPoDetail } = useQuery<PurchaseOrder>({
    queryKey: ['purchase', selectedPoId],
    queryFn: () => getPurchaseOrder(selectedPoId as number),
    enabled: selectedPoId !== null,
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
      await queryClient.invalidateQueries({ queryKey: ['purchase', po.id] })
      setSnackbar({ open: true, msg: 'Purchase order created.', severity: 'success' })
    },
    onError: () => setSnackbar({ open: true, msg: 'Failed to create purchase order.', severity: 'error' }),
  })

  const matchMutation = useMutation({
    mutationFn: ({ itemId, variantId }: { itemId: number; variantId: number }) =>
      matchPurchaseItem(itemId, { variant_id: variantId }),
    onSuccess: async (_row, vars) => {
      if (selectedPoId) {
        await queryClient.invalidateQueries({ queryKey: ['purchase', selectedPoId] })
        await queryClient.invalidateQueries({ queryKey: ['purchases'] })
      }
      setMatchVariantByItemId((prev) => ({ ...prev, [vars.itemId]: '' }))
      setSnackbar({ open: true, msg: 'PO item matched.', severity: 'success' })
    },
    onError: () => setSnackbar({ open: true, msg: 'Failed to match item.', severity: 'error' }),
  })

  const receiveMutation = useMutation({
    mutationFn: ({ poId, payload }: { poId: number; payload: { items: ItemReceipt[] } }) =>
      markPurchaseDelivered(poId, payload),
    onSuccess: async (res) => {
      if (selectedPoId) {
        await queryClient.invalidateQueries({ queryKey: ['purchase', selectedPoId] })
        await queryClient.invalidateQueries({ queryKey: ['purchases'] })
      }
      setReceiveOpen(false)
      setSnackbar({
        open: true,
        msg: `PO delivered. Added ${res.created_inventory_item_ids.length} inventory units.`,
        severity: 'success',
      })
    },
    onError: () => setSnackbar({ open: true, msg: 'Failed to mark PO delivered.', severity: 'error' }),
  })

  const importZohoMutation = useMutation({
    mutationFn: importPurchasesFromZoho,
    onSuccess: async (res) => {
      await queryClient.invalidateQueries({ queryKey: ['vendors'] })
      await queryClient.invalidateQueries({ queryKey: ['purchases'] })
      if (selectedPoId) {
        await queryClient.invalidateQueries({ queryKey: ['purchase', selectedPoId] })
      }
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

  const activeReceipts = useMemo(() => {
    if (!selectedOrder) return []
    return selectedOrder.items.map((item) => {
      const current = receiptByItemId[item.id]
      return (
        current || {
          purchase_order_item_id: item.id,
          quantity_received: item.quantity,
          serial_numbers: [],
          location_code: '',
        }
      )
    })
  }, [receiptByItemId, selectedOrder])

  const handleOpenReceive = () => {
    if (!selectedOrder) return
    const initial: Record<number, ItemReceipt> = {}
    selectedOrder.items.forEach((item) => {
      initial[item.id] = {
        purchase_order_item_id: item.id,
        quantity_received: item.quantity,
        serial_numbers: [],
        location_code: '',
      }
    })
    setReceiptByItemId(initial)
    setReceiveOpen(true)
  }

  const handleSubmitReceive = () => {
    if (!selectedPoId) return
    receiveMutation.mutate({ poId: selectedPoId, payload: { items: activeReceipts } })
  }

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h4">Purchasing</Typography>
        <Stack direction="row" spacing={1}>
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
        <Grid item xs={12} md={5}>
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
                      <TableCell>PO #</TableCell>
                      <TableCell>Vendor</TableCell>
                      <TableCell>Status</TableCell>
                      <TableCell align="right">Total</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {orders.map((po) => (
                      <TableRow
                        key={po.id}
                        hover
                        selected={selectedPoId === po.id}
                        onClick={() => setSelectedPoId(po.id)}
                        sx={{ cursor: 'pointer' }}
                      >
                        <TableCell>{po.po_number}</TableCell>
                        <TableCell>{po.vendor?.name || po.vendor_id}</TableCell>
                        <TableCell>
                          <Chip size="small" color={statusColor[po.deliver_status]} label={po.deliver_status} />
                        </TableCell>
                        <TableCell align="right">
                          {po.total_amount} {po.currency}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            )}
          </Paper>
        </Grid>

        <Grid item xs={12} md={7}>
          <Paper sx={{ p: 2 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
              <Typography variant="h6">PO Details</Typography>
              {selectedOrder && selectedOrder.deliver_status !== 'DELIVERED' && hasRole(['ADMIN', 'WAREHOUSE_OP']) && (
                <Button variant="contained" color="success" startIcon={<Done />} onClick={handleOpenReceive}>
                  Mark Delivered
                </Button>
              )}
            </Box>

            {!selectedPoId ? (
              <Typography variant="body2" color="text.secondary">
                Select a purchase order to view line items and matching status.
              </Typography>
            ) : loadingPoDetail ? (
              <Typography variant="body2">Loading order details...</Typography>
            ) : !selectedOrder ? (
              <Alert severity="warning">Unable to load purchase order details.</Alert>
            ) : (
              <>
                <Typography variant="body2" sx={{ mb: 1 }}>
                  Vendor: <strong>{selectedOrder.vendor?.name || selectedOrder.vendor_id}</strong>
                </Typography>
                <Typography variant="body2" sx={{ mb: 2 }}>
                  Notes: {selectedOrder.notes || 'N/A'}
                </Typography>

                <TableContainer>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>Item</TableCell>
                        <TableCell>Qty</TableCell>
                        <TableCell>Status</TableCell>
                        <TableCell>Variant ID</TableCell>
                        <TableCell>Match</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {selectedOrder.items.map((item: PurchaseOrderItem) => (
                        <TableRow key={item.id}>
                          <TableCell>{item.external_item_name}</TableCell>
                          <TableCell>{item.quantity}</TableCell>
                          <TableCell>
                            <Chip size="small" color={itemStatusColor[item.status]} label={item.status} />
                          </TableCell>
                          <TableCell>{item.variant_id ?? '-'}</TableCell>
                          <TableCell>
                            <Stack direction="row" spacing={1}>
                              <TextField
                                size="small"
                                type="number"
                                placeholder="variant_id"
                                value={matchVariantByItemId[item.id] || ''}
                                onChange={(e) =>
                                  setMatchVariantByItemId((prev) => ({ ...prev, [item.id]: e.target.value }))
                                }
                                sx={{ width: 120 }}
                              />
                              <Button
                                size="small"
                                variant="outlined"
                                disabled={!matchVariantByItemId[item.id] || item.status === 'RECEIVED'}
                                onClick={() =>
                                  matchMutation.mutate({
                                    itemId: item.id,
                                    variantId: Number(matchVariantByItemId[item.id]),
                                  })
                                }
                              >
                                Match
                              </Button>
                            </Stack>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              </>
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

      <Dialog open={receiveOpen} onClose={() => setReceiveOpen(false)} fullWidth maxWidth="md">
        <DialogTitle>Receive Purchase Order</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            {activeReceipts.map((receipt) => {
              const item = selectedOrder?.items.find((x) => x.id === receipt.purchase_order_item_id)
              return (
                <Paper key={receipt.purchase_order_item_id} variant="outlined" sx={{ p: 2 }}>
                  <Typography variant="subtitle2" sx={{ mb: 1 }}>
                    {item?.external_item_name}
                  </Typography>
                  <Grid container spacing={1}>
                    <Grid item xs={12} sm={3}>
                      <TextField
                        fullWidth
                        size="small"
                        type="number"
                        label="Quantity Received"
                        value={receipt.quantity_received}
                        onChange={(e) =>
                          setReceiptByItemId((prev) => ({
                            ...prev,
                            [receipt.purchase_order_item_id]: {
                              ...receipt,
                              quantity_received: Number(e.target.value),
                            },
                          }))
                        }
                      />
                    </Grid>
                    <Grid item xs={12} sm={4}>
                      <TextField
                        fullWidth
                        size="small"
                        label="Location Code"
                        value={receipt.location_code || ''}
                        onChange={(e) =>
                          setReceiptByItemId((prev) => ({
                            ...prev,
                            [receipt.purchase_order_item_id]: {
                              ...receipt,
                              location_code: e.target.value,
                            },
                          }))
                        }
                      />
                    </Grid>
                    <Grid item xs={12} sm={5}>
                      <TextField
                        fullWidth
                        size="small"
                        label="Serial Numbers (comma-separated)"
                        value={receipt.serial_numbers.join(',')}
                        onChange={(e) =>
                          setReceiptByItemId((prev) => ({
                            ...prev,
                            [receipt.purchase_order_item_id]: {
                              ...receipt,
                              serial_numbers: e.target.value
                                .split(',')
                                .map((s) => s.trim())
                                .filter(Boolean),
                            },
                          }))
                        }
                      />
                    </Grid>
                  </Grid>
                </Paper>
              )
            })}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setReceiveOpen(false)}>Cancel</Button>
          <Button variant="contained" color="success" onClick={handleSubmitReceive}>
            Confirm Delivery
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

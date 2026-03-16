import { ChangeEvent, Fragment, useRef, useState } from 'react'
import {
  Alert,
  Autocomplete,
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
  Paper,
  Snackbar,
  Stack,
  IconButton,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  TextField,
  Typography,
  LinearProgress,
} from '@mui/material'
import {
  Add,
  CloudSync,
  DeleteOutline,
  KeyboardArrowDown,
  KeyboardArrowUp,
  Link as LinkIcon,
} from '@mui/icons-material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  addPurchaseOrderItem,
  createPurchaseOrder,
  createVendor,
  deletePurchaseItem,
  importPurchasesFromGoodwillCsv,
  importOneRandomPurchaseFromZoho,
  importPurchasesFromZoho,
  listPurchaseOrdersPaged,
  listVendors,
  matchPurchaseItem,
  updatePurchaseItem,
} from '../api/purchasing'
import { forceSyncPurchase } from '../api/sync'
import type {
  PurchaseOrder,
  PurchaseOrderCreate,
  PurchaseOrderItem,
  VendorCreate,
} from '../types/purchasing'
import { useAuth } from '../hooks/useAuth'
import VariantSearchAutocomplete from '../components/common/VariantSearchAutocomplete'
import HoldActionPromptDialog from '../components/common/HoldActionPromptDialog'
import LongPressTableRow from '../components/common/LongPressTableRow'
import type { VariantSearchResult } from '../types/orders'

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

interface PurchaseOrderItemRowProps {
  item: PurchaseOrderItem
  onChanged: () => Promise<void>
  onNotify: (msg: string, severity: 'success' | 'error') => void
}

interface AddPurchaseOrderItemRowProps {
  poId: number
  onChanged: () => Promise<void>
  onNotify: (msg: string, severity: 'success' | 'error') => void
  onDone: () => void
}

function AddPurchaseOrderItemRow({ poId, onChanged, onNotify, onDone }: AddPurchaseOrderItemRowProps) {
  const [externalItemId, setExternalItemId] = useState('')
  const [externalItemName, setExternalItemName] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [unitPrice, setUnitPrice] = useState('0')
  const [selectedVariant, setSelectedVariant] = useState<VariantSearchResult | null>(null)

  const parsedQuantity = Number(quantity) || 0
  const parsedUnitPrice = Number(unitPrice) || 0
  const computedTotal = Math.max(parsedQuantity, 0) * Math.max(parsedUnitPrice, 0)

  const addItemMutation = useMutation({
    mutationFn: () =>
      addPurchaseOrderItem(poId, {
        external_item_id: externalItemId.trim() || undefined,
        external_item_name: externalItemName.trim(),
        quantity: parsedQuantity,
        unit_price: parsedUnitPrice,
        total_price: computedTotal,
        variant_id: selectedVariant?.id,
      }),
    onSuccess: async () => {
      setExternalItemId('')
      setExternalItemName('')
      setQuantity('1')
      setUnitPrice('0')
      setSelectedVariant(null)
      await onChanged()
      onNotify('Line item created.', 'success')
      onDone()
    },
    onError: (error: { response?: { data?: { detail?: string } }; message?: string }) => {
      onNotify(error.response?.data?.detail || error.message || 'Failed to create line item.', 'error')
    },
  })

  const createDisabled =
    addItemMutation.isPending || !externalItemName.trim() || parsedQuantity <= 0 || parsedUnitPrice < 0

  return (
    <>
      <TableRow sx={{ backgroundColor: 'background.paper' }}>
        <TableCell>
          <TextField
            size="small"
            value={externalItemId}
            onChange={(e) => setExternalItemId(e.target.value)}
            placeholder="Optional"
            fullWidth
          />
        </TableCell>
        <TableCell>
          <TextField
            size="small"
            value={externalItemName}
            onChange={(e) => setExternalItemName(e.target.value)}
            placeholder="New line item name"
            fullWidth
            required
          />
        </TableCell>
        <TableCell>{selectedVariant?.full_sku || '-'}</TableCell>
        <TableCell align="center">
          <TextField
            size="small"
            type="number"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            inputProps={{ min: 1, step: 1 }}
            sx={{ width: 90 }}
          />
        </TableCell>
        <TableCell align="right">
          <TextField
            size="small"
            type="number"
            value={unitPrice}
            onChange={(e) => setUnitPrice(e.target.value)}
            inputProps={{ min: 0, step: 0.01 }}
            sx={{ width: 120 }}
          />
        </TableCell>
        <TableCell align="center">
          <Chip size="small" color="default" label="NEW" />
        </TableCell>
        <TableCell align="center">
          <Stack direction="row" spacing={1} justifyContent="center">
            <Button
              size="small"
              variant="contained"
              onClick={() => addItemMutation.mutate()}
              disabled={createDisabled}
            >
              {addItemMutation.isPending ? 'Adding...' : 'Add Line'}
            </Button>
            <Button size="small" onClick={onDone} disabled={addItemMutation.isPending}>
              Cancel
            </Button>
          </Stack>
        </TableCell>
      </TableRow>
      <TableRow sx={{ backgroundColor: 'background.paper' }}>
        <TableCell colSpan={7}>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} alignItems={{ xs: 'stretch', md: 'center' }}>
            <VariantSearchAutocomplete value={selectedVariant} onChange={setSelectedVariant} />
            <Typography variant="body2" color="text.secondary">
              Total Price (auto): {computedTotal.toFixed(2)}
            </Typography>
          </Stack>
        </TableCell>
      </TableRow>
    </>
  )
}

function PurchaseOrderItemRow({ item, onChanged, onNotify }: PurchaseOrderItemRowProps) {
  const [promptOpen, setPromptOpen] = useState(false)
  const [showMatch, setShowMatch] = useState(false)
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)
  const [selectedVariant, setSelectedVariant] = useState<VariantSearchResult | null>(null)
  const [externalItemId, setExternalItemId] = useState(item.external_item_id || '')
  const [externalItemName, setExternalItemName] = useState(item.external_item_name)
  const [quantity, setQuantity] = useState(String(item.quantity))
  const [unitPrice, setUnitPrice] = useState(String(item.unit_price))

  const parsedQuantity = Number(quantity) || 0
  const parsedUnitPrice = Number(unitPrice) || 0
  const computedTotalPrice = Math.max(parsedQuantity, 0) * Math.max(parsedUnitPrice, 0)

  const saveMutation = useMutation({
    mutationFn: () =>
      updatePurchaseItem(item.id, {
        external_item_id: externalItemId.trim() || null,
        external_item_name: externalItemName.trim(),
        quantity: parsedQuantity,
        unit_price: parsedUnitPrice,
        total_price: computedTotalPrice,
        variant_id: selectedVariant ? selectedVariant.id : item.variant_id ?? undefined,
      }),
    onSuccess: async () => {
      setPromptOpen(false)
      await onChanged()
      onNotify('Item updated successfully.', 'success')
    },
    onError: (error: { response?: { data?: { detail?: string } }; message?: string }) => {
      onNotify(error.response?.data?.detail || error.message || 'Failed to update item.', 'error')
    },
  })

  const matchMutation = useMutation({
    mutationFn: () =>
      matchPurchaseItem(item.id, {
        variant_id: selectedVariant!.id,
      }),
    onSuccess: async () => {
      setShowMatch(false)
      setSelectedVariant(null)
      await onChanged()
      onNotify('Item matched successfully.', 'success')
    },
    onError: (error: { response?: { data?: { detail?: string } }; message?: string }) => {
      onNotify(error.response?.data?.detail || error.message || 'Failed to match item.', 'error')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => deletePurchaseItem(item.id),
    onSuccess: async () => {
      await onChanged()
      onNotify('Item deleted.', 'success')
    },
    onError: (error: { response?: { data?: { detail?: string } }; message?: string }) => {
      onNotify(error.response?.data?.detail || error.message || 'Failed to delete item.', 'error')
    },
  })

  const anyPending = saveMutation.isPending || deleteMutation.isPending || matchMutation.isPending

  const openPrompt = () => {
    setExternalItemId(item.external_item_id || '')
    setExternalItemName(item.external_item_name)
    setQuantity(String(item.quantity))
    setUnitPrice(String(item.unit_price))
    setSelectedVariant(null)
    setPromptOpen(true)
  }

  return (
    <>
      <LongPressTableRow payload={item} onLongPress={openPrompt} rowSx={{ cursor: 'pointer' }}>
        <TableCell>{item.external_item_id || '-'}</TableCell>
        <TableCell>{item.external_item_name}</TableCell>
        <TableCell>{item.variant_sku || '-'}</TableCell>
        <TableCell align="center">{item.quantity}</TableCell>
        <TableCell align="right">{item.unit_price}</TableCell>
        <TableCell align="center">
          <Chip size="small" color={itemStatusColor[item.status]} label={item.status} />
        </TableCell>
        <TableCell align="center">
          <Stack direction="row" spacing={0.5} justifyContent="center">
            {item.status === 'UNMATCHED' && (
              <IconButton
                size="small"
                color="primary"
                disabled={anyPending}
                onClick={(event) => {
                  event.stopPropagation()
                  setShowMatch((prev) => !prev)
                }}
              >
                <LinkIcon fontSize="small" />
              </IconButton>
            )}
            <IconButton
              size="small"
              color="error"
              disabled={item.status === 'RECEIVED' || anyPending}
              onClick={(event) => {
                event.stopPropagation()
                setDeleteConfirmOpen(true)
              }}
            >
              <DeleteOutline fontSize="small" />
            </IconButton>
          </Stack>
        </TableCell>
      </LongPressTableRow>

      {showMatch && (
        <TableRow>
          <TableCell colSpan={7} sx={{ py: 1, backgroundColor: 'background.paper' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, pl: 1 }}>
              <VariantSearchAutocomplete value={selectedVariant} onChange={setSelectedVariant} />
              <Button
                size="small"
                variant="contained"
                onClick={() => matchMutation.mutate()}
                disabled={!selectedVariant || matchMutation.isPending}
                startIcon={matchMutation.isPending ? <CircularProgress size={14} /> : <LinkIcon />}
              >
                Match
              </Button>
              <Button size="small" onClick={() => setShowMatch(false)}>
                Cancel
              </Button>
            </Box>
          </TableCell>
        </TableRow>
      )}

      <HoldActionPromptDialog
        open={promptOpen}
        onClose={() => setPromptOpen(false)}
        title="Edit Purchase Item"
        onSave={() => saveMutation.mutate()}
        onDelete={() => deleteMutation.mutate()}
        saveDisabled={item.status === 'RECEIVED' || !externalItemName.trim() || Number(quantity) <= 0}
        deleteDisabled={item.status === 'RECEIVED'}
        saveLoading={saveMutation.isPending}
        deleteLoading={deleteMutation.isPending}
        deleteConfirmTitle="Delete Purchase Item"
        deleteConfirmMessage={
          <Typography>
            Delete item <strong>{item.external_item_name}</strong>? This action cannot be undone.
          </Typography>
        }
      >
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField label="Item ID" value={externalItemId} onChange={(e) => setExternalItemId(e.target.value)} fullWidth />
          <TextField label="Item Name" value={externalItemName} onChange={(e) => setExternalItemName(e.target.value)} fullWidth />
          <TextField label="Quantity" type="number" value={quantity} onChange={(e) => setQuantity(e.target.value)} fullWidth />
          <TextField label="Unit Price" type="number" value={unitPrice} onChange={(e) => setUnitPrice(e.target.value)} fullWidth />
          <TextField
            label="Total Price (Auto)"
            type="number"
            value={computedTotalPrice.toFixed(2)}
            InputProps={{ readOnly: true }}
            fullWidth
          />
          <VariantSearchAutocomplete value={selectedVariant} onChange={setSelectedVariant} />
          <Typography variant="caption" color="text.secondary">
            Current SKU: {item.variant_sku || 'Unmatched'}
          </Typography>
        </Stack>
      </HoldActionPromptDialog>

      <Dialog open={deleteConfirmOpen} onClose={() => setDeleteConfirmOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle>Delete Purchase Item</DialogTitle>
        <DialogContent>
          <Typography>
            Delete item <strong>{item.external_item_name}</strong>? This action cannot be undone.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteConfirmOpen(false)} disabled={deleteMutation.isPending}>
            Cancel
          </Button>
          <Button
            color="error"
            variant="contained"
            disabled={deleteMutation.isPending}
            onClick={() => {
              deleteMutation.mutate(undefined, {
                onSuccess: () => {
                  setDeleteConfirmOpen(false)
                },
              })
            }}
          >
            {deleteMutation.isPending ? 'Deleting...' : 'Delete'}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}

export default function PurchasingManagement() {
  const queryClient = useQueryClient()
  const { hasRole } = useAuth()

  const [page, setPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(25)
  const [selectedPoId, setSelectedPoId] = useState<number | null>(null)
  const [createPoOpen, setCreatePoOpen] = useState(false)
  const [bulkDialogOpen, setBulkDialogOpen] = useState(false)
  const [bulkLoading, setBulkLoading] = useState(false)
  const [bulkError, setBulkError] = useState<string | null>(null)
  const [bulkTotal, setBulkTotal] = useState(0)
  const [bulkProgress, setBulkProgress] = useState({ queued: 0, success: 0, failed: 0 })
  const [bulkDone, setBulkDone] = useState(false)
  const [syncingPoId, setSyncingPoId] = useState<number | null>(null)
  const [addingItemPoId, setAddingItemPoId] = useState<number | null>(null)
  const goodwillFileInputRef = useRef<HTMLInputElement | null>(null)
  const [expandedPoId, setExpandedPoId] = useState<number | null>(null)
  const [snackbar, setSnackbar] = useState<{ open: boolean; msg: string; severity: 'success' | 'error' }>({
    open: false,
    msg: '',
    severity: 'success',
  })

  const [vendorSearchInput, setVendorSearchInput] = useState('')
  const [poForm, setPoForm] = useState<PurchaseOrderCreate>({
    po_number: '',
    vendor_id: 0,
    order_date: new Date().toISOString().slice(0, 10),
    total_amount: 0,
    tax_amount: 0,
    shipping_amount: 0,
    handling_amount: 0,
    currency: 'USD',
    notes: '',
    items: [],
  })

  const { data: vendors = [] } = useQuery({ queryKey: ['vendors'], queryFn: listVendors })
  const { data: pagedOrders = [], isLoading: loadingOrders } = useQuery({
    queryKey: ['purchases', page, rowsPerPage],
    queryFn: () =>
      listPurchaseOrdersPaged({
        skip: page * rowsPerPage,
        limit: rowsPerPage + 1,
      }),
  })

  const hasNextPage = pagedOrders.length > rowsPerPage
  const orders = hasNextPage ? pagedOrders.slice(0, rowsPerPage) : pagedOrders
  const paginationCount = page * rowsPerPage + orders.length + (hasNextPage ? 1 : 0)

  const refreshPurchases = async () => {
    await queryClient.invalidateQueries({ queryKey: ['purchases'] })
  }

  const createVendorInlineMutation = useMutation({
    mutationFn: (body: VendorCreate) => createVendor(body),
    onSuccess: async (vendor) => {
      await queryClient.invalidateQueries({ queryKey: ['vendors'] })
      setPoForm((prev) => ({ ...prev, vendor_id: vendor.id }))
      setVendorSearchInput(vendor.name)
      setSnackbar({ open: true, msg: 'Vendor created and selected.', severity: 'success' })
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
        tax_amount: 0,
        shipping_amount: 0,
        handling_amount: 0,
        currency: 'USD',
        notes: '',
        items: [],
      })
      setVendorSearchInput('')
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

  const importRandomZohoMutation = useMutation({
    mutationFn: () => {
      const randomSourcePage = Math.floor(Math.random() * 10) + 1
      return importOneRandomPurchaseFromZoho({ sourcePage: randomSourcePage, perPage: 200 })
    },
    onSuccess: async (res) => {
      await queryClient.invalidateQueries({ queryKey: ['vendors'] })
      await queryClient.invalidateQueries({ queryKey: ['purchases'] })
      setSnackbar({
        open: true,
        severity: 'success',
        msg:
          `Imported 1 random Zoho PO: ${res.selected_po_number} (Zoho ID ${res.selected_zoho_purchase_order_id}) ` +
          `from page ${res.selected_source_page}.`,
      })
    },
    onError: () => {
      setSnackbar({ open: true, msg: 'Failed to import a random purchase order from Zoho.', severity: 'error' })
    },
  })

  const importGoodwillCsvMutation = useMutation({
    mutationFn: (file: File) => importPurchasesFromGoodwillCsv(file),
    onSuccess: async (res) => {
      await queryClient.invalidateQueries({ queryKey: ['vendors'] })
      await queryClient.invalidateQueries({ queryKey: ['purchases'] })
      setSnackbar({
        open: true,
        severity: 'success',
        msg:
          `Goodwill CSV import done: ${res.purchase_orders_created} PO created, ` +
          `${res.purchase_orders_updated} PO updated, ` +
          `${res.purchase_order_items_created} items created, ${res.purchase_order_items_updated} items updated.`,
      })
    },
    onError: () => {
      setSnackbar({ open: true, msg: 'Failed to import Goodwill CSV.', severity: 'error' })
    },
  })

  const handleGoodwillCsvSelected = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) {
      return
    }

    importGoodwillCsvMutation.mutate(file)
    event.target.value = ''
  }

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
  const selectedVendor = vendors.find((vendor) => vendor.id === poForm.vendor_id) || null
  const vendorNameExists = vendors.some(
    (vendor) => vendor.name.trim().toLowerCase() === vendorSearchInput.trim().toLowerCase(),
  )

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
            disabled={importZohoMutation.isPending || importRandomZohoMutation.isPending}
          >
            {importZohoMutation.isPending ? 'Importing...' : 'Import from Zoho'}
          </Button>
          <Button
            variant="outlined"
            onClick={() => importRandomZohoMutation.mutate()}
            disabled={importZohoMutation.isPending || importRandomZohoMutation.isPending}
          >
            {importRandomZohoMutation.isPending ? 'Importing random PO...' : 'Import 1 Random PO'}
          </Button>
          <Button
            variant="outlined"
            onClick={() => goodwillFileInputRef.current?.click()}
            disabled={importGoodwillCsvMutation.isPending}
          >
            {importGoodwillCsvMutation.isPending ? 'Importing CSV...' : 'Import Goodwill CSV'}
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
                      <TableCell>Date</TableCell>
                      <TableCell>Tracking #</TableCell>
                      <TableCell>Status</TableCell>
                      <TableCell align="center">Items</TableCell>
                      <TableCell align="right">Tax</TableCell>
                      <TableCell align="right">Shipping</TableCell>
                      <TableCell align="right">Handling</TableCell>
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
                            <TableCell>{po.order_date}</TableCell>
                            <TableCell>{po.tracking_number || '-'}</TableCell>
                            <TableCell>
                              <Chip size="small" color={statusColor[po.deliver_status]} label={po.deliver_status} />
                            </TableCell>
                            <TableCell align="center">{po.items?.length ?? 0}</TableCell>
                            <TableCell align="right">{po.tax_amount ?? 0}</TableCell>
                            <TableCell align="right">{po.shipping_amount ?? 0}</TableCell>
                            <TableCell align="right">{po.handling_amount ?? 0}</TableCell>
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
                            <TableCell colSpan={hasRole(['ADMIN']) ? 11 : 10} sx={{ py: 0 }}>
                              <Collapse in={expanded} timeout="auto" unmountOnExit>
                                <Box sx={{ p: 1.5, bgcolor: 'action.hover' }}>
                                  <Typography variant="subtitle2" sx={{ mb: 1 }}>
                                    Line Items
                                  </Typography>
                                  <Table size="small">
                                    <TableHead>
                                      <TableRow>
                                        <TableCell>Item Id</TableCell>
                                        <TableCell>Item Name</TableCell>
                                        <TableCell>Item SKU</TableCell>
                                        <TableCell align="center">Qty</TableCell>
                                        <TableCell align="right">Price</TableCell>
                                        <TableCell align="center">Status</TableCell>
                                        <TableCell align="center">Actions</TableCell>
                                      </TableRow>
                                    </TableHead>
                                    <TableBody>
                                      {(po.items || []).map((item) => (
                                        <PurchaseOrderItemRow
                                          key={item.id}
                                          item={item}
                                          onChanged={refreshPurchases}
                                          onNotify={(msg, severity) => setSnackbar({ open: true, msg, severity })}
                                        />
                                      ))}
                                      <TableRow>
                                        <TableCell colSpan={7}>
                                          <Button
                                            size="small"
                                            variant="outlined"
                                            startIcon={<Add />}
                                            onClick={() =>
                                              setAddingItemPoId((current) => (current === po.id ? null : po.id))
                                            }
                                          >
                                            {addingItemPoId === po.id ? 'Hide Add Item' : 'Add New Item'}
                                          </Button>
                                        </TableCell>
                                      </TableRow>
                                      {addingItemPoId === po.id && (
                                        <AddPurchaseOrderItemRow
                                          poId={po.id}
                                          onChanged={refreshPurchases}
                                          onNotify={(msg, severity) => setSnackbar({ open: true, msg, severity })}
                                          onDone={() => setAddingItemPoId(null)}
                                        />
                                      )}
                                      <TableRow>
                                        <TableCell colSpan={4} />
                                        <TableCell align="right" sx={{ fontWeight: 600 }}>
                                          {(po.items || [])
                                            .reduce((sum, item) => sum + Number(item.total_price || 0), 0)
                                            .toFixed(2)}
                                        </TableCell>
                                        <TableCell align="center" sx={{ fontWeight: 600 }}>
                                          Line Total
                                        </TableCell>
                                        <TableCell />
                                      </TableRow>
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
            <TablePagination
              component="div"
              rowsPerPageOptions={[10, 25, 50, 100]}
              count={paginationCount}
              page={page}
              rowsPerPage={rowsPerPage}
              onPageChange={(_, nextPage) => setPage(nextPage)}
              onRowsPerPageChange={(e) => {
                setRowsPerPage(parseInt(e.target.value, 10))
                setPage(0)
              }}
            />
          </Paper>
        </Grid>
      </Grid>

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
            <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} alignItems={{ xs: 'stretch', md: 'center' }}>
              <Autocomplete
                options={vendors}
                value={selectedVendor}
                inputValue={vendorSearchInput}
                onChange={(_event, nextVendor) => {
                  setPoForm((prev) => ({ ...prev, vendor_id: nextVendor?.id || 0 }))
                  setVendorSearchInput(nextVendor?.name || '')
                }}
                onInputChange={(_event, nextInput) => {
                  setVendorSearchInput(nextInput)
                  const normalizedInput = nextInput.trim().toLowerCase()
                  const matched = vendors.find((vendor) =>
                    vendor.name.trim().toLowerCase().includes(normalizedInput),
                  )
                  setPoForm((prev) => ({ ...prev, vendor_id: matched?.id || 0 }))
                }}
                getOptionLabel={(option) => option.name}
                isOptionEqualToValue={(option, value) => option.id === value.id}
                sx={{ flex: 1 }}
                renderInput={(params) => <TextField {...params} label="Vendor" required />}
              />
              <Button
                variant="outlined"
                disabled={
                  createVendorInlineMutation.isPending || !vendorSearchInput.trim() || vendorNameExists
                }
                onClick={() =>
                  createVendorInlineMutation.mutate({
                    name: vendorSearchInput.trim(),
                    is_active: true,
                  })
                }
              >
                {createVendorInlineMutation.isPending
                  ? 'Creating vendor...'
                  : `Create Vendor "${vendorSearchInput.trim() || 'New Vendor'}"`}
              </Button>
            </Stack>
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
              label="Tax Amount"
              type="number"
              value={poForm.tax_amount ?? 0}
              onChange={(e) => setPoForm((prev) => ({ ...prev, tax_amount: Number(e.target.value) }))}
            />
            <TextField
              label="Shipping Amount"
              type="number"
              value={poForm.shipping_amount ?? 0}
              onChange={(e) =>
                setPoForm((prev) => ({ ...prev, shipping_amount: Number(e.target.value) }))
              }
            />
            <TextField
              label="Handling Amount"
              type="number"
              value={poForm.handling_amount ?? 0}
              onChange={(e) =>
                setPoForm((prev) => ({ ...prev, handling_amount: Number(e.target.value) }))
              }
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

      <input
        ref={goodwillFileInputRef}
        type="file"
        accept=".csv,text/csv"
        onChange={handleGoodwillCsvSelected}
        hidden
        aria-label="Upload Goodwill CSV"
        title="Upload Goodwill CSV"
      />
    </Box>
  )
}

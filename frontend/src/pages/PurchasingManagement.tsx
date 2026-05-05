import { ChangeEvent, Fragment, useRef, useState } from 'react'
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Checkbox,
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
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Select,
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
import {
  Add,
  CloudSync,
  NoteAlt,
  FilterList,
  KeyboardArrowDown,
  KeyboardArrowUp,
  Visibility,
  Link as LinkIcon,
  LinkOff,
} from '@mui/icons-material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  addPurchaseOrderItem,
  createPurchaseOrder,
  createVendor,
  deletePurchaseOrder,
  deletePurchaseItem,
  importPurchasesFromEbay,
  importPurchasesFromFile,
  importPurchasesFromZoho,
  listPurchaseOrdersPaged,
  listVendors,
  matchPurchaseItem,
  updatePurchaseOrder,
  updatePurchaseItem,
} from '../api/purchasing'
import { forceSyncPurchase, forceSyncPurchasesByPeriod } from '../api/sync'
import type {
  PurchaseOrder,
  PurchaseOrderCreate,
  PurchaseDeliverStatus,
  PurchaseOrderItem,
  PurchaseOrderUpdate,
  PurchaseFileImportSource,
  VendorCreate,
  ZohoSyncStatus,
} from '../types/purchasing'
import VariantSearchAutocomplete from '../components/common/VariantSearchAutocomplete'
import HoldActionPromptDialog from '../components/common/HoldActionPromptDialog'
import LongPressTableRow from '../components/common/LongPressTableRow'
import TablePaginationWithPageJump from '../components/common/TablePaginationWithPageJump'
import OrderSummaryCards from '../components/common/OrderSummaryCards'
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

const zohoSyncColor = {
  PENDING: 'warning',
  SYNCED: 'success',
  ERROR: 'error',
  DIRTY: 'info',
} as const

const ebayPurchaseSources: PurchaseFileImportSource[] = ['ebay_mekong', 'ebay_purchasing', 'ebay_usav', 'ebay_dragon']

function formatUnitPrice(value: number): string {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) {
    return '-'
  }
  return numeric.toFixed(6).replace(/\.?0+$/, '')
}

function getPurchaseImportSourceLabel(source: PurchaseFileImportSource): string {
  switch (source) {
    case 'goodwill':
      return 'Goodwill CSV'
    case 'goodwill_shipped':
      return 'Goodwill Shipped Orders'
    case 'goodwill_open':
      return 'Goodwill Open Orders'
    case 'amazon':
      return 'Amazon CSV'
    case 'aliexpress':
      return 'AliExpress CSV/JSON'
    case 'ebay_mekong':
      return 'eBay Mekong API'
    case 'ebay_purchasing':
      return 'eBay Purchasing API'
    case 'ebay_usav':
      return 'eBay USAV API'
    case 'ebay_dragon':
      return 'eBay Dragon API'
    default:
      return source
  }
}

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

interface PurchaseOrderMetadataForm {
  po_number: string
  vendor_id: number
  deliver_status: PurchaseDeliverStatus
  order_date: string
  expected_delivery_date: string
  tax_amount: number
  shipping_amount: number
  handling_amount: number
  currency: string
  tracking_number: string
  source: string
  is_stationery: boolean
  notes: string
}

function AddPurchaseOrderItemRow({ poId, onChanged, onNotify, onDone }: AddPurchaseOrderItemRowProps) {
  const [externalItemId, setExternalItemId] = useState('')
  const [externalItemName, setExternalItemName] = useState('')
  const [conditionNote, setConditionNote] = useState('')
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
        condition_note: conditionNote.trim() || null,
        external_item_name: externalItemName.trim(),
        quantity: parsedQuantity,
        unit_price: parsedUnitPrice,
        total_price: computedTotal,
        variant_id: selectedVariant?.id,
      }),
    onSuccess: async () => {
      setExternalItemId('')
      setExternalItemName('')
      setConditionNote('')
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
            inputProps={{ min: 0, step: 0.001 }}
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
            <TextField
              size="small"
              label="Condition Note"
              value={conditionNote}
              onChange={(e) => setConditionNote(e.target.value)}
              placeholder="Optional"
              multiline
              minRows={1}
              sx={{ minWidth: { xs: '100%', md: 240 } }}
            />
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
  const [selectedVariant, setSelectedVariant] = useState<VariantSearchResult | null>(null)
  const [externalItemId, setExternalItemId] = useState(item.external_item_id || '')
  const [externalItemName, setExternalItemName] = useState(item.external_item_name)
  const [conditionNote, setConditionNote] = useState(item.condition_note || '')
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
        condition_note: conditionNote.trim() || null,
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

  const unmatchMutation = useMutation({
    mutationFn: () =>
      updatePurchaseItem(item.id, {
        variant_id: null,
      }),
    onSuccess: async () => {
      setShowMatch(false)
      setSelectedVariant(null)
      await onChanged()
      onNotify('Item unmatched.', 'success')
    },
    onError: (error: { response?: { data?: { detail?: string } }; message?: string }) => {
      onNotify(error.response?.data?.detail || error.message || 'Failed to unmatch item.', 'error')
    },
  })

  const anyPending =
    saveMutation.isPending || deleteMutation.isPending || matchMutation.isPending || unmatchMutation.isPending
  const purchaseItemLink = item.purchase_item_link?.trim() || ''
  const hasPurchaseItemLink = purchaseItemLink.length > 0

  const openPrompt = () => {
    setExternalItemId(item.external_item_id || '')
    setExternalItemName(item.external_item_name)
    setConditionNote(item.condition_note || '')
    setQuantity(String(item.quantity))
    setUnitPrice(String(item.unit_price))
    setSelectedVariant(null)
    setPromptOpen(true)
  }

  return (
    <>
      <LongPressTableRow
        payload={item}
        onLongPress={openPrompt}
        longPressDelayMs={900}
        rowSx={{ cursor: 'pointer' }}
      >
        <TableCell>{item.external_item_id || '-'}</TableCell>
        <TableCell>
          <Typography variant="body2">{item.external_item_name}</Typography>
          {item.status === 'MATCHED' && item.variant_name && (
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{
                fontStyle: 'italic',
                fontSize: '0.72rem',
                display: 'block',
                mt: 0.25,
                maxWidth: 380,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {item.variant_name}
            </Typography>
          )}
          {item.condition_note && (
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{
                display: 'block',
                mt: 0.25,
                maxWidth: 380,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              Condition: {item.condition_note}
            </Typography>
          )}
        </TableCell>
        <TableCell>{item.variant_sku || '-'}</TableCell>
        <TableCell align="center">{item.quantity}</TableCell>
        <TableCell align="right">{formatUnitPrice(item.unit_price)}</TableCell>
        <TableCell align="center">
          <Chip size="small" color={itemStatusColor[item.status]} label={item.status} />
        </TableCell>
        <TableCell align="center">
          <Stack direction="row" spacing={0.5} justifyContent="center">
            <IconButton
              size="small"
              color="inherit"
              disabled={!hasPurchaseItemLink}
              onClick={(event) => {
                event.stopPropagation()
                if (!hasPurchaseItemLink) {
                  return
                }
                window.open(purchaseItemLink, '_blank', 'noopener,noreferrer')
              }}
            >
              <Visibility fontSize="small" />
            </IconButton>
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
            {item.status === 'MATCHED' && (
              <IconButton
                size="small"
                color="error"
                disabled={anyPending}
                onClick={(event) => {
                  event.stopPropagation()
                  unmatchMutation.mutate()
                }}
              >
                <LinkOff fontSize="small" />
              </IconButton>
            )}
            <IconButton
              size="small"
              color="primary"
              disabled={anyPending}
              onClick={(event) => {
                event.stopPropagation()
                openPrompt()
              }}
            >
              <NoteAlt fontSize="small" />
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
          <TextField label="Condition Note" value={conditionNote} onChange={(e) => setConditionNote(e.target.value)} fullWidth multiline minRows={2} />
          <TextField label="Quantity" type="number" value={quantity} onChange={(e) => setQuantity(e.target.value)} fullWidth />
          <TextField
            label="Unit Price"
            type="number"
            value={unitPrice}
            onChange={(e) => setUnitPrice(e.target.value)}
            inputProps={{ min: 0, step: 0.001 }}
            fullWidth
          />
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
    </>
  )
}

export default function PurchasingManagement() {
  const queryClient = useQueryClient()

  const [page, setPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(25)
  const [sortBy, setSortBy] = useState<'order_date' | 'po_number' | 'total_amount' | 'created_at'>('order_date')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [deliverStatusFilter, setDeliverStatusFilter] = useState<PurchaseDeliverStatus | 'ALL'>('ALL')
  const [itemMatchFilter, setItemMatchFilter] = useState<'ALL' | 'MATCHED' | 'UNMATCHED'>('ALL')
  const [zohoSyncFilter, setZohoSyncFilter] = useState<ZohoSyncStatus | 'ALL'>('ALL')
  const [sourceFilter, setSourceFilter] = useState<string>('ALL')
  const [poNumberSearch, setPoNumberSearch] = useState('')
  const [totalAmountSearch, setTotalAmountSearch] = useState('')
  const [totalAmountRange, setTotalAmountRange] = useState('0')
  const [orderDateFrom, setOrderDateFrom] = useState('')
  const [orderDateTo, setOrderDateTo] = useState('')
  const [filtersDialogOpen, setFiltersDialogOpen] = useState(false)
  const [selectedPoId, setSelectedPoId] = useState<number | null>(null)
  const [createPoOpen, setCreatePoOpen] = useState(false)
  const [editPoOpen, setEditPoOpen] = useState(false)
  const [editPoDeleteConfirmOpen, setEditPoDeleteConfirmOpen] = useState(false)
  const [editingPoId, setEditingPoId] = useState<number | null>(null)
  const [editVendorSearchInput, setEditVendorSearchInput] = useState('')
  const [bulkDialogOpen, setBulkDialogOpen] = useState(false)
  const [bulkLoading, setBulkLoading] = useState(false)
  const [bulkError, setBulkError] = useState<string | null>(null)
  const [bulkTotal, setBulkTotal] = useState(0)
  const [bulkProgress, setBulkProgress] = useState({ queued: 0, success: 0, failed: 0 })
  const [bulkDone, setBulkDone] = useState(false)
  const [syncingPoId, setSyncingPoId] = useState<number | null>(null)
  const [addingItemPoId, setAddingItemPoId] = useState<number | null>(null)
  const purchaseFileInputRef = useRef<HTMLInputElement | null>(null)
  const [importPurchaseOpen, setImportPurchaseOpen] = useState(false)
  const [importPurchaseEbayRangeOpen, setImportPurchaseEbayRangeOpen] = useState(false)
  const [importPurchaseEbayRangeFrom, setImportPurchaseEbayRangeFrom] = useState('')
  const [importPurchaseEbayRangeTo, setImportPurchaseEbayRangeTo] = useState('')
  const [importZohoRangeOpen, setImportZohoRangeOpen] = useState(false)
  const [importZohoRangeFrom, setImportZohoRangeFrom] = useState('')
  const [importZohoRangeTo, setImportZohoRangeTo] = useState('')
  const [purchaseImportSource, setPurchaseImportSource] = useState<PurchaseFileImportSource>('amazon')
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
    tracking_number: '',
    tax_amount: 0,
    shipping_amount: 0,
    handling_amount: 0,
    currency: 'USD',
    is_stationery: false,
    notes: '',
    items: [],
  })
  const [editPoForm, setEditPoForm] = useState<PurchaseOrderMetadataForm>({
    po_number: '',
    vendor_id: 0,
    deliver_status: 'CREATED',
    order_date: new Date().toISOString().slice(0, 10),
    expected_delivery_date: '',
    tax_amount: 0,
    shipping_amount: 0,
    handling_amount: 0,
    currency: 'USD',
    tracking_number: '',
    source: 'MANUAL',
    is_stationery: false,
    notes: '',
  })

  const { data: vendors = [] } = useQuery({ queryKey: ['vendors'], queryFn: listVendors })
  const { data: pagedOrders = [], isLoading: loadingOrders } = useQuery({
    queryKey: [
      'purchases',
      page,
      rowsPerPage,
      sortBy,
      sortDir,
      deliverStatusFilter,
      itemMatchFilter,
      zohoSyncFilter,
      sourceFilter,
      poNumberSearch,
      totalAmountSearch,
      totalAmountRange,
      orderDateFrom,
      orderDateTo,
    ],
    queryFn: () =>
      listPurchaseOrdersPaged({
        skip: page * rowsPerPage,
        limit: rowsPerPage + 1,
        sortBy,
        sortDir,
        poNumber: poNumberSearch || undefined,
        deliverStatus: deliverStatusFilter === 'ALL' ? undefined : deliverStatusFilter,
        itemMatchStatus:
          itemMatchFilter === 'ALL' ? undefined : itemMatchFilter === 'MATCHED' ? 'matched' : 'unmatched',
        zohoSyncStatus: zohoSyncFilter === 'ALL' ? undefined : zohoSyncFilter,
        source: sourceFilter === 'ALL' ? undefined : sourceFilter,
        totalAmount: totalAmountSearch ? Number(totalAmountSearch) : undefined,
        totalAmountRange: totalAmountSearch ? Number(totalAmountRange || '0') : undefined,
        orderDateFrom: orderDateFrom || undefined,
        orderDateTo: orderDateTo || undefined,
      }),
  })

  const { data: purchaseSummary } = useQuery({
    queryKey: [
      'purchases-summary',
      sortBy,
      sortDir,
      deliverStatusFilter,
      itemMatchFilter,
      zohoSyncFilter,
      sourceFilter,
      poNumberSearch,
      totalAmountSearch,
      totalAmountRange,
      orderDateFrom,
      orderDateTo,
    ],
    queryFn: async () => {
      const pageSize = 500
      let skip = 0
      let totalOrders = 0
      let unmatchedOrders = 0
      let unmatchedItems = 0

      // eslint-disable-next-line no-constant-condition
      while (true) {
        const batch = await listPurchaseOrdersPaged({
          skip,
          limit: pageSize,
          sortBy,
          sortDir,
          poNumber: poNumberSearch || undefined,
          deliverStatus: deliverStatusFilter === 'ALL' ? undefined : deliverStatusFilter,
          itemMatchStatus:
            itemMatchFilter === 'ALL' ? undefined : itemMatchFilter === 'MATCHED' ? 'matched' : 'unmatched',
          zohoSyncStatus: zohoSyncFilter === 'ALL' ? undefined : zohoSyncFilter,
          source: sourceFilter === 'ALL' ? undefined : sourceFilter,
          totalAmount: totalAmountSearch ? Number(totalAmountSearch) : undefined,
          totalAmountRange: totalAmountSearch ? Number(totalAmountRange || '0') : undefined,
          orderDateFrom: orderDateFrom || undefined,
          orderDateTo: orderDateTo || undefined,
        })

        totalOrders += batch.length
        for (const po of batch) {
          const poUnmatchedItems = (po.items || []).filter((item) => item.status === 'UNMATCHED').length
          unmatchedItems += poUnmatchedItems
          if (poUnmatchedItems > 0) {
            unmatchedOrders += 1
          }
        }

        if (batch.length < pageSize) {
          break
        }
        skip += pageSize
      }

      return { totalOrders, unmatchedOrders, unmatchedItems }
    },
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
        tracking_number: '',
        tax_amount: 0,
        shipping_amount: 0,
        handling_amount: 0,
        currency: 'USD',
        is_stationery: false,
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

  const updatePoMutation = useMutation({
    mutationFn: ({ poId, body }: { poId: number; body: PurchaseOrderUpdate }) => updatePurchaseOrder(poId, body),
    onSuccess: async (po) => {
      setEditPoOpen(false)
      setEditingPoId(null)
      setSelectedPoId(po.id)
      setExpandedPoId(po.id)
      await queryClient.invalidateQueries({ queryKey: ['purchases'] })
      setSnackbar({ open: true, msg: 'Purchase order metadata updated.', severity: 'success' })
    },
    onError: (error: { response?: { data?: { detail?: string } }; message?: string }) => {
      setSnackbar({
        open: true,
        msg: error.response?.data?.detail || error.message || 'Failed to update purchase order.',
        severity: 'error',
      })
    },
  })

  const deletePoMutation = useMutation({
    mutationFn: (poId: number) => deletePurchaseOrder(poId),
    onSuccess: async () => {
      const deletedPoId = editingPoId
      setEditPoDeleteConfirmOpen(false)
      setEditPoOpen(false)
      setEditingPoId(null)
      if (deletedPoId !== null) {
        if (selectedPoId === deletedPoId) {
          setSelectedPoId(null)
        }
        if (expandedPoId === deletedPoId) {
          setExpandedPoId(null)
        }
      }
      await queryClient.invalidateQueries({ queryKey: ['purchases'] })
      setSnackbar({ open: true, msg: 'Purchase order deleted.', severity: 'success' })
    },
    onError: (error: { response?: { data?: { detail?: string } }; message?: string }) => {
      setSnackbar({
        open: true,
        msg: error.response?.data?.detail || error.message || 'Failed to delete purchase order.',
        severity: 'error',
      })
    },
  })

  const importZohoRangeMutation = useMutation({
    mutationFn: (params: { orderDateFrom: string; orderDateTo: string }) => importPurchasesFromZoho(params),
    onSuccess: async (res, params) => {
      await queryClient.invalidateQueries({ queryKey: ['vendors'] })
      await queryClient.invalidateQueries({ queryKey: ['purchases'] })
      setImportZohoRangeOpen(false)
      setSnackbar({
        open: true,
        severity: 'success',
        msg:
          `Zoho range import done (${params.orderDateFrom} to ${params.orderDateTo}): ` +
          `${res.purchase_orders_created} PO created, ${res.purchase_orders_updated} PO updated, ` +
          `${res.vendors_created} vendor created, ${res.vendors_updated} vendor updated.`,
      })
    },
    onError: (error: { response?: { data?: { detail?: string } } }) => {
      setSnackbar({
        open: true,
        msg: error.response?.data?.detail || 'Failed to import Zoho purchases by date range.',
        severity: 'error',
      })
    },
  })

  const importPurchaseFileMutation = useMutation({
    mutationFn: ({ source, file }: { source: PurchaseFileImportSource; file: File }) =>
      importPurchasesFromFile(source, file),
    onSuccess: async (res) => {
      await queryClient.invalidateQueries({ queryKey: ['vendors'] })
      await queryClient.invalidateQueries({ queryKey: ['purchases'] })
      const sourceLabel = getPurchaseImportSourceLabel(res.source)
      setSnackbar({
        open: true,
        severity: 'success',
        msg:
          `${sourceLabel} import done: ${res.purchase_orders_created} PO created, ` +
          `${res.purchase_orders_updated} PO updated, ` +
          `${res.purchase_order_items_created} items created, ${res.purchase_order_items_updated} items updated.`,
      })
    },
    onError: () => {
      setSnackbar({ open: true, msg: 'Failed to import purchase file.', severity: 'error' })
    },
  })

  const importPurchaseEbayMutation = useMutation({
    mutationFn: (params: {
      source: 'ebay_mekong' | 'ebay_purchasing' | 'ebay_usav' | 'ebay_dragon'
      orderDateFrom: string
      orderDateTo: string
    }) => importPurchasesFromEbay(params),
    onSuccess: async (res) => {
      await queryClient.invalidateQueries({ queryKey: ['vendors'] })
      await queryClient.invalidateQueries({ queryKey: ['purchases'] })
      setImportPurchaseEbayRangeOpen(false)
      const sourceLabel = getPurchaseImportSourceLabel(res.source)
      setSnackbar({
        open: true,
        severity: 'success',
        msg:
          `${sourceLabel} import done: ${res.purchase_orders_created} PO created, ` +
          `${res.purchase_orders_updated} PO updated, ` +
          `${res.purchase_order_items_created} items created, ${res.purchase_order_items_updated} items updated.`,
      })
    },
    onError: (error: { response?: { data?: { detail?: string } } }) => {
      setSnackbar({
        open: true,
        msg: error.response?.data?.detail || 'Failed to import eBay purchases.',
        severity: 'error',
      })
    },
  })

  const isEbayPurchaseSource = ebayPurchaseSources.includes(purchaseImportSource)

  const handlePurchaseImportSelected = (event: ChangeEvent<HTMLInputElement>) => {
    if (isEbayPurchaseSource) {
      event.target.value = ''
      return
    }

    const file = event.target.files?.[0]
    if (!file) {
      return
    }

    importPurchaseFileMutation.mutate({ source: purchaseImportSource, file })
    event.target.value = ''
    setImportPurchaseOpen(false)
  }

  const forceSyncPoMutation = useMutation({
    mutationFn: (poId: number) => forceSyncPurchase(poId),
    onMutate: (poId) => setSyncingPoId(poId),
    onSuccess: async (_data, poId) => {
      setSnackbar({ open: true, msg: `Purchase order #${poId} queued for Zoho sync.`, severity: 'success' })
      await queryClient.invalidateQueries({ queryKey: ['purchases'] })
      setSyncingPoId(null)
    },
    onError: (error: { response?: { data?: { detail?: string } }; message?: string }, poId) => {
      const detail = error.response?.data?.detail || error.message || 'Sync failed.'
      setSnackbar({ open: true, msg: `Purchase order #${poId}: ${detail}`, severity: 'error' })
      setSyncingPoId(null)
    },
  })

  const canSyncPo = (po: PurchaseOrder) => po.items.length > 0

  const handleBulkSync = async () => {
    setBulkLoading(true)
    setBulkError(null)
    setBulkDone(false)
    setBulkProgress({ queued: 0, success: 0, failed: 0 })

    try {
      const response = await forceSyncPurchasesByPeriod({
        orderDateFrom: orderDateFrom || undefined,
        orderDateTo: orderDateTo || undefined,
        limit: 2000,
      })

      setBulkTotal(response.count)
      setBulkProgress({ queued: response.count, success: response.count, failed: 0 })

      setBulkDone(true)
      await queryClient.invalidateQueries({ queryKey: ['purchases'] })
    } catch (err: any) {
      setBulkError(err?.response?.data?.detail || err?.message || 'Failed to queue purchase orders.')
    } finally {
      setBulkLoading(false)
    }
  }

  const bulkPercent = bulkTotal ? Math.min(Math.round((bulkProgress.queued / bulkTotal) * 100), 100) : 0
  const selectedVendor = vendors.find((vendor) => vendor.id === poForm.vendor_id) || null
  const selectedEditVendor = vendors.find((vendor) => vendor.id === editPoForm.vendor_id) || null
  const vendorNameExists = vendors.some(
    (vendor) => vendor.name.trim().toLowerCase() === vendorSearchInput.trim().toLowerCase(),
  )

  const openEditMetadataDialog = (po: PurchaseOrder) => {
    setEditingPoId(po.id)
    setEditVendorSearchInput(po.vendor?.name || '')
    setEditPoForm({
      po_number: po.po_number,
      vendor_id: po.vendor_id,
      deliver_status: po.deliver_status,
      order_date: po.order_date,
      expected_delivery_date: po.expected_delivery_date || '',
      tax_amount: Number(po.tax_amount || 0),
      shipping_amount: Number(po.shipping_amount || 0),
      handling_amount: Number(po.handling_amount || 0),
      currency: po.currency || 'USD',
      tracking_number: po.tracking_number || '',
      source: po.source || 'MANUAL',
      is_stationery: po.is_stationery || false,
      notes: po.notes || '',
    })
    setEditPoOpen(true)
  }

  const activeFilterCount = [
    deliverStatusFilter !== 'ALL',
    itemMatchFilter !== 'ALL',
    zohoSyncFilter !== 'ALL',
    sourceFilter !== 'ALL',
    !!totalAmountSearch,
    !!orderDateFrom,
    !!orderDateTo,
    sortBy !== 'order_date',
    sortDir !== 'desc',
  ].filter(Boolean).length

  const clearAllFilters = () => {
    setOrderDateFrom('')
    setOrderDateTo('')
    setDeliverStatusFilter('ALL')
    setItemMatchFilter('ALL')
    setZohoSyncFilter('ALL')
    setSourceFilter('ALL')
    setPoNumberSearch('')
    setTotalAmountSearch('')
    setTotalAmountRange('0')
    setSortBy('order_date')
    setSortDir('desc')
    setPage(0)
  }

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h4">Purchasing</Typography>
        <Stack direction="row" spacing={1}>
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
            Sync period to Zoho
          </Button>
          <Button
            variant="outlined"
            onClick={() => {
              setImportZohoRangeFrom(orderDateFrom)
              setImportZohoRangeTo(orderDateTo)
              setImportZohoRangeOpen(true)
            }}
            disabled={importZohoRangeMutation.isPending}
          >
            {importZohoRangeMutation.isPending ? 'Importing range...' : 'Import Range from Zoho'}
          </Button>
          <Button
            variant="outlined"
            onClick={() => setImportPurchaseOpen(true)}
            disabled={importPurchaseFileMutation.isPending || importPurchaseEbayMutation.isPending}
          >
            {importPurchaseFileMutation.isPending || importPurchaseEbayMutation.isPending
              ? 'Importing...'
              : 'Import Purchase'}
          </Button>
          <Button startIcon={<Add />} variant="contained" onClick={() => setCreatePoOpen(true)}>
            Create PO
          </Button>
        </Stack>
      </Box>

      <OrderSummaryCards
        totalOrders={purchaseSummary?.totalOrders ?? orders.length}
        unmatchedOrders={purchaseSummary?.unmatchedOrders ?? 0}
        unmatchedItems={purchaseSummary?.unmatchedItems ?? 0}
      />

      <Grid container spacing={2}>
        <Grid item xs={12}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" sx={{ mb: 1 }}>
              Purchase Orders
            </Typography>
            <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} sx={{ mb: 2 }} alignItems={{ xs: 'stretch', md: 'center' }}>
              <TextField
                size="small"
                label="Search PO # / Vendor"
                value={poNumberSearch}
                onChange={(e) => {
                  setPoNumberSearch(e.target.value)
                  setPage(0)
                }}
                sx={{ minWidth: 280, flex: 1 }}
              />
              <TextField
                size="small"
                label="Price Search"
                type="number"
                value={totalAmountSearch}
                onChange={(e) => {
                  setTotalAmountSearch(e.target.value)
                  setPage(0)
                }}
                inputProps={{ min: 0, step: 0.01 }}
                sx={{ minWidth: 150 }}
              />
              <TextField
                size="small"
                label="Range +/-"
                type="number"
                value={totalAmountRange}
                onChange={(e) => {
                  setTotalAmountRange(e.target.value)
                  setPage(0)
                }}
                inputProps={{ min: 0, step: 0.01 }}
                sx={{ width: 120 }}
              />
              <Button
                variant={activeFilterCount > 0 ? 'contained' : 'outlined'}
                startIcon={<FilterList />}
                onClick={() => setFiltersDialogOpen(true)}
              >
                Filters{activeFilterCount > 0 ? ` (${activeFilterCount})` : ''}
              </Button>
              <Button
                size="small"
                onClick={clearAllFilters}
                disabled={
                  !orderDateFrom &&
                  !orderDateTo &&
                  deliverStatusFilter === 'ALL' &&
                  itemMatchFilter === 'ALL' &&
                  zohoSyncFilter === 'ALL' &&
                  sourceFilter === 'ALL' &&
                  !poNumberSearch &&
                  !totalAmountSearch &&
                  totalAmountRange === '0' &&
                  sortBy === 'order_date' &&
                  sortDir === 'desc'
                }
              >
                Clear
              </Button>
            </Stack>
            {loadingOrders ? (
              <Typography variant="body2">Loading...</Typography>
            ) : (
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell sx={{ width: 44 }} />
                      <TableCell>PO #</TableCell>
                      <TableCell>Date</TableCell>
                      <TableCell>Tracking #</TableCell>
                      <TableCell>Expected Delivery</TableCell>
                      <TableCell>Status</TableCell>
                      <TableCell align="center">Unmatched</TableCell>
                      <TableCell align="right">Total</TableCell>
                      <TableCell align="center">Zoho Sync Status</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {orders.map((po) => {
                      const expanded = expandedPoId === po.id
                      const unmatchedCount = (po.items || []).filter((item) => item.status === 'UNMATCHED').length
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
                            <TableCell>{po.order_date}</TableCell>
                            <TableCell>{po.tracking_number || '-'}</TableCell>
                            <TableCell>{po.expected_delivery_date || '-'}</TableCell>
                            <TableCell>
                              <Chip size="small" color={statusColor[po.deliver_status]} label={po.deliver_status} />
                            </TableCell>
                            <TableCell align="center">
                              <Chip
                                size="small"
                                color={unmatchedCount > 0 ? 'error' : 'default'}
                                label={unmatchedCount}
                              />
                            </TableCell>
                            <TableCell align="right">
                              {po.total_amount} {po.currency}
                            </TableCell>
                            <TableCell align="center">
                              <Chip
                                size="small"
                                color={zohoSyncColor[po.zoho_sync_status]}
                                label={po.zoho_sync_status}
                                title={po.zoho_sync_error || ''}
                              />
                            </TableCell>
                          </TableRow>
                          <TableRow>
                            <TableCell colSpan={9} sx={{ py: 0 }}>
                              <Collapse in={expanded} timeout="auto" unmountOnExit>
                                <Box sx={{ p: 1.5, bgcolor: 'action.hover' }}>
                                  <Stack
                                    direction="row"
                                    spacing={2}
                                    alignItems="center"
                                    sx={{ mb: 1.25, flexWrap: 'nowrap', overflow: 'hidden' }}
                                  >
                                    <Box sx={{ minWidth: 110, maxWidth: 170, flexShrink: 1, overflow: 'hidden' }}>
                                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                                        Vendor
                                      </Typography>
                                      <Typography
                                        variant="body2"
                                        sx={{ fontSize: '0.82rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                                      >
                                        {po.vendor?.name || po.vendor_id}
                                      </Typography>
                                    </Box>

                                    <Box sx={{ minWidth: 150, maxWidth: 200, flexShrink: 1, overflow: 'hidden' }}>
                                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                                        Zoho ID
                                      </Typography>
                                      <Typography
                                        variant="body2"
                                        sx={{ fontSize: '0.82rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                                      >
                                        {po.zoho_id || '-'}
                                      </Typography>
                                    </Box>

                                    <Box sx={{ minWidth: 95, maxWidth: 140, flexShrink: 1, overflow: 'hidden' }}>
                                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                                        Source
                                      </Typography>
                                      <Typography
                                        variant="body2"
                                        sx={{ fontSize: '0.82rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                                      >
                                        {po.source || '-'}
                                      </Typography>
                                    </Box>

                                    <Box sx={{ minWidth: 100, maxWidth: 120, flexShrink: 0, overflow: 'hidden' }}>
                                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                                        Stationery
                                      </Typography>
                                      <Typography variant="body2" sx={{ fontSize: '0.82rem' }}>
                                        {po.is_stationery ? 'Yes' : 'No'}
                                      </Typography>
                                    </Box>

                                    <Box sx={{ minWidth: 56, flexShrink: 0 }}>
                                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                                        Tax
                                      </Typography>
                                      <Typography variant="body2" sx={{ fontSize: '0.82rem' }}>
                                        {po.tax_amount ?? 0}
                                      </Typography>
                                    </Box>

                                    <Box sx={{ minWidth: 64, flexShrink: 0 }}>
                                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                                        Shipping
                                      </Typography>
                                      <Typography variant="body2" sx={{ fontSize: '0.82rem' }}>
                                        {po.shipping_amount ?? 0}
                                      </Typography>
                                    </Box>

                                    <Box sx={{ minWidth: 64, flexShrink: 0 }}>
                                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                                        Handling
                                      </Typography>
                                      <Typography variant="body2" sx={{ fontSize: '0.82rem' }}>
                                        {po.handling_amount ?? 0}
                                      </Typography>
                                    </Box>

                                    <Box sx={{ minWidth: 140, flex: 1, overflow: 'hidden' }}>
                                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                                        Notes
                                      </Typography>
                                      <Typography
                                        variant="body2"
                                        sx={{
                                          fontSize: '0.82rem',
                                          whiteSpace: 'nowrap',
                                          overflow: 'hidden',
                                          textOverflow: 'ellipsis',
                                        }}
                                      >
                                        {po.notes || '-'}
                                      </Typography>
                                    </Box>

                                    <Button
                                      size="small"
                                      variant="outlined"
                                      sx={{ flexShrink: 0 }}
                                      startIcon={<NoteAlt />}
                                      onClick={(e) => {
                                        e.stopPropagation()
                                        openEditMetadataDialog(po)
                                      }}
                                    >
                                      Edit Metadata
                                    </Button>

                                    <Button
                                      size="small"
                                      variant="outlined"
                                      sx={{ flexShrink: 0 }}
                                      startIcon={syncingPoId === po.id ? <CircularProgress size={14} /> : <CloudSync />}
                                      disabled={!canSyncPo(po) || syncingPoId === po.id}
                                      onClick={(e) => {
                                        e.stopPropagation()
                                        forceSyncPoMutation.mutate(po.id)
                                      }}
                                    >
                                      Zoho Sync
                                    </Button>
                                  </Stack>
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
            <TablePaginationWithPageJump
              count={paginationCount}
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
                onInputChange={(_event, nextInput, reason) => {
                  // Prevent losing typed vendor names when focus shifts to "Create Vendor".
                  if (reason === 'reset' && !nextInput && !selectedVendor) {
                    return
                  }
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
                onMouseDown={(e) => e.preventDefault()}
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
              label="Tracking #"
              value={poForm.tracking_number || ''}
              onChange={(e) => setPoForm((prev) => ({ ...prev, tracking_number: e.target.value }))}
              placeholder="Optional tracking number"
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
            <FormControlLabel
              control={
                <Checkbox
                  checked={Boolean(poForm.is_stationery)}
                  onChange={(e) => setPoForm((prev) => ({ ...prev, is_stationery: e.target.checked }))}
                />
              }
              label="Is Stationery"
            />
            <Alert severity="info">Create PO first. Line items can be loaded from integrations and matched below.</Alert>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreatePoOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={!poForm.po_number || !poForm.vendor_id || !poForm.order_date}
            onClick={() =>
              createPoMutation.mutate({
                ...poForm,
                tracking_number: poForm.tracking_number?.trim() || undefined,
              })
            }
          >
            Create
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog
        open={editPoOpen}
        onClose={() => {
          if (!updatePoMutation.isPending && !deletePoMutation.isPending) {
            setEditPoOpen(false)
            setEditingPoId(null)
            setEditPoDeleteConfirmOpen(false)
          }
        }}
        fullWidth
        maxWidth="sm"
      >
        <DialogTitle>Edit Purchase Order Metadata</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label="PO Number"
              value={editPoForm.po_number}
              onChange={(e) => setEditPoForm((prev) => ({ ...prev, po_number: e.target.value }))}
              required
            />
            <Autocomplete
              options={vendors}
              value={selectedEditVendor}
              inputValue={editVendorSearchInput}
              onChange={(_event, nextVendor) => {
                setEditPoForm((prev) => ({ ...prev, vendor_id: nextVendor?.id || 0 }))
                setEditVendorSearchInput(nextVendor?.name || '')
              }}
              onInputChange={(_event, nextInput, reason) => {
                setEditVendorSearchInput(nextInput)

                // Keep existing vendor selection stable while typing/filtering.
                if (reason !== 'input') {
                  return
                }

                const normalizedInput = nextInput.trim().toLowerCase()
                if (!normalizedInput) {
                  return
                }

                const exactMatch = vendors.find(
                  (vendor) => vendor.name.trim().toLowerCase() === normalizedInput,
                )
                if (exactMatch) {
                  setEditPoForm((prev) => ({ ...prev, vendor_id: exactMatch.id }))
                }
              }}
              getOptionLabel={(option) => option.name}
              isOptionEqualToValue={(option, value) => option.id === value.id}
              renderInput={(params) => <TextField {...params} label="Vendor" required />}
            />
            <FormControl size="small" fullWidth>
              <InputLabel id="po-edit-status-label">PO Status</InputLabel>
              <Select
                labelId="po-edit-status-label"
                label="PO Status"
                value={editPoForm.deliver_status}
                onChange={(e) =>
                  setEditPoForm((prev) => ({ ...prev, deliver_status: e.target.value as PurchaseDeliverStatus }))
                }
              >
                <MenuItem value="CREATED">CREATED</MenuItem>
                <MenuItem value="BILLED">BILLED</MenuItem>
                <MenuItem value="DELIVERED">DELIVERED</MenuItem>
              </Select>
            </FormControl>
            <TextField
              label="Order Date"
              type="date"
              value={editPoForm.order_date}
              onChange={(e) => setEditPoForm((prev) => ({ ...prev, order_date: e.target.value }))}
              InputLabelProps={{ shrink: true }}
            />
            <TextField
              label="Expected Delivery Date"
              type="date"
              value={editPoForm.expected_delivery_date}
              onChange={(e) =>
                setEditPoForm((prev) => ({ ...prev, expected_delivery_date: e.target.value }))
              }
              InputLabelProps={{ shrink: true }}
            />
            <TextField
              label="Tracking #"
              value={editPoForm.tracking_number}
              onChange={(e) => setEditPoForm((prev) => ({ ...prev, tracking_number: e.target.value }))}
            />
            <TextField
              label="Source"
              value={editPoForm.source}
              onChange={(e) => setEditPoForm((prev) => ({ ...prev, source: e.target.value }))}
            />
            <FormControlLabel
              control={
                <Checkbox
                  checked={editPoForm.is_stationery}
                  onChange={(e) => setEditPoForm((prev) => ({ ...prev, is_stationery: e.target.checked }))}
                />
              }
              label="Is Stationery"
            />
            <TextField
              label="Tax Amount"
              type="number"
              value={editPoForm.tax_amount}
              onChange={(e) => setEditPoForm((prev) => ({ ...prev, tax_amount: Number(e.target.value) }))}
            />
            <TextField
              label="Shipping Amount"
              type="number"
              value={editPoForm.shipping_amount}
              onChange={(e) => setEditPoForm((prev) => ({ ...prev, shipping_amount: Number(e.target.value) }))}
            />
            <TextField
              label="Handling Amount"
              type="number"
              value={editPoForm.handling_amount}
              onChange={(e) => setEditPoForm((prev) => ({ ...prev, handling_amount: Number(e.target.value) }))}
            />
            <TextField
              label="Currency"
              value={editPoForm.currency}
              onChange={(e) => setEditPoForm((prev) => ({ ...prev, currency: e.target.value }))}
            />
            <TextField
              label="Notes"
              value={editPoForm.notes}
              onChange={(e) => setEditPoForm((prev) => ({ ...prev, notes: e.target.value }))}
              multiline
              minRows={2}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => {
              setEditPoOpen(false)
              setEditingPoId(null)
              setEditPoDeleteConfirmOpen(false)
            }}
            disabled={updatePoMutation.isPending || deletePoMutation.isPending}
          >
            Cancel
          </Button>
          <Button
            color="error"
            variant="outlined"
            disabled={editingPoId === null || updatePoMutation.isPending || deletePoMutation.isPending}
            onClick={() => setEditPoDeleteConfirmOpen(true)}
          >
            Delete PO
          </Button>
          <Button
            variant="contained"
            disabled={
              updatePoMutation.isPending ||
              deletePoMutation.isPending ||
              editingPoId === null ||
              !editPoForm.po_number.trim() ||
              !editPoForm.vendor_id ||
              !editPoForm.order_date
            }
            onClick={() => {
              if (editingPoId === null) {
                return
              }
              updatePoMutation.mutate({
                poId: editingPoId,
                body: {
                  po_number: editPoForm.po_number.trim(),
                  vendor_id: editPoForm.vendor_id,
                  deliver_status: editPoForm.deliver_status,
                  order_date: editPoForm.order_date,
                  expected_delivery_date: editPoForm.expected_delivery_date || null,
                  tax_amount: Number(editPoForm.tax_amount || 0),
                  shipping_amount: Number(editPoForm.shipping_amount || 0),
                  handling_amount: Number(editPoForm.handling_amount || 0),
                  currency: editPoForm.currency.trim().toUpperCase().slice(0, 3) || 'USD',
                  tracking_number: editPoForm.tracking_number.trim() || null,
                  source: editPoForm.source.trim() || 'MANUAL',
                  is_stationery: editPoForm.is_stationery,
                  notes: editPoForm.notes.trim() || null,
                },
              })
            }}
          >
            {updatePoMutation.isPending ? 'Saving...' : 'Save Metadata'}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog
        open={editPoDeleteConfirmOpen}
        onClose={() => {
          if (!deletePoMutation.isPending) {
            setEditPoDeleteConfirmOpen(false)
          }
        }}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>Delete Purchase Order</DialogTitle>
        <DialogContent>
          <Typography>
            Delete purchase order <strong>{editPoForm.po_number || '-'}</strong>? This action cannot be undone.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditPoDeleteConfirmOpen(false)} disabled={deletePoMutation.isPending}>
            Cancel
          </Button>
          <Button
            color="error"
            variant="contained"
            disabled={editingPoId === null || deletePoMutation.isPending}
            onClick={() => {
              if (editingPoId === null) {
                return
              }
              deletePoMutation.mutate(editingPoId)
            }}
          >
            {deletePoMutation.isPending ? 'Deleting...' : 'Delete'}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={filtersDialogOpen} onClose={() => setFiltersDialogOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Purchase Filters</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <FormControl size="small" fullWidth>
              <InputLabel id="po-sort-by-label">Sort By</InputLabel>
              <Select
                labelId="po-sort-by-label"
                label="Sort By"
                value={sortBy}
                onChange={(e) => {
                  setSortBy(e.target.value as 'order_date' | 'po_number' | 'total_amount' | 'created_at')
                  setPage(0)
                }}
              >
                <MenuItem value="order_date">Order Date</MenuItem>
                <MenuItem value="po_number">PO Number</MenuItem>
                <MenuItem value="total_amount">Total Amount</MenuItem>
                <MenuItem value="created_at">Created At</MenuItem>
              </Select>
            </FormControl>

            <FormControl size="small" fullWidth>
              <InputLabel id="po-sort-dir-label">Sort Direction</InputLabel>
              <Select
                labelId="po-sort-dir-label"
                label="Sort Direction"
                value={sortDir}
                onChange={(e) => {
                  setSortDir(e.target.value as 'asc' | 'desc')
                  setPage(0)
                }}
              >
                <MenuItem value="desc">Newest first</MenuItem>
                <MenuItem value="asc">Oldest first</MenuItem>
              </Select>
            </FormControl>

            <FormControl size="small" fullWidth>
              <InputLabel id="po-status-filter-label">PO Status</InputLabel>
              <Select
                labelId="po-status-filter-label"
                label="PO Status"
                value={deliverStatusFilter}
                onChange={(e) => {
                  setDeliverStatusFilter(e.target.value as PurchaseDeliverStatus | 'ALL')
                  setPage(0)
                }}
              >
                <MenuItem value="ALL">All</MenuItem>
                <MenuItem value="CREATED">CREATED</MenuItem>
                <MenuItem value="BILLED">BILLED</MenuItem>
                <MenuItem value="DELIVERED">DELIVERED</MenuItem>
              </Select>
            </FormControl>

            <FormControl size="small" fullWidth>
              <InputLabel id="po-match-filter-label">Match State</InputLabel>
              <Select
                labelId="po-match-filter-label"
                label="Match State"
                value={itemMatchFilter}
                onChange={(e) => {
                  setItemMatchFilter(e.target.value as 'ALL' | 'MATCHED' | 'UNMATCHED')
                  setPage(0)
                }}
              >
                <MenuItem value="ALL">All</MenuItem>
                <MenuItem value="UNMATCHED">Has unmatched items</MenuItem>
                <MenuItem value="MATCHED">Fully matched</MenuItem>
              </Select>
            </FormControl>

            <FormControl size="small" fullWidth>
              <InputLabel id="po-zoho-filter-label">Zoho Sync Status</InputLabel>
              <Select
                labelId="po-zoho-filter-label"
                label="Zoho Sync Status"
                value={zohoSyncFilter}
                onChange={(e) => {
                  setZohoSyncFilter(e.target.value as ZohoSyncStatus | 'ALL')
                  setPage(0)
                }}
              >
                <MenuItem value="ALL">All</MenuItem>
                <MenuItem value="PENDING">PENDING</MenuItem>
                <MenuItem value="SYNCED">SYNCED</MenuItem>
                <MenuItem value="ERROR">ERROR</MenuItem>
                <MenuItem value="DIRTY">DIRTY</MenuItem>
              </Select>
            </FormControl>

            <FormControl size="small" fullWidth>
              <InputLabel id="po-source-filter-label">Source</InputLabel>
              <Select
                labelId="po-source-filter-label"
                label="Source"
                value={sourceFilter}
                onChange={(e) => {
                  setSourceFilter(e.target.value)
                  setPage(0)
                }}
              >
                <MenuItem value="ALL">All</MenuItem>
                <MenuItem value="MANUAL">MANUAL</MenuItem>
                <MenuItem value="GOODWILL_SHIPPED">GOODWILL_SHIPPED</MenuItem>
                <MenuItem value="GOODWILL_PICKUP">GOODWILL_PICKUP</MenuItem>
                <MenuItem value="AMAZON_CSV">AMAZON_CSV</MenuItem>
                <MenuItem value="ALIEXPRESS_JSON">ALIEXPRESS_JSON</MenuItem>
                <MenuItem value="ALIEXPRESS_CSV">ALIEXPRESS_CSV</MenuItem>
                <MenuItem value="EBAY_MEKONG_API">EBAY_MEKONG_API</MenuItem>
                <MenuItem value="EBAY_PURCHASING_API">EBAY_PURCHASING_API</MenuItem>
                <MenuItem value="EBAY_USAV_API">EBAY_USAV_API</MenuItem>
                <MenuItem value="EBAY_DRAGON_API">EBAY_DRAGON_API</MenuItem>
                <MenuItem value="ZOHO_IMPORT">ZOHO_IMPORT</MenuItem>
              </Select>
            </FormControl>

            <TextField
              size="small"
              type="number"
              label="Price Search"
              value={totalAmountSearch}
              onChange={(e) => {
                setTotalAmountSearch(e.target.value)
                setPage(0)
              }}
              inputProps={{ min: 0, step: 0.01 }}
            />

            <TextField
              size="small"
              type="number"
              label="Approx Range +/-"
              value={totalAmountRange}
              onChange={(e) => {
                setTotalAmountRange(e.target.value)
                setPage(0)
              }}
              inputProps={{ min: 0, step: 0.01 }}
            />

            <TextField
              size="small"
              type="date"
              label="From"
              InputLabelProps={{ shrink: true }}
              value={orderDateFrom}
              onChange={(e) => {
                setOrderDateFrom(e.target.value)
                setPage(0)
              }}
            />

            <TextField
              size="small"
              type="date"
              label="To"
              InputLabelProps={{ shrink: true }}
              value={orderDateTo}
              onChange={(e) => {
                setOrderDateTo(e.target.value)
                setPage(0)
              }}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => {
              clearAllFilters()
              setFiltersDialogOpen(false)
            }}
          >
            Clear All
          </Button>
          <Button onClick={() => setFiltersDialogOpen(false)} variant="contained">
            Apply
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={importZohoRangeOpen} onClose={() => setImportZohoRangeOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle>Import Range from Zoho</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              size="small"
              type="date"
              label="From"
              InputLabelProps={{ shrink: true }}
              value={importZohoRangeFrom}
              onChange={(e) => setImportZohoRangeFrom(e.target.value)}
            />
            <TextField
              size="small"
              type="date"
              label="To"
              InputLabelProps={{ shrink: true }}
              value={importZohoRangeTo}
              onChange={(e) => setImportZohoRangeTo(e.target.value)}
            />
            <Alert severity="info">Only Zoho purchase orders within this order date range will be imported.</Alert>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setImportZohoRangeOpen(false)} disabled={importZohoRangeMutation.isPending}>
            Cancel
          </Button>
          <Button
            variant="contained"
            disabled={
              importZohoRangeMutation.isPending ||
              !importZohoRangeFrom ||
              !importZohoRangeTo ||
              importZohoRangeFrom > importZohoRangeTo
            }
            onClick={() =>
              importZohoRangeMutation.mutate({
                orderDateFrom: importZohoRangeFrom,
                orderDateTo: importZohoRangeTo,
              })
            }
          >
            {importZohoRangeMutation.isPending ? 'Importing...' : 'Import'}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog
        open={bulkDialogOpen}
        onClose={bulkLoading ? undefined : () => setBulkDialogOpen(false)}
        fullWidth
        maxWidth="sm"
      >
        <DialogTitle>Sync purchase orders to Zoho</DialogTitle>
        <DialogContent dividers>
          <Stack spacing={2}>
            <Typography variant="body2" color="text.secondary">
              Queue purchase orders to Zoho for the selected date period.
              If no date filter is set, the latest purchase orders are queued.
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Unmatched items are automatically mapped to the placeholder item in Zoho.
            </Typography>
            <Stack spacing={1}>
              <Typography variant="body2">Queued purchase orders: {bulkTotal}</Typography>
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
                Queueing purchase orders to Zoho...
              </Alert>
            )}
            {bulkDone && !bulkLoading && !bulkError && bulkTotal > 0 && (
              <Alert severity="success">Purchase orders queued successfully.</Alert>
            )}
            {bulkDone && !bulkLoading && bulkTotal === 0 && (
              <Alert severity="info">No purchase orders found to queue for this period.</Alert>
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

      <Dialog open={importPurchaseOpen} onClose={() => setImportPurchaseOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle>Import Purchase</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <FormControl fullWidth size="small">
              <InputLabel id="purchase-import-source-label">Source</InputLabel>
              <Select
                labelId="purchase-import-source-label"
                value={purchaseImportSource}
                label="Source"
                onChange={(e) => setPurchaseImportSource(e.target.value as PurchaseFileImportSource)}
              >
                <MenuItem value="goodwill_shipped">Goodwill Shipped Orders (CSV)</MenuItem>
                <MenuItem value="goodwill_open">Goodwill Open Orders (CSV)</MenuItem>
                <MenuItem value="amazon">Amazon (CSV)</MenuItem>
                <MenuItem value="aliexpress">AliExpress (CSV / JSON)</MenuItem>
                <MenuItem value="ebay_mekong">eBay Mekong (API)</MenuItem>
                <MenuItem value="ebay_purchasing">eBay Purchasing (API)</MenuItem>
                <MenuItem value="ebay_usav">eBay USAV (API)</MenuItem>
                <MenuItem value="ebay_dragon">eBay Dragon (API)</MenuItem>
              </Select>
            </FormControl>
            <Alert severity="info">
              {purchaseImportSource === 'goodwill_open'
                ? 'Only rows with Status = View Order will be imported from open orders CSV.'
                : purchaseImportSource === 'aliexpress'
                ? 'Upload a CSV or JSON file exported from AliExpress orders.'
                : isEbayPurchaseSource
                  ? 'After continuing, choose the date range to import from eBay API.'
                  : 'Upload a CSV file exported from the selected source.'}
            </Alert>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => setImportPurchaseOpen(false)}
            disabled={importPurchaseFileMutation.isPending || importPurchaseEbayMutation.isPending}
          >
            Cancel
          </Button>
          <Button
            variant="contained"
            disabled={importPurchaseFileMutation.isPending || importPurchaseEbayMutation.isPending}
            onClick={() => {
              if (isEbayPurchaseSource) {
                setImportPurchaseEbayRangeFrom(orderDateFrom)
                setImportPurchaseEbayRangeTo(orderDateTo)
                setImportPurchaseEbayRangeOpen(true)
                setImportPurchaseOpen(false)
                return
              }
              purchaseFileInputRef.current?.click()
            }}
          >
            {isEbayPurchaseSource ? 'Continue' : 'Select File'}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog
        open={importPurchaseEbayRangeOpen}
        onClose={() => setImportPurchaseEbayRangeOpen(false)}
        fullWidth
        maxWidth="xs"
      >
        <DialogTitle>Import eBay Purchases</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label="From"
              type="date"
              value={importPurchaseEbayRangeFrom}
              onChange={(e) => setImportPurchaseEbayRangeFrom(e.target.value)}
              InputLabelProps={{ shrink: true }}
              fullWidth
            />
            <TextField
              label="To"
              type="date"
              value={importPurchaseEbayRangeTo}
              onChange={(e) => setImportPurchaseEbayRangeTo(e.target.value)}
              InputLabelProps={{ shrink: true }}
              fullWidth
            />
            <Alert severity="info">
              Source: {getPurchaseImportSourceLabel(purchaseImportSource).replace(' API', '')}
            </Alert>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setImportPurchaseEbayRangeOpen(false)} disabled={importPurchaseEbayMutation.isPending}>
            Cancel
          </Button>
          <Button
            variant="contained"
            disabled={
              importPurchaseEbayMutation.isPending ||
              !importPurchaseEbayRangeFrom ||
              !importPurchaseEbayRangeTo ||
              importPurchaseEbayRangeFrom > importPurchaseEbayRangeTo ||
              !isEbayPurchaseSource
            }
            onClick={() =>
              importPurchaseEbayMutation.mutate({
                source: purchaseImportSource as 'ebay_mekong' | 'ebay_purchasing' | 'ebay_usav' | 'ebay_dragon',
                orderDateFrom: importPurchaseEbayRangeFrom,
                orderDateTo: importPurchaseEbayRangeTo,
              })
            }
          >
            {importPurchaseEbayMutation.isPending ? 'Importing...' : 'Import'}
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
        ref={purchaseFileInputRef}
        type="file"
        accept={purchaseImportSource === 'aliexpress' ? '.csv,text/csv,.json,application/json' : '.csv,text/csv'}
        onChange={handlePurchaseImportSelected}
        hidden
        aria-label="Upload purchase import file"
        title="Upload purchase import file"
      />
    </Box>
  )
}

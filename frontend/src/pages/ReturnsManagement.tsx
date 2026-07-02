import { Fragment, useMemo, useState, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  Grid,
  IconButton,
  InputLabel,
  LinearProgress,
  MenuItem,
  Paper,
  Select,
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
  Tooltip,
  Menu,
  ListItemIcon,
  ListItemText,
} from '@mui/material'
import { KeyboardArrowDown, KeyboardArrowUp, Sync, DateRange, UploadFile, Refresh, ArrowDropDown, FilterList, NoteAlt, CloudSync } from '@mui/icons-material'

import SearchField from '../components/common/SearchField'
import LongPressTableRow from '../components/common/LongPressTableRow'
import HoldActionPromptDialog from '../components/common/HoldActionPromptDialog'
import { useAuth } from '../hooks/useAuth'
import TablePaginationWithPageJump from '../components/common/TablePaginationWithPageJump'
import { useDebouncedValue } from '../hooks/useDebouncedValue'
import {
  getReturnRecord,
  getReturnSyncStatus,
  listReturns,
  syncReturnToZoho,
  syncReturns,
  syncReturnsRange,
  importAmazonReturns,
  rematchReturnRecord,
  updateReturnRecord,
} from '../api/returns'
import type {
  ReturnListResponse,
  ReturnNormalizedStatus,
  ReturnPlatform,
  ReturnRecordBrief,
  ReturnRecordDetail,
  ReturnSyncResponse,
  ReturnSyncStatusResponse,
  ReturnZohoSyncStatus,
  ReturnZohoValidationResponse,
} from '../types/returns'

const PLATFORM_LABELS: Record<ReturnPlatform, string> = {
  AMAZON: 'Amazon',
  EBAY_MEKONG: 'eBay Mekong',
  EBAY_USAV: 'eBay USAV',
  EBAY_DRAGON: 'eBay Dragon',
  ECWID: 'Ecwid',
  SHOPIFY: 'Shopify',
  WALMART: 'Walmart',
  ZOHO: 'Zoho',
  MANUAL: 'Manual',
}

const STATUS_OPTIONS: ReturnNormalizedStatus[] = [
  'RETURNED',
  'PARTIALLY_RETURNED',
  'REFUNDED',
  'PARTIALLY_REFUNDED',
  'CANCELLED',
  'PARTIALLY_CANCELLED',
  'UNKNOWN',
  'UNMATCHED_ORDER',
]

const STATUS_COLORS: Record<ReturnNormalizedStatus, 'default' | 'success' | 'warning' | 'error' | 'info'> = {
  RETURNED: 'success',
  PARTIALLY_RETURNED: 'warning',
  REFUNDED: 'info',
  PARTIALLY_REFUNDED: 'warning',
  CANCELLED: 'error',
  PARTIALLY_CANCELLED: 'warning',
  UNKNOWN: 'default',
  UNMATCHED_ORDER: 'error',
}

const ZOHO_SYNC_COLORS: Record<ReturnZohoSyncStatus, 'default' | 'success' | 'warning' | 'error' | 'info'> = {
  PENDING: 'warning',
  READY_TO_SYNC: 'info',
  MISSING_LOCAL_ORDER: 'warning',
  MISSING_ZOHO_ORDER: 'warning',
  MISSING_LINE_ITEM_MAPPING: 'warning',
  QUANTITY_CONFLICT: 'warning',
  ALREADY_SYNCED: 'success',
  SYNCED: 'success',
  ERROR: 'error',
}

const SYNC_PLATFORM_OPTIONS = [
  { value: '', label: 'All Configured Platforms' },
  { value: 'ECWID', label: 'Ecwid' },
  { value: 'EBAY_MEKONG', label: 'eBay Mekong' },
  { value: 'EBAY_USAV', label: 'eBay USAV' },
  { value: 'EBAY_DRAGON', label: 'eBay Dragon' },
  { value: 'WALMART', label: 'Walmart' },
] as const

const VIEW_TO_CHANNEL: Record<'self' | 'fba', string> = {
  self: 'SELF_FULFILLED',
  fba: 'AMAZON_FBA',
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  try {
    return new Date(value).toLocaleDateString()
  } catch {
    return value
  }
}

function formatMoney(amount: string, currency: string): string {
  const numeric = Number(amount || 0)
  return `${currency} ${numeric.toFixed(2)}`
}

function formatStatusLabel(value: string): string {
  return value.replace(/_/g, ' ')
}

function SummaryCards({ counts, total }: { counts: Record<string, number>; total: number }) {
  const cards = [
    { label: 'All Records', value: total, color: 'text.primary' },
    { label: 'Returned', value: (counts.RETURNED || 0) + (counts.PARTIALLY_RETURNED || 0), color: 'success.main' },
    { label: 'Refunded', value: (counts.REFUNDED || 0) + (counts.PARTIALLY_REFUNDED || 0), color: 'info.main' },
    { label: 'Cancelled', value: (counts.CANCELLED || 0) + (counts.PARTIALLY_CANCELLED || 0), color: 'error.main' },
  ]

  return (
    <Grid container spacing={2}>
      {cards.map((card) => (
        <Grid item xs={12} sm={6} md={3} key={card.label}>
          <Paper sx={{ p: 2, height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
            <Typography variant="body2" color="text.secondary" gutterBottom>
              {card.label}
            </Typography>
            <Typography variant="h4" color={card.color}>
              {card.value}
            </Typography>
          </Paper>
        </Grid>
      ))}
    </Grid>
  )
}

export default function ReturnsManagement() {
  const { hasRole } = useAuth()
  const canEditReturn = hasRole(['ADMIN', 'SALES_REP'])

  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const returnView = searchParams.get('view') === 'fba' ? 'fba' : 'self'
  const fulfillmentChannel = VIEW_TO_CHANNEL[returnView]

  const [page, setPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(50)
  const [platformFilter, setPlatformFilter] = useState<ReturnPlatform | ''>('')
  const [statusFilter, setStatusFilter] = useState<ReturnNormalizedStatus | ''>('')
  const [sourceFilter, setSourceFilter] = useState('')
  const [orderedFromFilter, setOrderedFromFilter] = useState('')
  const [orderedToFilter, setOrderedToFilter] = useState('')
  const [eventFromFilter, setEventFromFilter] = useState('')
  const [eventToFilter, setEventToFilter] = useState('')
  const [sortBy, setSortBy] = useState<'event_at' | 'ordered_at' | 'refunded_amount' | 'external_order_id'>('event_at')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [searchInput, setSearchInput] = useState('')
  const debouncedSearch = useDebouncedValue(searchInput, 250)
  const [expandedId, setExpandedId] = useState<number | null>(null)

  const [syncDialogOpen, setSyncDialogOpen] = useState(false)
  const [syncPlatform, setSyncPlatform] = useState('')
  const [syncResults, setSyncResults] = useState<ReturnSyncResponse[] | null>(null)
  const [singleZohoResult, setSingleZohoResult] = useState<ReturnZohoValidationResponse | null>(null)
  const [syncingZohoReturnId, setSyncingZohoReturnId] = useState<number | null>(null)
  const [rematchingId, setRematchingId] = useState<number | null>(null)
  const [filtersDialogOpen, setFiltersDialogOpen] = useState(false)
  const [syncActionsAnchorEl, setSyncActionsAnchorEl] = useState<null | HTMLElement>(null)

  const [rangeDialogOpen, setRangeDialogOpen] = useState(false)
  const [rangePlatform, setRangePlatform] = useState('')
  const [rangeSince, setRangeSince] = useState('')
  const [rangeUntil, setRangeUntil] = useState('')
  const [rangeResults, setRangeResults] = useState<ReturnSyncResponse[] | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const activeFilterCount = [
    platformFilter !== '',
    statusFilter !== '',
    sourceFilter !== '',
    !!orderedFromFilter,
    !!orderedToFilter,
    !!eventFromFilter,
    !!eventToFilter,
    sortBy !== 'event_at',
    sortDir !== 'desc',
  ].filter(Boolean).length
  const hasActiveFilters = activeFilterCount > 0 || !!searchInput

  const [selectedReturn, setSelectedReturn] = useState<ReturnRecordBrief | null>(null)
  const [editDialogOpen, setEditDialogOpen] = useState(false)
  const [editNormalizedStatus, setEditNormalizedStatus] = useState<ReturnNormalizedStatus | ''>('')
  const [editReason, setEditReason] = useState('')
  const [editRefundedAmount, setEditRefundedAmount] = useState('')
  const [editZohoSyncStatus, setEditZohoSyncStatus] = useState<ReturnZohoSyncStatus | ''>('')
  const [snackbarMessage, setSnackbarMessage] = useState('')

  const handleEditClick = (row: ReturnRecordBrief) => {
    if (!canEditReturn) return
    setSelectedReturn(row)
    setEditNormalizedStatus(row.normalized_status)
    setEditReason(row.reason || '')
    setEditRefundedAmount(row.refunded_amount?.toString() || '0')
    setEditZohoSyncStatus(row.zoho_sync_status)
    setEditDialogOpen(true)
  }

  const updateMutation = useMutation({
    mutationFn: () => {
      if (!selectedReturn) throw new Error('No return selected')
      return updateReturnRecord(selectedReturn.id, {
        normalized_status: editNormalizedStatus ? (editNormalizedStatus as ReturnNormalizedStatus) : undefined,
        reason: editReason.trim() || undefined,
        refunded_amount: editRefundedAmount ? parseFloat(editRefundedAmount) : undefined,
        zoho_sync_status: editZohoSyncStatus ? (editZohoSyncStatus as ReturnZohoSyncStatus) : undefined,
      })
    },
    onSuccess: () => {
      setSnackbarMessage('Return updated successfully')
      setEditDialogOpen(false)
      void queryClient.invalidateQueries({ queryKey: ['returns'] })
      if (expandedId === selectedReturn?.id) {
        void queryClient.invalidateQueries({ queryKey: ['return-record', expandedId] })
      }
    },
    onError: (error) => {
      setSnackbarMessage(`Update failed: ${(error as Error).message}`)
    }
  })

  const resetFilters = () => {
    setPlatformFilter('')
    setStatusFilter('')
    setSourceFilter('')
    setOrderedFromFilter('')
    setOrderedToFilter('')
    setEventFromFilter('')
    setEventToFilter('')
    setSortBy('event_at')
    setSortDir('desc')
    setSearchInput('')
    setPage(0)
  }

  const returnsQuery = useQuery<ReturnListResponse>({
    queryKey: [
      'returns',
      returnView,
      page,
      rowsPerPage,
      platformFilter,
      statusFilter,
      sourceFilter,
      orderedFromFilter,
      orderedToFilter,
      eventFromFilter,
      eventToFilter,
      sortBy,
      sortDir,
      debouncedSearch,
    ],
    queryFn: () =>
      listReturns({
        skip: page * rowsPerPage,
        limit: rowsPerPage,
        fulfillment_channel: fulfillmentChannel,
        platform: platformFilter || undefined,
        normalized_status: statusFilter || undefined,
        source: sourceFilter || undefined,
        ordered_at_from: orderedFromFilter || undefined,
        ordered_at_to: orderedToFilter || undefined,
        event_at_from: eventFromFilter || undefined,
        event_at_to: eventToFilter || undefined,
        sort_by: sortBy,
        sort_dir: sortDir,
        search: debouncedSearch || undefined,
      }),
  })

  const syncStatusQuery = useQuery<ReturnSyncStatusResponse>({
    queryKey: ['returns-sync-status'],
    queryFn: () => getReturnSyncStatus(),
    refetchInterval: 15000,
  })

  const detailQuery = useQuery<ReturnRecordDetail>({
    queryKey: ['return-record', expandedId],
    queryFn: () => getReturnRecord(expandedId as number),
    enabled: expandedId !== null,
  })

  const syncMutation = useMutation({
    mutationFn: () => syncReturns(syncPlatform ? { platform: syncPlatform } : {}),
    onSuccess: (data) => {
      setSyncResults(data)
      void queryClient.invalidateQueries({ queryKey: ['returns'] })
      void queryClient.invalidateQueries({ queryKey: ['returns-sync-status'] })
    },
  })

  const importMutation = useMutation({
    mutationFn: (file: File) => importAmazonReturns(file),
    onSuccess: (data) => {
      setSyncResults([data])
      setSyncDialogOpen(true)
      void queryClient.invalidateQueries({ queryKey: ['returns'] })
      void queryClient.invalidateQueries({ queryKey: ['returns-sync-status'] })
    },
  })

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      importMutation.mutate(e.target.files[0])
      e.target.value = ''
    }
  }

  const rangeSyncMutation = useMutation({
    mutationFn: () =>
      syncReturnsRange({
        platform: rangePlatform || undefined,
        since: new Date(rangeSince).toISOString(),
        until: new Date(rangeUntil).toISOString(),
      }),
    onSuccess: (data) => {
      setRangeResults(data)
      void queryClient.invalidateQueries({ queryKey: ['returns'] })
      void queryClient.invalidateQueries({ queryKey: ['returns-sync-status'] })
    },
  })

  const zohoSyncMutation = useMutation({
    mutationFn: (recordId: number) => {
      setSyncingZohoReturnId(recordId)
      return syncReturnToZoho(recordId)
    },
    onSuccess: (data) => {
      setSingleZohoResult(data)
      void queryClient.invalidateQueries({ queryKey: ['returns'] })
      void queryClient.invalidateQueries({ queryKey: ['returns-sync-status'] })
      void queryClient.invalidateQueries({ queryKey: ['return-record', data.record_id] })
    },
    onSettled: () => setSyncingZohoReturnId(null),
  })

  const rematchMutation = useMutation({
    mutationFn: (recordId: number) => {
      setRematchingId(recordId)
      return rematchReturnRecord(recordId)
    },
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ['returns'] })
      void queryClient.invalidateQueries({ queryKey: ['returns-sync-status'] })
      void queryClient.invalidateQueries({ queryKey: ['return-record', data.id] })
    },
    onSettled: () => setRematchingId(null),
  })

  const syncAlerts = useMemo(
    () => (syncStatusQuery.data?.platforms || []).filter((entry) => entry.current_status === 'ERROR'),
    [syncStatusQuery.data],
  )

  return (
    <Box sx={{ p: 3 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3, gap: 2, flexWrap: 'wrap' }}>
        <Stack spacing={1}>
          <Typography variant="h4">Returns Management</Typography>
          <Stack direction="row" spacing={1}>
            <Button
              variant={returnView === 'self' ? 'contained' : 'outlined'}
              onClick={() => {
                setSearchParams({ view: 'self' })
                setPage(0)
              }}
            >
              Self-Fulfilled
            </Button>
            <Button
              variant={returnView === 'fba' ? 'contained' : 'outlined'}
              onClick={() => {
                setSearchParams({ view: 'fba' })
                setPage(0)
              }}
            >
              Amazon FBA
            </Button>
          </Stack>
        </Stack>
        <Stack direction="row" spacing={1}>
          <input
            type="file"
            accept=".csv,.tsv"
            style={{ display: 'none' }}
            ref={fileInputRef}
            onChange={handleFileChange}
          />
          <Tooltip title="Refresh">
            <IconButton
              onClick={() => {
                void queryClient.invalidateQueries({ queryKey: ['returns'] })
                void queryClient.invalidateQueries({ queryKey: ['returns-sync-status'] })
              }}
            >
              <Refresh />
            </IconButton>
          </Tooltip>
          <Button
            variant="outlined"
            onClick={(event) => setSyncActionsAnchorEl(event.currentTarget)}
            endIcon={<ArrowDropDown />}
            disabled={importMutation.isPending || syncMutation.isPending || rangeSyncMutation.isPending}
          >
            Sync Actions
          </Button>
          <Menu
            anchorEl={syncActionsAnchorEl}
            open={Boolean(syncActionsAnchorEl)}
            onClose={() => setSyncActionsAnchorEl(null)}
          >
            <MenuItem onClick={() => { setSyncActionsAnchorEl(null); fileInputRef.current?.click(); }}>
              <ListItemIcon><UploadFile fontSize="small" /></ListItemIcon>
              <ListItemText>{importMutation.isPending ? 'Importing...' : 'Import Amazon Return CSV/TSV'}</ListItemText>
            </MenuItem>
            <MenuItem onClick={() => { setSyncActionsAnchorEl(null); setSyncDialogOpen(true); }}>
              <ListItemIcon><Sync fontSize="small" /></ListItemIcon>
              <ListItemText>Sync Returns</ListItemText>
            </MenuItem>
            <MenuItem onClick={() => { setSyncActionsAnchorEl(null); setRangeDialogOpen(true); }}>
              <ListItemIcon><DateRange fontSize="small" /></ListItemIcon>
              <ListItemText>Sync Date Range</ListItemText>
            </MenuItem>
          </Menu>
        </Stack>
      </Box>

      {syncAlerts.length > 0 && (
        <Stack spacing={1} sx={{ mb: 2 }}>
          {syncAlerts.map((entry) => {
            return (
              <Alert key={entry.platform_name} severity="warning" sx={{ alignItems: 'flex-start' }}>
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                  <Typography variant="body2" fontWeight={500}>
                    {entry.platform_name} return sync failed.
                  </Typography>
                  <Typography variant="caption" sx={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap', wordBreak: 'break-all', opacity: 0.8 }}>
                    {entry.last_error_message || 'Unknown error'}
                  </Typography>
                </Box>
              </Alert>
            )
          })}
        </Stack>
      )}

      <Box sx={{ mb: 3 }}>
        <SummaryCards counts={returnsQuery.data?.summary_counts || {}} total={returnsQuery.data?.total || 0} />
      </Box>

      {singleZohoResult ? (
        <Alert
          severity={singleZohoResult.status === 'SYNCED' || singleZohoResult.status === 'ALREADY_SYNCED' ? 'success' : 'warning'}
          sx={{ mb: 2 }}
          onClose={() => setSingleZohoResult(null)}
        >
          Return {singleZohoResult.record_id}: {formatStatusLabel(singleZohoResult.status)}
          {singleZohoResult.zoho_salesreturn_number ? ` (${singleZohoResult.zoho_salesreturn_number})` : ''}
          {singleZohoResult.blockers.length ? ` - ${singleZohoResult.blockers.join('; ')}` : ''}
        </Alert>
      ) : null}
      {zohoSyncMutation.isError ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => zohoSyncMutation.reset()}>
          {(zohoSyncMutation.error as Error).message}
        </Alert>
      ) : null}

      <Paper sx={{ p: 2, mb: 2 }}>
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} alignItems={{ xs: 'stretch', md: 'center' }}>
          <Box sx={{ minWidth: 280, flex: 1 }}>
            <SearchField
              value={searchInput}
              onChange={setSearchInput}
              placeholder="Search order, return, customer, SKU..."
              fullWidth
              size="small"
            />
          </Box>
          <Button
            variant={activeFilterCount > 0 ? 'contained' : 'outlined'}
            startIcon={<FilterList />}
            onClick={() => setFiltersDialogOpen(true)}
          >
            Filters{activeFilterCount > 0 ? ` (${activeFilterCount})` : ''}
          </Button>
          <Button size="small" onClick={resetFilters} disabled={!hasActiveFilters}>
            Clear
          </Button>
        </Stack>
      </Paper>

      <Paper>
        {returnsQuery.isLoading ? <LinearProgress /> : null}
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell sx={{ width: 40 }} />
                <TableCell>Date</TableCell>
                <TableCell>Platform</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Order #</TableCell>
                <TableCell>Return #</TableCell>
                <TableCell>Customer</TableCell>
                <TableCell align="right">Refunded</TableCell>
                <TableCell align="right">Returned Qty</TableCell>
                <TableCell align="right">Cancelled Qty</TableCell>
                <TableCell>Zoho</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {(returnsQuery.data?.items || []).map((row: ReturnRecordBrief) => {
                const expanded = expandedId === row.id
                return (
                  <Fragment key={row.id}>
                    <LongPressTableRow
                      hover
                      payload={row}
                      rowSx={{ cursor: 'pointer', '& > *': { borderBottom: expanded ? 'unset' : undefined } }}
                      onClick={() => setExpandedId(expanded ? null : row.id)}
                      enableLongPress={canEditReturn}
                      onLongPress={() => handleEditClick(row)}
                    >
                      <TableCell sx={{ px: 1 }}>
                        <IconButton size="small">
                          {expanded ? <KeyboardArrowUp /> : <KeyboardArrowDown />}
                        </IconButton>
                      </TableCell>
                      <TableCell><Typography variant="body2">{formatDate(row.event_at)}</Typography></TableCell>
                      <TableCell>
                        <Chip size="small" variant="outlined" label={PLATFORM_LABELS[row.platform]} />
                      </TableCell>
                      <TableCell>
                        <Chip size="small" label={formatStatusLabel(row.normalized_status)} color={STATUS_COLORS[row.normalized_status]} variant="outlined" />
                      </TableCell>
                      <TableCell><Typography variant="body2" fontWeight={500}>{row.external_order_id}</Typography></TableCell>
                      <TableCell><Typography variant="body2">{row.external_return_id || '—'}</Typography></TableCell>
                      <TableCell>
                        <Typography variant="body2">{row.customer_name || '—'}</Typography>
                        {row.customer_email && <Typography variant="caption" color="text.secondary">{row.customer_email}</Typography>}
                      </TableCell>
                      <TableCell align="right"><Typography variant="body2">{formatMoney(row.refunded_amount, row.currency)}</Typography></TableCell>
                      <TableCell align="right"><Typography variant="body2">{row.returned_qty_total}</Typography></TableCell>
                      <TableCell align="right"><Typography variant="body2">{row.cancelled_qty_total}</Typography></TableCell>
                      <TableCell>
                        <Stack spacing={0.5} alignItems="flex-start">
                          <Chip
                            size="small"
                            variant="outlined"
                            label={formatStatusLabel(row.zoho_sync_status)}
                            color={ZOHO_SYNC_COLORS[row.zoho_sync_status]}
                          />
                          {row.zoho_salesreturn_number ? (
                            <Typography variant="caption" color="text.secondary">{row.zoho_salesreturn_number}</Typography>
                          ) : null}
                        </Stack>
                      </TableCell>
                      <TableCell align="right">
                        <Button
                          size="small"
                          variant="outlined"
                          startIcon={syncingZohoReturnId === row.id ? <CircularProgress size={14} /> : <CloudSync />}
                          disabled={
                            zohoSyncMutation.isPending ||
                            row.zoho_sync_status === 'SYNCED' ||
                            row.zoho_sync_status === 'ALREADY_SYNCED'
                          }
                          onClick={(e) => { e.stopPropagation(); zohoSyncMutation.mutate(row.id); }}
                        >
                          {syncingZohoReturnId === row.id ? 'Syncing...' : 'Zoho Sync'}
                        </Button>
                      </TableCell>
                    </LongPressTableRow>
                    <TableRow>
                      <TableCell colSpan={12} sx={{ py: 0, borderBottom: expanded ? undefined : 0 }}>
                        <Collapse in={expanded} timeout="auto" unmountOnExit>
                          <Box sx={{ p: 1.5, bgcolor: 'action.hover' }}>
                            {detailQuery.isLoading && expanded ? (
                              <CircularProgress size={20} />
                            ) : expanded && detailQuery.data?.id === row.id ? (
                              <>
                                <Stack
                                  direction="row"
                                  spacing={2}
                                  alignItems="center"
                                  sx={{ mb: 1.25, flexWrap: 'nowrap', overflow: 'hidden' }}
                                >
                                  <Box sx={{ minWidth: 120, maxWidth: 220, flexShrink: 1, overflow: 'hidden' }}>
                                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>Reason</Typography>
                                    <Typography variant="body2" sx={{ fontSize: '0.82rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{detailQuery.data.reason || '—'}</Typography>
                                  </Box>
                                  <Box sx={{ minWidth: 120, maxWidth: 220, flexShrink: 1, overflow: 'hidden' }}>
                                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>Source Status</Typography>
                                    <Typography variant="body2" sx={{ fontSize: '0.82rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{detailQuery.data.source_status || '—'}</Typography>
                                  </Box>
                                  <Box sx={{ minWidth: 120, maxWidth: 220, flexShrink: 1, overflow: 'hidden' }}>
                                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>Substatus</Typography>
                                    <Typography variant="body2" sx={{ fontSize: '0.82rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{detailQuery.data.source_substatus || '—'}</Typography>
                                  </Box>
                                  <Box sx={{ minWidth: 140, flexShrink: 0 }}>
                                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>Linked Order ID</Typography>
                                    <Typography variant="body2" sx={{ fontSize: '0.82rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{detailQuery.data.linked_order_id || '—'}</Typography>
                                  </Box>
                                  <Box sx={{ marginLeft: 'auto', flexShrink: 0 }}>
                                    <Stack direction="row" spacing={1}>
                                      <Button
                                        size="small"
                                        variant="outlined"
                                        disabled={rematchMutation.isPending || !!detailQuery.data.linked_order_id}
                                        onClick={() => rematchMutation.mutate(detailQuery.data.id)}
                                        startIcon={rematchingId === detailQuery.data.id ? <CircularProgress size={14} /> : <Sync />}
                                      >
                                        {rematchingId === detailQuery.data.id ? 'Rematching...' : 'Rematch'}
                                      </Button>
                                    </Stack>
                                  </Box>
                                </Stack>
                                {detailQuery.data.zoho_sync_error && (
                                  <Alert severity="error" sx={{ mb: 1.5, py: 0 }}>
                                    Zoho Error: {detailQuery.data.zoho_sync_error}
                                  </Alert>
                                )}
                                <Typography variant="subtitle2" sx={{ mb: 1 }}>
                                  Line Items
                                </Typography>
                                <Table size="small">
                                  <TableHead>
                                    <TableRow>
                                      <TableCell>Item Name</TableCell>
                                      <TableCell>Ext SKU</TableCell>
                                      <TableCell align="center">Ordered</TableCell>
                                      <TableCell align="center">Returned</TableCell>
                                      <TableCell align="center">Cancelled</TableCell>
                                      <TableCell align="right">Refunded</TableCell>
                                      <TableCell>Linked Order Item</TableCell>
                                    </TableRow>
                                  </TableHead>
                                  <TableBody>
                                    {detailQuery.data.items.map((item) => (
                                      <TableRow key={item.id} sx={{ '&:last-child td, &:last-child th': { border: 0 } }}>
                                        <TableCell>
                                          <Typography variant="body2" sx={{ maxWidth: 280, whiteSpace: 'normal', overflowWrap: 'anywhere', wordBreak: 'break-word' }}>
                                            {item.item_name}
                                          </Typography>
                                        </TableCell>
                                        <TableCell><Typography variant="body2">{item.external_sku || '—'}</Typography></TableCell>
                                        <TableCell align="center">{item.ordered_qty}</TableCell>
                                        <TableCell align="center">{item.returned_qty}</TableCell>
                                        <TableCell align="center">{item.cancelled_qty}</TableCell>
                                        <TableCell align="right">{formatMoney(item.refunded_amount, row.currency)}</TableCell>
                                        <TableCell>
                                          <Typography variant="body2">{item.linked_order_item_id || '—'}</Typography>
                                        </TableCell>
                                      </TableRow>
                                    ))}
                                  </TableBody>
                                </Table>
                              </>
                            ) : null}
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
        <TablePaginationWithPageJump
          count={returnsQuery.data?.total || 0}
          page={page}
          rowsPerPage={rowsPerPage}
          rowsPerPageOptions={[10, 25, 50, 100]}
          onPageChange={setPage}
          onRowsPerPageChange={(nextRows) => {
            setRowsPerPage(nextRows)
            setPage(0)
          }}
        />
      </Paper>

      <Dialog open={filtersDialogOpen} onClose={() => setFiltersDialogOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Return Filters</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <FormControl size="small" fullWidth>
              <InputLabel>Sort By</InputLabel>
              <Select
                value={sortBy}
                onChange={(e) => {
                  setSortBy(e.target.value as typeof sortBy)
                  setPage(0)
                }}
                label="Sort By"
              >
                <MenuItem value="event_at">Event At</MenuItem>
                <MenuItem value="ordered_at">Ordered At</MenuItem>
                <MenuItem value="refunded_amount">Refunded Amount</MenuItem>
                <MenuItem value="external_order_id">External Order ID</MenuItem>
              </Select>
            </FormControl>
            <FormControl size="small" fullWidth>
              <InputLabel>Direction</InputLabel>
              <Select
                value={sortDir}
                onChange={(e) => {
                  setSortDir(e.target.value as 'asc' | 'desc')
                  setPage(0)
                }}
                label="Direction"
              >
                <MenuItem value="desc">Desc</MenuItem>
                <MenuItem value="asc">Asc</MenuItem>
              </Select>
            </FormControl>
            <FormControl size="small" fullWidth>
              <InputLabel>Platform</InputLabel>
              <Select
                value={platformFilter}
                onChange={(e) => {
                  setPlatformFilter(e.target.value as ReturnPlatform | '')
                  setPage(0)
                }}
                label="Platform"
              >
                <MenuItem value="">All</MenuItem>
                {Object.entries(PLATFORM_LABELS).map(([value, label]) => (
                  <MenuItem key={value} value={value}>{label}</MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl size="small" fullWidth>
              <InputLabel>Status</InputLabel>
              <Select
                value={statusFilter}
                onChange={(e) => {
                  setStatusFilter(e.target.value as ReturnNormalizedStatus | '')
                  setPage(0)
                }}
                label="Status"
              >
                <MenuItem value="">All</MenuItem>
                {STATUS_OPTIONS.map((value) => (
                  <MenuItem key={value} value={value}>{formatStatusLabel(value)}</MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              fullWidth
              size="small"
              label="Source"
              value={sourceFilter}
              onChange={(e) => {
                setSourceFilter(e.target.value)
                setPage(0)
              }}
            />
            <TextField
              fullWidth
              size="small"
              type="date"
              label="Ordered From"
              value={orderedFromFilter}
              onChange={(e) => {
                setOrderedFromFilter(e.target.value)
                setPage(0)
              }}
              InputLabelProps={{ shrink: true }}
            />
            <TextField
              fullWidth
              size="small"
              type="date"
              label="Ordered To"
              value={orderedToFilter}
              onChange={(e) => {
                setOrderedToFilter(e.target.value)
                setPage(0)
              }}
              InputLabelProps={{ shrink: true }}
            />
            <TextField
              fullWidth
              size="small"
              type="date"
              label="Event From"
              value={eventFromFilter}
              onChange={(e) => {
                setEventFromFilter(e.target.value)
                setPage(0)
              }}
              InputLabelProps={{ shrink: true }}
            />
            <TextField
              fullWidth
              size="small"
              type="date"
              label="Event To"
              value={eventToFilter}
              onChange={(e) => {
                setEventToFilter(e.target.value)
                setPage(0)
              }}
              InputLabelProps={{ shrink: true }}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setFiltersDialogOpen(false)}>Close</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={syncDialogOpen} onClose={() => setSyncDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Sync Returns</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <FormControl fullWidth size="small">
              <InputLabel>Platform</InputLabel>
              <Select value={syncPlatform} label="Platform" onChange={(e) => setSyncPlatform(e.target.value)}>
                {SYNC_PLATFORM_OPTIONS.map((option) => (
                  <MenuItem key={option.value} value={option.value}>{option.label}</MenuItem>
                ))}
              </Select>
            </FormControl>
            {syncMutation.isError ? <Alert severity="error">{(syncMutation.error as Error).message}</Alert> : null}
            {syncResults ? (
              <Stack spacing={1}>
                {syncResults.map((result) => (
                  <Alert key={result.platform} severity={result.success ? 'success' : 'warning'}>
                    {result.platform}: new {result.new_records}, updated {result.updated_records}, linked orders {result.linked_orders}, linked items {result.linked_items}
                  </Alert>
                ))}
              </Stack>
            ) : null}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { setSyncDialogOpen(false); setSyncResults(null); syncMutation.reset() }}>Close</Button>
          {!syncResults ? (
            <Button variant="contained" onClick={() => syncMutation.mutate()} disabled={syncMutation.isPending} startIcon={syncMutation.isPending ? <CircularProgress size={18} /> : <Sync />}>
              {syncMutation.isPending ? 'Syncing...' : 'Start Sync'}
            </Button>
          ) : null}
        </DialogActions>
      </Dialog>

      <Dialog open={rangeDialogOpen} onClose={() => setRangeDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Sync Returns by Date Range</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <FormControl fullWidth size="small">
              <InputLabel>Platform</InputLabel>
              <Select value={rangePlatform} label="Platform" onChange={(e) => setRangePlatform(e.target.value)}>
                {SYNC_PLATFORM_OPTIONS.map((option) => (
                  <MenuItem key={option.value} value={option.value}>{option.label}</MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              label="Since"
              type="datetime-local"
              value={rangeSince}
              onChange={(e) => setRangeSince(e.target.value)}
              InputLabelProps={{ shrink: true }}
              fullWidth
              size="small"
            />
            <TextField
              label="Until"
              type="datetime-local"
              value={rangeUntil}
              onChange={(e) => setRangeUntil(e.target.value)}
              InputLabelProps={{ shrink: true }}
              fullWidth
              size="small"
            />
            {rangeSyncMutation.isError ? <Alert severity="error">{(rangeSyncMutation.error as Error).message}</Alert> : null}
            {rangeResults ? (
              <Stack spacing={1}>
                {rangeResults.map((result) => (
                  <Alert key={result.platform} severity={result.success ? 'success' : 'warning'}>
                    {result.platform}: new {result.new_records}, updated {result.updated_records}, linked orders {result.linked_orders}, linked items {result.linked_items}
                  </Alert>
                ))}
              </Stack>
            ) : null}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { setRangeDialogOpen(false); setRangeResults(null); rangeSyncMutation.reset() }}>Close</Button>
          {!rangeResults ? (
            <Button
              variant="contained"
              onClick={() => rangeSyncMutation.mutate()}
              disabled={rangeSyncMutation.isPending || !rangeSince || !rangeUntil}
              startIcon={rangeSyncMutation.isPending ? <CircularProgress size={18} /> : <DateRange />}
            >
              {rangeSyncMutation.isPending ? 'Syncing...' : 'Start Range Sync'}
            </Button>
          ) : null}
        </DialogActions>
      </Dialog>

      <HoldActionPromptDialog
        open={editDialogOpen}
        onClose={() => setEditDialogOpen(false)}
        title="Edit Return"
        onSave={() => updateMutation.mutate()}
        saveDisabled={!selectedReturn || !canEditReturn}
        saveLoading={updateMutation.isPending}
      >
        <Stack spacing={2} sx={{ mt: 1 }}>
          <FormControl fullWidth size="small">
            <InputLabel>Status</InputLabel>
            <Select
              value={editNormalizedStatus}
              onChange={(e) => setEditNormalizedStatus(e.target.value as ReturnNormalizedStatus)}
              label="Status"
            >
              {STATUS_OPTIONS.map((status) => (
                <MenuItem key={status} value={status}>{formatStatusLabel(status)}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <TextField
            fullWidth
            size="small"
            label="Reason"
            value={editReason}
            onChange={(e) => setEditReason(e.target.value)}
          />
          <TextField
            fullWidth
            size="small"
            label="Refunded Amount"
            type="number"
            value={editRefundedAmount}
            onChange={(e) => setEditRefundedAmount(e.target.value)}
          />
          <FormControl fullWidth size="small">
            <InputLabel>Zoho Sync Status</InputLabel>
            <Select
              value={editZohoSyncStatus}
              onChange={(e) => setEditZohoSyncStatus(e.target.value as ReturnZohoSyncStatus)}
              label="Zoho Sync Status"
            >
              {['PENDING', 'READY_TO_SYNC', 'MISSING_LOCAL_ORDER', 'MISSING_ZOHO_ORDER', 'MISSING_LINE_ITEM_MAPPING', 'QUANTITY_CONFLICT', 'ALREADY_SYNCED', 'SYNCED', 'ERROR'].map((s) => (
                <MenuItem key={s} value={s}>{formatStatusLabel(s)}</MenuItem>
              ))}
            </Select>
          </FormControl>
        </Stack>
      </HoldActionPromptDialog>

      <Snackbar open={!!snackbarMessage} autoHideDuration={4000} onClose={() => setSnackbarMessage('')}>
        <Alert onClose={() => setSnackbarMessage('')} severity="info">
          {snackbarMessage}
        </Alert>
      </Snackbar>
    </Box>
  )
}

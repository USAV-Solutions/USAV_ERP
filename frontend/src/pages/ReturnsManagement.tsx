import { Fragment, useMemo, useState } from 'react'
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
import { KeyboardArrowDown, KeyboardArrowUp, Sync, DateRange } from '@mui/icons-material'

import SearchField from '../components/common/SearchField'
import TablePaginationWithPageJump from '../components/common/TablePaginationWithPageJump'
import { useDebouncedValue } from '../hooks/useDebouncedValue'
import {
  getReturnRecord,
  getReturnSyncStatus,
  listReturns,
  syncReturnToZoho,
  syncReturns,
  syncReturnsRange,
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
]

const STATUS_COLORS: Record<ReturnNormalizedStatus, 'default' | 'success' | 'warning' | 'error' | 'info'> = {
  RETURNED: 'success',
  PARTIALLY_RETURNED: 'warning',
  REFUNDED: 'info',
  PARTIALLY_REFUNDED: 'warning',
  CANCELLED: 'error',
  PARTIALLY_CANCELLED: 'warning',
  UNKNOWN: 'default',
}

const ZOHO_SYNC_COLORS: Record<ReturnZohoSyncStatus, 'default' | 'success' | 'warning' | 'error' | 'info'> = {
  PENDING: 'default',
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

function formatDateTime(value: string | null): string {
  if (!value) return '—'
  try {
    return new Date(value).toLocaleString()
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
    { label: 'All Records', value: total },
    { label: 'Returned', value: (counts.RETURNED || 0) + (counts.PARTIALLY_RETURNED || 0) },
    { label: 'Refunded', value: (counts.REFUNDED || 0) + (counts.PARTIALLY_REFUNDED || 0) },
    { label: 'Cancelled', value: (counts.CANCELLED || 0) + (counts.PARTIALLY_CANCELLED || 0) },
  ]

  return (
    <Grid container spacing={2}>
      {cards.map((card) => (
        <Grid item xs={12} sm={6} md={3} key={card.label}>
          <Card>
            <CardContent sx={{ py: 1.5 }}>
              <Typography variant="body2" color="text.secondary">
                {card.label}
              </Typography>
              <Typography variant="h5">{card.value}</Typography>
            </CardContent>
          </Card>
        </Grid>
      ))}
    </Grid>
  )
}

export default function ReturnsManagement() {
  const queryClient = useQueryClient()
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

  const [rangeDialogOpen, setRangeDialogOpen] = useState(false)
  const [rangePlatform, setRangePlatform] = useState('')
  const [rangeSince, setRangeSince] = useState('')
  const [rangeUntil, setRangeUntil] = useState('')
  const [rangeResults, setRangeResults] = useState<ReturnSyncResponse[] | null>(null)

  const returnsQuery = useQuery<ReturnListResponse>({
    queryKey: [
      'returns',
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

  const syncAlerts = useMemo(
    () => (syncStatusQuery.data?.platforms || []).filter((entry) => entry.current_status === 'ERROR'),
    [syncStatusQuery.data],
  )

  return (
    <Box sx={{ p: 3 }}>
      <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={2} sx={{ mb: 3 }}>
        <Box>
          <Typography variant="h4">Returns</Typography>
          <Typography variant="body2" color="text.secondary">
            Read-only visibility for returns, refunds, and cancellations across marketplace APIs.
          </Typography>
        </Box>
        <Stack direction="row" spacing={1}>
          <Button variant="outlined" startIcon={<Sync />} onClick={() => setSyncDialogOpen(true)}>
            Sync Returns
          </Button>
          <Button variant="outlined" startIcon={<DateRange />} onClick={() => setRangeDialogOpen(true)}>
            Sync Date Range
          </Button>
        </Stack>
      </Stack>

      {syncAlerts.length > 0 && (
        <Stack spacing={1} sx={{ mb: 2 }}>
          {syncAlerts.map((entry) => (
            <Alert key={entry.platform_name} severity="warning">
              {entry.platform_name}: {entry.last_error_message || 'Sync failed'}
            </Alert>
          ))}
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
        <Grid container spacing={2}>
          <Grid item xs={12} md={3}>
            <SearchField value={searchInput} onChange={setSearchInput} placeholder="Search order, return, customer, SKU" fullWidth />
          </Grid>
          <Grid item xs={12} sm={6} md={2}>
            <FormControl fullWidth size="small">
              <InputLabel>Platform</InputLabel>
              <Select value={platformFilter} label="Platform" onChange={(e) => setPlatformFilter(e.target.value as ReturnPlatform | '')}>
                <MenuItem value="">All</MenuItem>
                {Object.entries(PLATFORM_LABELS).map(([value, label]) => (
                  <MenuItem key={value} value={value}>{label}</MenuItem>
                ))}
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12} sm={6} md={2}>
            <FormControl fullWidth size="small">
              <InputLabel>Status</InputLabel>
              <Select value={statusFilter} label="Status" onChange={(e) => setStatusFilter(e.target.value as ReturnNormalizedStatus | '')}>
                <MenuItem value="">All</MenuItem>
                {STATUS_OPTIONS.map((value) => (
                  <MenuItem key={value} value={value}>{formatStatusLabel(value)}</MenuItem>
                ))}
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12} sm={6} md={2}>
            <TextField size="small" label="Source" value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)} fullWidth />
          </Grid>
          <Grid item xs={6} md={2}>
            <TextField size="small" label="Ordered From" type="date" value={orderedFromFilter} onChange={(e) => setOrderedFromFilter(e.target.value)} fullWidth InputLabelProps={{ shrink: true }} />
          </Grid>
          <Grid item xs={6} md={2}>
            <TextField size="small" label="Ordered To" type="date" value={orderedToFilter} onChange={(e) => setOrderedToFilter(e.target.value)} fullWidth InputLabelProps={{ shrink: true }} />
          </Grid>
          <Grid item xs={6} md={2}>
            <TextField size="small" label="Event From" type="date" value={eventFromFilter} onChange={(e) => setEventFromFilter(e.target.value)} fullWidth InputLabelProps={{ shrink: true }} />
          </Grid>
          <Grid item xs={6} md={2}>
            <TextField size="small" label="Event To" type="date" value={eventToFilter} onChange={(e) => setEventToFilter(e.target.value)} fullWidth InputLabelProps={{ shrink: true }} />
          </Grid>
          <Grid item xs={12} sm={6} md={2}>
            <FormControl fullWidth size="small">
              <InputLabel>Sort By</InputLabel>
              <Select value={sortBy} label="Sort By" onChange={(e) => setSortBy(e.target.value as typeof sortBy)}>
                <MenuItem value="event_at">Event At</MenuItem>
                <MenuItem value="ordered_at">Ordered At</MenuItem>
                <MenuItem value="refunded_amount">Refunded Amount</MenuItem>
                <MenuItem value="external_order_id">External Order ID</MenuItem>
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12} sm={6} md={2}>
            <FormControl fullWidth size="small">
              <InputLabel>Direction</InputLabel>
              <Select value={sortDir} label="Direction" onChange={(e) => setSortDir(e.target.value as 'asc' | 'desc')}>
                <MenuItem value="desc">Desc</MenuItem>
                <MenuItem value="asc">Asc</MenuItem>
              </Select>
            </FormControl>
          </Grid>
        </Grid>
      </Paper>

      <Paper>
        {returnsQuery.isLoading ? <LinearProgress /> : null}
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell width={48} />
                <TableCell>Event</TableCell>
                <TableCell>Platform</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Order</TableCell>
                <TableCell>Return</TableCell>
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
                    <TableRow hover>
                      <TableCell>
                        <IconButton size="small" onClick={() => setExpandedId(expanded ? null : row.id)}>
                          {expanded ? <KeyboardArrowUp /> : <KeyboardArrowDown />}
                        </IconButton>
                      </TableCell>
                      <TableCell>{formatDateTime(row.event_at)}</TableCell>
                      <TableCell>{PLATFORM_LABELS[row.platform]}</TableCell>
                      <TableCell>
                        <Chip size="small" label={formatStatusLabel(row.normalized_status)} color={STATUS_COLORS[row.normalized_status]} />
                      </TableCell>
                      <TableCell>{row.external_order_id}</TableCell>
                      <TableCell>{row.external_return_id || '—'}</TableCell>
                      <TableCell>
                        <Typography variant="body2">{row.customer_name || '—'}</Typography>
                        <Typography variant="caption" color="text.secondary">{row.customer_email || ''}</Typography>
                      </TableCell>
                      <TableCell align="right">{formatMoney(row.refunded_amount, row.currency)}</TableCell>
                      <TableCell align="right">{row.returned_qty_total}</TableCell>
                      <TableCell align="right">{row.cancelled_qty_total}</TableCell>
                      <TableCell>
                        <Stack spacing={0.5}>
                          <Chip
                            size="small"
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
                          startIcon={syncingZohoReturnId === row.id ? <CircularProgress size={16} /> : <Sync />}
                          disabled={
                            zohoSyncMutation.isPending ||
                            row.zoho_sync_status === 'SYNCED' ||
                            row.zoho_sync_status === 'ALREADY_SYNCED'
                          }
                          onClick={() => zohoSyncMutation.mutate(row.id)}
                        >
                          {syncingZohoReturnId === row.id ? 'Syncing...' : 'Sync to Zoho'}
                        </Button>
                      </TableCell>
                    </TableRow>
                    <TableRow>
                      <TableCell colSpan={12} sx={{ py: 0, borderBottom: expanded ? undefined : 0 }}>
                        <Collapse in={expanded} timeout="auto" unmountOnExit>
                          <Box sx={{ p: 2, bgcolor: 'grey.50' }}>
                            {detailQuery.isLoading && expanded ? (
                              <CircularProgress size={20} />
                            ) : expanded && detailQuery.data?.id === row.id ? (
                              <Stack spacing={1.5}>
                                <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
                                  <Typography variant="body2"><strong>Reason:</strong> {detailQuery.data.reason || '—'}</Typography>
                                  <Typography variant="body2"><strong>Source Status:</strong> {detailQuery.data.source_status || '—'}</Typography>
                                  <Typography variant="body2"><strong>Substatus:</strong> {detailQuery.data.source_substatus || '—'}</Typography>
                                  <Typography variant="body2"><strong>Linked Order ID:</strong> {detailQuery.data.linked_order_id || '—'}</Typography>
                                  <Typography variant="body2"><strong>Zoho Error:</strong> {detailQuery.data.zoho_sync_error || '—'}</Typography>
                                </Stack>
                                <Table size="small">
                                  <TableHead>
                                    <TableRow>
                                      <TableCell>Item</TableCell>
                                      <TableCell>SKU</TableCell>
                                      <TableCell align="right">Ordered</TableCell>
                                      <TableCell align="right">Returned</TableCell>
                                      <TableCell align="right">Cancelled</TableCell>
                                      <TableCell align="right">Refunded</TableCell>
                                      <TableCell>Linked Order Item</TableCell>
                                    </TableRow>
                                  </TableHead>
                                  <TableBody>
                                    {detailQuery.data.items.map((item) => (
                                      <TableRow key={item.id}>
                                        <TableCell>{item.item_name}</TableCell>
                                        <TableCell>{item.external_sku || '—'}</TableCell>
                                        <TableCell align="right">{item.ordered_qty}</TableCell>
                                        <TableCell align="right">{item.returned_qty}</TableCell>
                                        <TableCell align="right">{item.cancelled_qty}</TableCell>
                                        <TableCell align="right">{formatMoney(item.refunded_amount, row.currency)}</TableCell>
                                        <TableCell>{item.linked_order_item_id || '—'}</TableCell>
                                      </TableRow>
                                    ))}
                                  </TableBody>
                                </Table>
                              </Stack>
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
          onPageChange={setPage}
          onRowsPerPageChange={(nextRows) => {
            setRowsPerPage(nextRows)
            setPage(0)
          }}
        />
      </Paper>

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
    </Box>
  )
}

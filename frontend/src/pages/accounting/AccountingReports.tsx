import { useMemo, useState, type SyntheticEvent } from 'react'
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  Grid,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  Typography,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import {
  exportPurchaseOrderReport,
  exportSalesOrderReport,
  fetchPurchaseOrderReport,
  fetchPurchaseOrderReportFilterOptions,
  fetchSalesOrderReport,
  fetchSalesOrderReportFilterOptions,
  type GroupBy,
  type OrderBy,
  type SalesGroupBy,
} from '../../api/accountingReports'

function toIsoDate(value: Date): string {
  return value.toISOString().slice(0, 10)
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

type ReportType = 'purchasing' | 'sale'
type ReportGroupBy = GroupBy | SalesGroupBy

interface ReportRow {
  group: string
  order_date: string
  order_number: string
  item: string
  sku: string
  source: string
  quantity: number
  total_price: string
  tax: string
  shipping: string
  handling: string
  counterparty: string
}

export default function AccountingReports() {
  const today = useMemo(() => new Date(), [])
  const initialStartDate = toIsoDate(new Date(today.getFullYear(), today.getMonth(), 1))
  const initialEndDate = toIsoDate(today)

  const [reportType, setReportType] = useState<ReportType>('purchasing')
  const [startDate, setStartDate] = useState<string>(initialStartDate)
  const [endDate, setEndDate] = useState<string>(initialEndDate)
  const [groupBy, setGroupBy] = useState<ReportGroupBy>('month')
  const [orderBy, setOrderBy] = useState<OrderBy>('date')
  const [filterOpen, setFilterOpen] = useState<boolean>(false)

  const [item, setItem] = useState<{ value: string; label: string }[]>([])
  const [source, setSource] = useState<string[]>([])
  const [counterparty, setCounterparty] = useState<string[]>([])
  const [poStatus, setPoStatus] = useState<string[]>([])

  const [appliedStartDate, setAppliedStartDate] = useState<string>(initialStartDate)
  const [appliedEndDate, setAppliedEndDate] = useState<string>(initialEndDate)
  const [appliedGroupBy, setAppliedGroupBy] = useState<ReportGroupBy>('month')
  const [appliedOrderBy, setAppliedOrderBy] = useState<OrderBy>('date')
  const [appliedItem, setAppliedItem] = useState<string[]>([])
  const [appliedSource, setAppliedSource] = useState<string[]>([])
  const [appliedCounterparty, setAppliedCounterparty] = useState<string[]>([])
  const [appliedPoStatus, setAppliedPoStatus] = useState<string[]>([])

  const [exporting, setExporting] = useState<'csv' | 'xlsx' | null>(null)
  const [exportError, setExportError] = useState<string>('')

  const isPurchasingReport = reportType === 'purchasing'

  const reportQuery = useQuery({
    queryKey: ['accounting-report', reportType, appliedStartDate, appliedEndDate, appliedGroupBy, appliedOrderBy, appliedItem, appliedSource, appliedCounterparty, appliedPoStatus],
    queryFn: async (): Promise<ReportRow[]> => {
      if (isPurchasingReport) {
        const rows = await fetchPurchaseOrderReport({
          startDate: appliedStartDate,
          endDate: appliedEndDate,
          groupBy: appliedGroupBy as GroupBy,
          orderBy: appliedOrderBy,
          item: appliedItem,
          source: appliedSource,
          vendor: appliedCounterparty,
          poStatus: appliedPoStatus,
        })
        return rows.map((row) => ({ ...row, counterparty: row.vendor }))
      }

      const rows = await fetchSalesOrderReport({
        startDate: appliedStartDate,
        endDate: appliedEndDate,
        groupBy: appliedGroupBy as SalesGroupBy,
        orderBy: appliedOrderBy,
        item: appliedItem,
        source: appliedSource,
        customer: appliedCounterparty,
      })
      return rows.map((row) => ({ ...row, counterparty: row.customer }))
    },
    staleTime: 60_000,
  })

  const filterOptionsQuery = useQuery({
    queryKey: ['accounting-report-filter-options', reportType, startDate, endDate],
    queryFn: async () => {
      if (isPurchasingReport) {
        const data = await fetchPurchaseOrderReportFilterOptions({ startDate, endDate })
        return {
          item_options: data.item_options,
          source_options: data.source_options,
          counterparty_options: data.vendor_options,
          po_status_options: data.po_status_options,
        }
      }
      const data = await fetchSalesOrderReportFilterOptions({ startDate, endDate })
      return {
        item_options: data.item_options,
        source_options: data.source_options,
        counterparty_options: data.customer_options,
        po_status_options: [],
      }
    },
    staleTime: 60_000,
    enabled: filterOpen,
  })

  const itemOptions = filterOptionsQuery.data?.item_options ?? []
  const sourceOptions = filterOptionsQuery.data?.source_options ?? []
  const counterpartyOptions = filterOptionsQuery.data?.counterparty_options ?? []
  const poStatusOptions = filterOptionsQuery.data?.po_status_options ?? []

  const applyFilter = () => {
    setAppliedStartDate(startDate)
    setAppliedEndDate(endDate)
    setAppliedGroupBy(groupBy)
    setAppliedOrderBy(orderBy)
    setAppliedItem(item.map((option) => option.value.trim()).filter(Boolean))
    setAppliedSource(source.map((value) => value.trim()).filter(Boolean))
    setAppliedCounterparty(counterparty.map((value) => value.trim()).filter(Boolean))
    setAppliedPoStatus(poStatus.map((value) => value.trim()).filter(Boolean))
    setFilterOpen(false)
  }

  const handleReportTypeChange = (_: SyntheticEvent, value: ReportType) => {
    setReportType(value)
    setGroupBy('month')
    setAppliedGroupBy('month')
    setItem([])
    setSource([])
    setCounterparty([])
    setPoStatus([])
    setAppliedItem([])
    setAppliedSource([])
    setAppliedCounterparty([])
    setAppliedPoStatus([])
    setExportError('')
  }

  const handleExport = async (fileType: 'csv' | 'xlsx') => {
    try {
      setExportError('')
      setExporting(fileType)
      if (isPurchasingReport) {
        const blob = await exportPurchaseOrderReport({
          startDate: appliedStartDate,
          endDate: appliedEndDate,
          groupBy: appliedGroupBy as GroupBy,
          orderBy: appliedOrderBy,
          item: appliedItem,
          source: appliedSource,
          vendor: appliedCounterparty,
          poStatus: appliedPoStatus,
          fileType,
        })
        downloadBlob(blob, `purchase_order_report_${appliedGroupBy}.${fileType}`)
      } else {
        const blob = await exportSalesOrderReport({
          startDate: appliedStartDate,
          endDate: appliedEndDate,
          groupBy: appliedGroupBy as SalesGroupBy,
          orderBy: appliedOrderBy,
          item: appliedItem,
          source: appliedSource,
          customer: appliedCounterparty,
          fileType,
        })
        downloadBlob(blob, `sales_order_report_${appliedGroupBy}.${fileType}`)
      }
    } catch {
      setExportError('Failed to export report')
    } finally {
      setExporting(null)
    }
  }

  return (
    <Card>
      <CardContent>
        <Typography variant="h4" gutterBottom>
          Accounting Reports
        </Typography>
        <Tabs value={reportType} onChange={handleReportTypeChange} sx={{ mb: 2 }}>
          <Tab label="Purchasing Report" value="purchasing" />
          <Tab label="Sale Report" value="sale" />
        </Tabs>
        <Grid container spacing={2} sx={{ mb: 2 }}>
          <Grid item xs={12} md={3}>
            <TextField
              fullWidth
              label="Start Date"
              type="date"
              value={startDate}
              onChange={(event) => setStartDate(event.target.value)}
              InputLabelProps={{ shrink: true }}
            />
          </Grid>
          <Grid item xs={12} md={3}>
            <TextField
              fullWidth
              label="End Date"
              type="date"
              value={endDate}
              onChange={(event) => setEndDate(event.target.value)}
              InputLabelProps={{ shrink: true }}
            />
          </Grid>
          <Grid item xs={12} md={3}>
            <FormControl fullWidth>
              <InputLabel id="order-by-label">Order By</InputLabel>
              <Select
                labelId="order-by-label"
                value={orderBy}
                label="Order By"
                onChange={(event) => setOrderBy(event.target.value as OrderBy)}
              >
                <MenuItem value="total_price">Total Price</MenuItem>
                <MenuItem value="quantity">Quantity</MenuItem>
                <MenuItem value="sku">SKU</MenuItem>
                <MenuItem value="source">Source</MenuItem>
                <MenuItem value="date">Date</MenuItem>
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12} md={3}>
            <FormControl fullWidth>
              <InputLabel id="group-by-label">Group By</InputLabel>
              <Select
                labelId="group-by-label"
                value={groupBy}
                label="Group By"
                onChange={(event) => setGroupBy(event.target.value as ReportGroupBy)}
              >
                <MenuItem value="sku">SKU</MenuItem>
                <MenuItem value="source">Source</MenuItem>
                <MenuItem value={isPurchasingReport ? 'vendor' : 'customer'}>
                  {isPurchasingReport ? 'Vendor' : 'Customer'}
                </MenuItem>
                <MenuItem value="week">Week</MenuItem>
                <MenuItem value="month">Month</MenuItem>
                <MenuItem value="quarter">Quarter</MenuItem>
                <MenuItem value="year">Year</MenuItem>
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12} md={3}>
            <Stack direction="row" spacing={1} sx={{ height: '100%', alignItems: 'center' }}>
              <Button variant="contained" onClick={() => setFilterOpen(true)}>Filter</Button>
            </Stack>
          </Grid>
        </Grid>

        <Dialog open={filterOpen} onClose={() => setFilterOpen(false)} fullWidth maxWidth="md">
          <DialogTitle>Filters</DialogTitle>
          <DialogContent>
            <Grid container spacing={2} sx={{ mt: 0.5 }}>
              <Grid item xs={12} md={6}>
                <Autocomplete
                  multiple
                  disableCloseOnSelect
                  options={itemOptions}
                  value={item}
                  onChange={(_, values) => setItem(values)}
                  loading={filterOptionsQuery.isLoading}
                  isOptionEqualToValue={(option, value) => option.value === value.value}
                  getOptionLabel={(option) => option.label}
                  renderInput={(params) => <TextField {...params} label="SKU / Name" placeholder="Search SKU or name and select" />}
                  renderOption={(props, option, { selected }) => (
                    <li {...props}>
                      <Checkbox checked={selected} sx={{ mr: 1 }} />
                      {option.label}
                    </li>
                  )}
                />
              </Grid>
              <Grid item xs={12} md={6}>
                <Autocomplete
                  multiple
                  disableCloseOnSelect
                  options={sourceOptions}
                  value={source}
                  onChange={(_, values) => setSource(values)}
                  loading={filterOptionsQuery.isLoading}
                  renderInput={(params) => <TextField {...params} label="Source" placeholder="Select sources" />}
                  renderOption={(props, option, { selected }) => (
                    <li {...props}>
                      <Checkbox checked={selected} sx={{ mr: 1 }} />
                      {option}
                    </li>
                  )}
                />
              </Grid>
              <Grid item xs={12} md={6}>
                <Autocomplete
                  multiple
                  disableCloseOnSelect
                  options={counterpartyOptions}
                  value={counterparty}
                  onChange={(_, values) => setCounterparty(values)}
                  loading={filterOptionsQuery.isLoading}
                  renderInput={(params) => (
                    <TextField
                      {...params}
                      label={isPurchasingReport ? 'Vendor' : 'Customer'}
                      placeholder={isPurchasingReport ? 'Search and select vendors' : 'Search and select customers'}
                    />
                  )}
                  renderOption={(props, option, { selected }) => (
                    <li {...props}>
                      <Checkbox checked={selected} sx={{ mr: 1 }} />
                      {option}
                    </li>
                  )}
                />
              </Grid>
              {isPurchasingReport ? (
                <Grid item xs={12} md={6}>
                  <Autocomplete
                    multiple
                    disableCloseOnSelect
                    options={poStatusOptions}
                    value={poStatus}
                    onChange={(_, values) => setPoStatus(values)}
                    loading={filterOptionsQuery.isLoading}
                    renderInput={(params) => <TextField {...params} label="PO Status" placeholder="Select PO status" />}
                    renderOption={(props, option, { selected }) => (
                      <li {...props}>
                        <Checkbox checked={selected} sx={{ mr: 1 }} />
                        {option}
                      </li>
                    )}
                  />
                </Grid>
              ) : null}
            </Grid>
            {filterOptionsQuery.error ? (
              <Alert severity="error" sx={{ mt: 2 }}>
                Failed to load filter options.
              </Alert>
            ) : null}
          </DialogContent>
          <DialogActions>
            <Button
              onClick={() => {
                setItem([])
                setSource([])
                setCounterparty([])
                setPoStatus([])
              }}
            >
              Clear
            </Button>
            <Button onClick={() => setFilterOpen(false)}>Cancel</Button>
            <Button variant="contained" onClick={applyFilter}>Apply Filter</Button>
          </DialogActions>
        </Dialog>

        <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
          <Button
            variant="contained"
            onClick={() => handleExport('csv')}
            disabled={exporting !== null}
          >
            {exporting === 'csv' ? 'Exporting CSV...' : 'Export CSV'}
          </Button>
          <Button
            variant="contained"
            onClick={() => handleExport('xlsx')}
            disabled={exporting !== null}
          >
            {exporting === 'xlsx' ? 'Exporting XLSX...' : 'Export XLSX'}
          </Button>
        </Stack>

        {exportError ? <Alert severity="error" sx={{ mb: 2 }}>{exportError}</Alert> : null}
        {reportQuery.error ? <Alert severity="error" sx={{ mb: 2 }}>Failed to load report data.</Alert> : null}

        {reportQuery.isLoading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress />
          </Box>
        ) : null}

        {!reportQuery.isLoading && (reportQuery.data?.length ?? 0) === 0 ? (
          <Alert severity="info">No data found for selected range and grouping.</Alert>
        ) : null}

        {(reportQuery.data?.length ?? 0) > 0 ? (
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Group</TableCell>
                  <TableCell>Order Date</TableCell>
                  <TableCell>Order Number</TableCell>
                  <TableCell>Item</TableCell>
                  <TableCell>SKU</TableCell>
                  <TableCell>Source</TableCell>
                  <TableCell align="right">Qty</TableCell>
                  <TableCell align="right">Total Price</TableCell>
                  <TableCell align="right">Tax</TableCell>
                  <TableCell align="right">Shipping</TableCell>
                  <TableCell align="right">Handling</TableCell>
                  <TableCell>{isPurchasingReport ? 'Vendor' : 'Customer'}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {(reportQuery.data ?? []).map((row, idx) => (
                  <TableRow key={`${row.group}-${idx}`}>
                    <TableCell>{row.group}</TableCell>
                    <TableCell>{row.order_date}</TableCell>
                    <TableCell>{row.order_number}</TableCell>
                    <TableCell>{row.item}</TableCell>
                    <TableCell>{row.sku}</TableCell>
                    <TableCell>{row.source}</TableCell>
                    <TableCell align="right">{row.quantity}</TableCell>
                    <TableCell align="right">{row.total_price}</TableCell>
                    <TableCell align="right">{row.tax}</TableCell>
                    <TableCell align="right">{row.shipping}</TableCell>
                    <TableCell align="right">{row.handling}</TableCell>
                    <TableCell>{row.counterparty}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        ) : null}
      </CardContent>
    </Card>
  )
}

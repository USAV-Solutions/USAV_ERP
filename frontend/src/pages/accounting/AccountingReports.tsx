import { useMemo, useState } from 'react'
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
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import {
  exportPurchaseOrderReport,
  fetchPurchaseOrderReport,
  fetchPurchaseOrderReportFilterOptions,
  type GroupBy,
  type OrderBy,
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

export default function AccountingReports() {
  const today = useMemo(() => new Date(), [])
  const initialStartDate = toIsoDate(new Date(today.getFullYear(), today.getMonth(), 1))
  const initialEndDate = toIsoDate(today)

  const [startDate, setStartDate] = useState<string>(initialStartDate)
  const [endDate, setEndDate] = useState<string>(initialEndDate)
  const [groupBy, setGroupBy] = useState<GroupBy>('month')
  const [orderBy, setOrderBy] = useState<OrderBy>('date')
  const [filterOpen, setFilterOpen] = useState<boolean>(false)

  const [item, setItem] = useState<{ value: string; label: string }[]>([])
  const [source, setSource] = useState<string[]>([])
  const [vendor, setVendor] = useState<string[]>([])

  const [appliedStartDate, setAppliedStartDate] = useState<string>(initialStartDate)
  const [appliedEndDate, setAppliedEndDate] = useState<string>(initialEndDate)
  const [appliedGroupBy, setAppliedGroupBy] = useState<GroupBy>('month')
  const [appliedOrderBy, setAppliedOrderBy] = useState<OrderBy>('date')
  const [appliedItem, setAppliedItem] = useState<string[]>([])
  const [appliedSource, setAppliedSource] = useState<string[]>([])
  const [appliedVendor, setAppliedVendor] = useState<string[]>([])

  const [exporting, setExporting] = useState<'csv' | 'xlsx' | null>(null)
  const [exportError, setExportError] = useState<string>('')

  const reportQuery = useQuery({
    queryKey: ['purchase-order-report', appliedStartDate, appliedEndDate, appliedGroupBy, appliedOrderBy, appliedItem, appliedSource, appliedVendor],
    queryFn: () => fetchPurchaseOrderReport({
      startDate: appliedStartDate,
      endDate: appliedEndDate,
      groupBy: appliedGroupBy,
      orderBy: appliedOrderBy,
      item: appliedItem,
      source: appliedSource,
      vendor: appliedVendor,
    }),
    staleTime: 60_000,
  })

  const filterOptionsQuery = useQuery({
    queryKey: ['purchase-order-report-filter-options', startDate, endDate],
    queryFn: () => fetchPurchaseOrderReportFilterOptions({ startDate, endDate }),
    staleTime: 60_000,
    enabled: filterOpen,
  })

  const itemOptions = filterOptionsQuery.data?.item_options ?? []
  const sourceOptions = filterOptionsQuery.data?.source_options ?? []
  const vendorOptions = filterOptionsQuery.data?.vendor_options ?? []

  const applyFilter = () => {
    setAppliedStartDate(startDate)
    setAppliedEndDate(endDate)
    setAppliedGroupBy(groupBy)
    setAppliedOrderBy(orderBy)
    setAppliedItem(item.map((option) => option.value.trim()).filter(Boolean))
    setAppliedSource(source.map((value) => value.trim()).filter(Boolean))
    setAppliedVendor(vendor.map((value) => value.trim()).filter(Boolean))
    setFilterOpen(false)
  }

  const handleExport = async (fileType: 'csv' | 'xlsx') => {
    try {
      setExportError('')
      setExporting(fileType)
      const blob = await exportPurchaseOrderReport({
        startDate: appliedStartDate,
        endDate: appliedEndDate,
        groupBy: appliedGroupBy,
        orderBy: appliedOrderBy,
        item: appliedItem,
        source: appliedSource,
        vendor: appliedVendor,
        fileType,
      })
      downloadBlob(blob, `purchase_order_report_${appliedGroupBy}.${fileType}`)
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
          Purchase Order Reports
        </Typography>
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
                onChange={(event) => setGroupBy(event.target.value as GroupBy)}
              >
                <MenuItem value="sku">SKU</MenuItem>
                <MenuItem value="source">Source</MenuItem>
                <MenuItem value="vendor">Vendor</MenuItem>
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
                  options={vendorOptions}
                  value={vendor}
                  onChange={(_, values) => setVendor(values)}
                  loading={filterOptionsQuery.isLoading}
                  renderInput={(params) => <TextField {...params} label="Vendor" placeholder="Search and select vendors" />}
                  renderOption={(props, option, { selected }) => (
                    <li {...props}>
                      <Checkbox checked={selected} sx={{ mr: 1 }} />
                      {option}
                    </li>
                  )}
                />
              </Grid>
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
                setVendor([])
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
                  <TableCell>Vendor</TableCell>
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
                    <TableCell>{row.vendor}</TableCell>
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

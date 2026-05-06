import { useMemo, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
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
  type GroupBy,
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
  const [startDate, setStartDate] = useState<string>(toIsoDate(new Date(today.getFullYear(), today.getMonth(), 1)))
  const [endDate, setEndDate] = useState<string>(toIsoDate(today))
  const [groupBy, setGroupBy] = useState<GroupBy>('month')
  const [exporting, setExporting] = useState<'csv' | 'xlsx' | null>(null)
  const [exportError, setExportError] = useState<string>('')

  const reportQuery = useQuery({
    queryKey: ['purchase-order-report', startDate, endDate, groupBy],
    queryFn: () => fetchPurchaseOrderReport({ startDate, endDate, groupBy }),
    staleTime: 60_000,
  })

  const quickThisWeek = () => {
    const now = new Date()
    const day = now.getDay() || 7
    const start = new Date(now)
    start.setDate(now.getDate() - day + 1)
    const end = new Date(start)
    end.setDate(start.getDate() + 6)
    setStartDate(toIsoDate(start))
    setEndDate(toIsoDate(end))
  }

  const quickThisMonth = () => {
    const now = new Date()
    setStartDate(toIsoDate(new Date(now.getFullYear(), now.getMonth(), 1)))
    setEndDate(toIsoDate(new Date(now.getFullYear(), now.getMonth() + 1, 0)))
  }

  const quickThisYear = () => {
    const now = new Date()
    setStartDate(toIsoDate(new Date(now.getFullYear(), 0, 1)))
    setEndDate(toIsoDate(new Date(now.getFullYear(), 11, 31)))
  }

  const handleExport = async (fileType: 'csv' | 'xlsx') => {
    try {
      setExportError('')
      setExporting(fileType)
      const blob = await exportPurchaseOrderReport({ startDate, endDate, groupBy, fileType })
      downloadBlob(blob, `purchase_order_report_${groupBy}.${fileType}`)
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
              <Button variant="outlined" onClick={quickThisWeek}>This Week</Button>
              <Button variant="outlined" onClick={quickThisMonth}>This Month</Button>
              <Button variant="outlined" onClick={quickThisYear}>This Year</Button>
            </Stack>
          </Grid>
        </Grid>

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

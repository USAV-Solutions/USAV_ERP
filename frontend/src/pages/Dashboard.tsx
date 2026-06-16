import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  Drawer,
  FormControl,
  Grid,
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
  TablePagination,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import {
  Inventory2,
  Paid,
  Percent,
  ShoppingCart,
  TrendingUp,
  Undo,
} from '@mui/icons-material'
import {
  BestSellingProductRow,
  BestSellingSortBy,
  fetchBestSellingPlatformBreakdown,
  fetchBestSellingProductDetail,
  fetchBestSellingProducts,
  fetchBestSellingSummary,
  fetchBestSellingTrends,
} from '../api/bestSellingDashboard'

const platforms = ['AMAZON', 'EBAY_MEKONG', 'EBAY_USAV', 'EBAY_DRAGON', 'ECWID', 'SHOPIFY', 'WALMART', 'ZOHO', 'MANUAL']

const sortOptions: { value: BestSellingSortBy; label: string }[] = [
  { value: 'qty_sold', label: 'Qty Sold' },
  { value: 'revenue', label: 'Revenue' },
  { value: 'gross_profit', label: 'Gross Profit' },
  { value: 'return_rate', label: 'Return Rate' },
  { value: 'inventory_left', label: 'Inventory Left' },
  { value: 'margin', label: 'Margin' },
]

function dateDaysAgo(days: number): string {
  const value = new Date()
  value.setDate(value.getDate() - days)
  return value.toISOString().slice(0, 10)
}

function formatMoney(value: number): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value)
}

function formatPercent(value: number): string {
  return `${value.toFixed(1)}%`
}

function KpiCard({
  title,
  value,
  subvalue,
  icon,
}: {
  title: string
  value: string
  subvalue?: string
  icon: React.ReactNode
}) {
  return (
    <Card sx={{ height: '100%', border: '1px solid', borderColor: 'divider' }}>
      <CardContent sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
        <Box sx={{ color: 'primary.main', display: 'flex' }}>{icon}</Box>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="body2" color="text.secondary" noWrap>
            {title}
          </Typography>
          <Typography variant="h5" fontWeight={700} noWrap>
            {value}
          </Typography>
          {subvalue && (
            <Typography variant="caption" color="text.secondary" noWrap>
              {subvalue}
            </Typography>
          )}
        </Box>
      </CardContent>
    </Card>
  )
}

function TopProductsChart({ rows }: { rows: BestSellingProductRow[] }) {
  const topRows = rows.slice(0, 10)
  const maxQty = Math.max(...topRows.map((row) => row.qty_sold), 1)

  return (
    <Paper sx={{ p: 2, height: '100%' }}>
      <Typography variant="h6" gutterBottom>
        Top 10 by Quantity
      </Typography>
      <Stack spacing={1.2}>
        {topRows.map((row) => (
          <Box key={`${row.sku}-${row.platform}`} sx={{ display: 'grid', gridTemplateColumns: 'minmax(120px, 190px) 1fr 48px', gap: 1, alignItems: 'center' }}>
            <Typography variant="body2" noWrap title={row.sku}>
              {row.sku}
            </Typography>
            <Box sx={{ bgcolor: 'grey.100', height: 10, borderRadius: 1, overflow: 'hidden' }}>
              <Box sx={{ width: `${(row.qty_sold / maxQty) * 100}%`, height: '100%', bgcolor: 'success.main' }} />
            </Box>
            <Typography variant="body2" align="right">
              {row.qty_sold}
            </Typography>
          </Box>
        ))}
        {topRows.length === 0 && (
          <Typography variant="body2" color="text.secondary">
            No data
          </Typography>
        )}
      </Stack>
    </Paper>
  )
}

export default function Dashboard() {
  const [startDate, setStartDate] = useState(dateDaysAgo(30))
  const [endDate, setEndDate] = useState(new Date().toISOString().slice(0, 10))
  const [platform, setPlatform] = useState('')
  const [search, setSearch] = useState('')
  const [appliedSearch, setAppliedSearch] = useState('')
  const [sortBy, setSortBy] = useState<BestSellingSortBy>('qty_sold')
  const [page, setPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(25)
  const [selectedSku, setSelectedSku] = useState<string | null>(null)

  const filters = useMemo(() => ({
    startDate,
    endDate,
    platform: platform || undefined,
  }), [endDate, platform, startDate])

  const productsFilters = useMemo(() => ({
    ...filters,
    search: appliedSearch || undefined,
    sortBy,
    sortDir: 'desc' as const,
    limit: rowsPerPage,
    offset: page * rowsPerPage,
  }), [appliedSearch, filters, page, rowsPerPage, sortBy])

  const summaryQuery = useQuery({
    queryKey: ['best-selling-summary', filters],
    queryFn: () => fetchBestSellingSummary(filters),
  })
  const productsQuery = useQuery({
    queryKey: ['best-selling-products', productsFilters],
    queryFn: () => fetchBestSellingProducts(productsFilters),
  })
  const platformQuery = useQuery({
    queryKey: ['best-selling-platforms', startDate, endDate],
    queryFn: () => fetchBestSellingPlatformBreakdown({ startDate, endDate }),
  })
  const trendsQuery = useQuery({
    queryKey: ['best-selling-trends', filters, selectedSku],
    queryFn: () => fetchBestSellingTrends({ ...filters, sku: selectedSku || undefined }),
  })
  const detailQuery = useQuery({
    queryKey: ['best-selling-product-detail', selectedSku, startDate, endDate],
    queryFn: () => fetchBestSellingProductDetail(selectedSku || '', { startDate, endDate }),
    enabled: Boolean(selectedSku),
  })

  const rows = productsQuery.data?.rows ?? []
  const summary = summaryQuery.data
  const totalRows = productsQuery.data?.total ?? 0
  const loading = summaryQuery.isLoading || productsQuery.isLoading

  return (
    <Box>
      <Paper sx={{ p: 2, mb: 3 }}>
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems={{ xs: 'stretch', md: 'center' }}>
          <TextField
            label="Start Date"
            type="date"
            size="small"
            value={startDate}
            onChange={(event) => {
              setPage(0)
              setStartDate(event.target.value)
            }}
            InputLabelProps={{ shrink: true }}
          />
          <TextField
            label="End Date"
            type="date"
            size="small"
            value={endDate}
            onChange={(event) => {
              setPage(0)
              setEndDate(event.target.value)
            }}
            InputLabelProps={{ shrink: true }}
          />
          <FormControl size="small" sx={{ minWidth: 170 }}>
            <InputLabel>Platform</InputLabel>
            <Select
              value={platform}
              label="Platform"
              onChange={(event) => {
                setPage(0)
                setPlatform(event.target.value)
              }}
            >
              <MenuItem value="">All Platforms</MenuItem>
              {platforms.map((item) => (
                <MenuItem value={item} key={item}>
                  {item}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <TextField
            label="SKU or Product"
            size="small"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                setPage(0)
                setAppliedSearch(search)
              }
            }}
            sx={{ minWidth: { md: 240 } }}
          />
          <Button
            variant="contained"
            onClick={() => {
              setPage(0)
              setAppliedSearch(search)
            }}
          >
            Search
          </Button>
          <FormControl size="small" sx={{ minWidth: 150 }}>
            <InputLabel>Sort</InputLabel>
            <Select
              value={sortBy}
              label="Sort"
              onChange={(event) => {
                setPage(0)
                setSortBy(event.target.value as BestSellingSortBy)
              }}
            >
              {sortOptions.map((option) => (
                <MenuItem value={option.value} key={option.value}>
                  {option.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </Stack>
      </Paper>

      {loading && <LinearProgress sx={{ mb: 2 }} />}
      {(summaryQuery.isError || productsQuery.isError) && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Failed to load dashboard data
        </Alert>
      )}

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={12} sm={6} md={2.4}>
          <KpiCard title="Units Sold" value={String(summary?.total_units_sold ?? 0)} subvalue={`${summary?.orders_included ?? 0} orders`} icon={<ShoppingCart />} />
        </Grid>
        <Grid item xs={12} sm={6} md={2.4}>
          <KpiCard title="Revenue" value={formatMoney(summary?.total_revenue ?? 0)} subvalue={`${summary?.sku_count ?? 0} SKUs`} icon={<Paid />} />
        </Grid>
        <Grid item xs={12} sm={6} md={2.4}>
          <KpiCard title="Gross Profit" value={formatMoney(summary?.gross_profit ?? 0)} subvalue={formatPercent(summary?.average_margin_percent ?? 0)} icon={<TrendingUp />} />
        </Grid>
        <Grid item xs={12} sm={6} md={2.4}>
          <KpiCard title="Return Rate" value={formatPercent(summary?.return_rate_percent ?? 0)} subvalue="Linked returns" icon={<Undo />} />
        </Grid>
        <Grid item xs={12} sm={6} md={2.4}>
          <KpiCard title="Low Stock Best Sellers" value={String(summary?.low_stock_best_sellers ?? 0)} subvalue="Top 10 SKUs" icon={<Inventory2 />} />
        </Grid>
      </Grid>

      <Stack spacing={1} sx={{ mb: 3 }}>
        {summary?.warnings.map((warning) => (
          <Alert severity={warning.severity} key={warning.code}>
            {warning.message} ({warning.count})
          </Alert>
        ))}
      </Stack>

      <Grid container spacing={3} sx={{ mb: 3 }}>
        <Grid item xs={12} lg={7}>
          <TopProductsChart rows={rows} />
        </Grid>
        <Grid item xs={12} lg={5}>
          <Paper sx={{ p: 2, height: '100%' }}>
            <Typography variant="h6" gutterBottom>
              Platform Breakdown
            </Typography>
            <Stack spacing={1.5}>
              {(platformQuery.data ?? []).map((row) => (
                <Box key={row.platform} sx={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 1 }}>
                  <Box>
                    <Typography variant="body2" fontWeight={600}>
                      {row.platform}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {row.qty_sold} units, {formatPercent(row.return_rate_percent)} returns
                    </Typography>
                  </Box>
                  <Box sx={{ textAlign: 'right' }}>
                    <Typography variant="body2">{formatMoney(row.revenue)}</Typography>
                    <Typography variant="caption" color="success.main">
                      {formatMoney(row.gross_profit)}
                    </Typography>
                  </Box>
                </Box>
              ))}
              {platformQuery.data?.length === 0 && (
                <Typography variant="body2" color="text.secondary">
                  No data
                </Typography>
              )}
            </Stack>
          </Paper>
        </Grid>
      </Grid>

      <Paper>
        <Box sx={{ p: 2 }}>
          <Typography variant="h6">Best-Selling SKUs</Typography>
        </Box>
        <Divider />
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Rank</TableCell>
                <TableCell>SKU</TableCell>
                <TableCell>Product</TableCell>
                <TableCell>Platform</TableCell>
                <TableCell align="right">Qty</TableCell>
                <TableCell align="right">Revenue</TableCell>
                <TableCell align="right">ASP</TableCell>
                <TableCell align="right">Cost</TableCell>
                <TableCell align="right">Gross Profit</TableCell>
                <TableCell align="right">Margin</TableCell>
                <TableCell align="right">Returns</TableCell>
                <TableCell align="right">Inventory</TableCell>
                <TableCell>Status</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((row) => (
                <TableRow
                  hover
                  key={`${row.rank}-${row.sku}-${row.platform}`}
                  onClick={() => setSelectedSku(row.sku)}
                  sx={{ cursor: 'pointer' }}
                >
                  <TableCell>{row.rank}</TableCell>
                  <TableCell sx={{ whiteSpace: 'nowrap' }}>{row.sku}</TableCell>
                  <TableCell sx={{ minWidth: 220 }}>{row.product_name}</TableCell>
                  <TableCell>{row.platform}</TableCell>
                  <TableCell align="right">{row.qty_sold}</TableCell>
                  <TableCell align="right">{formatMoney(row.revenue)}</TableCell>
                  <TableCell align="right">{formatMoney(row.average_selling_price)}</TableCell>
                  <TableCell align="right">{formatMoney(row.cost_of_goods_sold)}</TableCell>
                  <TableCell align="right">{formatMoney(row.gross_profit)}</TableCell>
                  <TableCell align="right">{formatPercent(row.gross_margin_percent)}</TableCell>
                  <TableCell align="right">
                    {row.return_qty} ({formatPercent(row.return_rate_percent)})
                  </TableCell>
                  <TableCell align="right">{row.inventory_left}</TableCell>
                  <TableCell sx={{ minWidth: 170 }}>
                    <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
                      {row.status_badges.map((badge) => (
                        <Chip key={badge} label={badge} size="small" />
                      ))}
                    </Stack>
                  </TableCell>
                </TableRow>
              ))}
              {rows.length === 0 && (
                <TableRow>
                  <TableCell colSpan={13}>
                    <Typography variant="body2" color="text.secondary" align="center" sx={{ py: 4 }}>
                      No data
                    </Typography>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
        <TablePagination
          component="div"
          count={totalRows}
          page={page}
          onPageChange={(_, nextPage) => setPage(nextPage)}
          rowsPerPage={rowsPerPage}
          onRowsPerPageChange={(event) => {
            setRowsPerPage(parseInt(event.target.value, 10))
            setPage(0)
          }}
          rowsPerPageOptions={[10, 25, 50, 100]}
        />
      </Paper>

      <Drawer anchor="right" open={Boolean(selectedSku)} onClose={() => setSelectedSku(null)}>
        <Box sx={{ width: { xs: 360, sm: 520 }, p: 3 }}>
          {detailQuery.isLoading && <LinearProgress sx={{ mb: 2 }} />}
          {detailQuery.data && (
            <Stack spacing={3}>
              <Box>
                <Typography variant="h6">{detailQuery.data.product.sku}</Typography>
                <Typography variant="body2" color="text.secondary">
                  {detailQuery.data.product.product_name}
                </Typography>
              </Box>
              <Grid container spacing={2}>
                <Grid item xs={6}>
                  <KpiCard title="Qty Sold" value={String(detailQuery.data.product.qty_sold)} icon={<ShoppingCart />} />
                </Grid>
                <Grid item xs={6}>
                  <KpiCard title="Gross Margin" value={formatPercent(detailQuery.data.product.gross_margin_percent)} icon={<Percent />} />
                </Grid>
              </Grid>
              <Box>
                <Typography variant="subtitle1" gutterBottom>
                  Platform Split
                </Typography>
                <Stack spacing={1}>
                  {detailQuery.data.platform_breakdown.map((row) => (
                    <Box key={row.platform} sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                      <Typography variant="body2">{row.platform}</Typography>
                      <Typography variant="body2">{row.qty_sold} units / {formatMoney(row.revenue)}</Typography>
                    </Box>
                  ))}
                </Stack>
              </Box>
              <Box>
                <Typography variant="subtitle1" gutterBottom>
                  Recent Orders
                </Typography>
                <Stack spacing={1}>
                  {detailQuery.data.recent_orders.map((order) => (
                    <Box key={`${order.order_id}-${order.external_order_id}`} sx={{ borderBottom: '1px solid', borderColor: 'divider', pb: 1 }}>
                      <Typography variant="body2" fontWeight={600}>
                        {order.external_order_id}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {order.platform} / {order.customer} / {order.qty} units / {formatMoney(order.revenue)}
                      </Typography>
                    </Box>
                  ))}
                </Stack>
              </Box>
              <Box>
                <Typography variant="subtitle1" gutterBottom>
                  Sales Trend
                </Typography>
                <Stack spacing={0.75}>
                  {(trendsQuery.data ?? []).slice(-10).map((point) => (
                    <Box key={point.date} sx={{ display: 'grid', gridTemplateColumns: '110px 1fr auto', gap: 1, alignItems: 'center' }}>
                      <Typography variant="caption">{point.date}</Typography>
                      <Box sx={{ bgcolor: 'grey.100', height: 8, borderRadius: 1, overflow: 'hidden' }}>
                        <Box sx={{ width: `${Math.min(point.qty_sold * 10, 100)}%`, height: '100%', bgcolor: 'primary.main' }} />
                      </Box>
                      <Typography variant="caption">{point.qty_sold}</Typography>
                    </Box>
                  ))}
                </Stack>
              </Box>
            </Stack>
          )}
          {detailQuery.isError && (
            <Alert severity="error">Failed to load SKU details</Alert>
          )}
        </Box>
      </Drawer>
    </Box>
  )
}

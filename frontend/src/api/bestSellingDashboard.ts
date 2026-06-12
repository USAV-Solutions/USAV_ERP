import axiosClient from './axiosClient'
import { BEST_SELLING_DASHBOARD } from './endpoints'

export type BestSellingSortBy = 'qty_sold' | 'revenue' | 'gross_profit' | 'return_rate' | 'inventory_left' | 'margin'
export type SortDir = 'asc' | 'desc'

export interface DataQualityWarning {
  code: string
  message: string
  count: number
  severity: 'warning' | 'info'
}

export interface BestSellingSummary {
  total_units_sold: number
  total_revenue: number
  gross_profit: number
  average_margin_percent: number
  return_rate_percent: number
  low_stock_best_sellers: number
  orders_included: number
  sku_count: number
  warnings: DataQualityWarning[]
}

export interface BestSellingProductRow {
  rank: number
  sku: string
  product_name: string
  platform: string
  qty_sold: number
  revenue: number
  average_selling_price: number
  cost_of_goods_sold: number
  allocated_shipping_cost: number
  gross_profit: number
  gross_margin_percent: number
  return_qty: number
  return_rate_percent: number
  inventory_left: number
  missing_cost_rows: number
  status_badges: string[]
}

export interface BestSellingProductsResponse {
  total: number
  rows: BestSellingProductRow[]
}

export interface TrendPoint {
  date: string
  qty_sold: number
  revenue: number
  gross_profit: number
}

export interface PlatformBreakdownRow {
  platform: string
  qty_sold: number
  revenue: number
  gross_profit: number
  return_rate_percent: number
}

export interface RecentOrderRow {
  order_id: number
  external_order_id: string
  ordered_at: string | null
  platform: string
  customer: string
  qty: number
  revenue: number
}

export interface BestSellingProductDetail {
  product: BestSellingProductRow
  platform_breakdown: PlatformBreakdownRow[]
  recent_orders: RecentOrderRow[]
}

interface DashboardParams {
  startDate?: string
  endDate?: string
  platform?: string
  search?: string
  sortBy?: BestSellingSortBy
  sortDir?: SortDir
  limit?: number
  offset?: number
  sku?: string
}

function queryString(params: DashboardParams): string {
  const query = new URLSearchParams()
  if (params.startDate) query.set('start_date', params.startDate)
  if (params.endDate) query.set('end_date', params.endDate)
  if (params.platform) query.set('platform', params.platform)
  if (params.search) query.set('search', params.search)
  if (params.sortBy) query.set('sort_by', params.sortBy)
  if (params.sortDir) query.set('sort_dir', params.sortDir)
  if (params.limit) query.set('limit', String(params.limit))
  if (params.offset) query.set('offset', String(params.offset))
  if (params.sku) query.set('sku', params.sku)
  return query.toString()
}

export async function fetchBestSellingSummary(params: DashboardParams): Promise<BestSellingSummary> {
  const query = queryString(params)
  const { data } = await axiosClient.get<BestSellingSummary>(
    `${BEST_SELLING_DASHBOARD.SUMMARY}${query ? `?${query}` : ''}`,
  )
  return data
}

export async function fetchBestSellingProducts(params: DashboardParams): Promise<BestSellingProductsResponse> {
  const query = queryString(params)
  const { data } = await axiosClient.get<BestSellingProductsResponse>(
    `${BEST_SELLING_DASHBOARD.PRODUCTS}${query ? `?${query}` : ''}`,
  )
  return data
}

export async function fetchBestSellingTrends(params: DashboardParams): Promise<TrendPoint[]> {
  const query = queryString(params)
  const { data } = await axiosClient.get<TrendPoint[]>(
    `${BEST_SELLING_DASHBOARD.TRENDS}${query ? `?${query}` : ''}`,
  )
  return data
}

export async function fetchBestSellingPlatformBreakdown(params: DashboardParams): Promise<PlatformBreakdownRow[]> {
  const query = queryString(params)
  const { data } = await axiosClient.get<PlatformBreakdownRow[]>(
    `${BEST_SELLING_DASHBOARD.PLATFORM_BREAKDOWN}${query ? `?${query}` : ''}`,
  )
  return data
}

export async function fetchBestSellingProductDetail(
  sku: string,
  params: DashboardParams,
): Promise<BestSellingProductDetail> {
  const query = queryString(params)
  const { data } = await axiosClient.get<BestSellingProductDetail>(
    `${BEST_SELLING_DASHBOARD.PRODUCT(sku)}${query ? `?${query}` : ''}`,
  )
  return data
}


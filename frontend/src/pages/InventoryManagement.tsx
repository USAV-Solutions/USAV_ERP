import { useState, useMemo, useEffect } from 'react'
import {
  Box,
  Typography,
  Button,
  Alert,
  Snackbar,
  Paper,
  TextField,
  InputAdornment,
  ToggleButton,
  ToggleButtonGroup,
  Chip,
  IconButton,
  Tooltip,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TablePagination,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  CircularProgress,
  LinearProgress,
} from '@mui/material'
import {
  Add,
  Search,
  ViewList,
  ViewModule,
  ExpandMore,
  ExpandLess,
} from '@mui/icons-material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AxiosError } from 'axios'
import axiosClient from '../api/axiosClient'
import { CATALOG, IMAGES, ZOHO } from '../api/endpoints'
import { Variant, ProductIdentity, ProductFamily, ProductType } from '../types/inventory'
import { useAuth } from '../hooks/useAuth'
import CreateProductDialog from '../components/inventory/CreateProductDialog'
import ProductThumbnail from '../components/inventory/ProductThumbnail'
import ImageGalleryModal from '../components/inventory/ImageGalleryModal'

type ViewMode = 'list' | 'grouped'

interface ExpandedRowProps {
  familyName: string
  variants: EnhancedVariant[]
}

interface EnhancedVariant extends Variant {
  identity?: ProductIdentity & { family?: ProductFamily }
}

interface GroupedItem {
  product_id: number
  name: string
  brand?: string
  variant_count: number
  variants: EnhancedVariant[]
}

interface ThumbnailBackfillResponse {
  processed: number
  updated: number
  failed: number
  remaining_null_thumbnail_url: number
}

interface ZohoSyncProgressResponse {
  job_id: string
  status: 'queued' | 'running' | 'stopping' | 'stopped' | 'completed' | 'failed'
  started_at: string
  finished_at?: string | null
  total_target: number
  total_processed: number
  total_success: number
  total_failed: number
  current_sku?: string | null
  cancel_requested: boolean
  last_error?: string | null
}

interface ZohoReadinessItem {
  variant_id: number
  sku: string
  identity_type: string
  ready: boolean
  severity: 'ok' | 'warning' | 'error'
  missing_fields: string[]
  warnings: string[]
}

interface ZohoReadinessResponse {
  total_checked: number
  ready_count: number
  blocked_count: number
  warning_only_count: number
  items: ZohoReadinessItem[]
}

const getTypeLabel = (type: ProductType): string => {
  const labels: Record<ProductType, string> = {
    Product: 'Product',
    P: 'Part',
    B: 'Bundle',
    K: 'Kit',
  }
  return labels[type] || type
}

const getTypeColor = (type: ProductType): 'primary' | 'secondary' | 'success' | 'warning' => {
  const colors: Record<ProductType, 'primary' | 'secondary' | 'success' | 'warning'> = {
    Product: 'primary',
    P: 'secondary',
    B: 'success',
    K: 'warning',
  }
  return colors[type] || 'primary'
}

const getSyncStatusChip = (status: string) => {
  type ChipColor = 'success' | 'warning' | 'error' | 'default'
  const configs: Record<string, { color: ChipColor; label: string }> = {
    SYNCED: { color: 'success', label: '🟢 Synced' },
    PENDING: { color: 'warning', label: '🟡 Pending' },
    ERROR: { color: 'error', label: '🔴 Error' },
    DIRTY: { color: 'warning', label: '🟡 Dirty' },
  }
  const config = configs[status] || { color: 'default' as ChipColor, label: status }
  return <Chip size="small" color={config.color} label={config.label} />
}

function ExpandedRow({ familyName, variants }: ExpandedRowProps) {
  const [gallerySku, setGallerySku] = useState<string | null>(null)

  return (
    <TableRow>
      <TableCell colSpan={8} sx={{ py: 0, bgcolor: 'grey.50' }}>
        <Box sx={{ py: 2, px: 4 }}>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            Variants for {familyName}
          </Typography>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell width={60}>Image</TableCell>
                <TableCell>Full SKU</TableCell>
                <TableCell>Type</TableCell>
                <TableCell>UPIS-H</TableCell>
                <TableCell>Color</TableCell>
                <TableCell>Condition</TableCell>
                <TableCell>Zoho Status</TableCell>
                <TableCell>Active</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {variants.map((variant) => (
                <TableRow key={variant.id}>
                  <TableCell>
                    <ProductThumbnail
                      sku={variant.full_sku}
                      thumbnailUrl={variant.thumbnail_url}
                      size={36}
                      onClick={() => setGallerySku(variant.full_sku)}
                    />
                  </TableCell>
                  <TableCell>{variant.full_sku}</TableCell>
                  <TableCell>
                    <Chip
                      size="small"
                      label={getTypeLabel(variant.identity?.type || 'Product')}
                      color={getTypeColor(variant.identity?.type || 'Product')}
                    />
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2" fontFamily="monospace">
                      {variant.identity?.generated_upis_h || '-'}
                    </Typography>
                  </TableCell>
                  <TableCell>{variant.color_code || '-'}</TableCell>
                  <TableCell>{variant.condition_code || 'Used'}</TableCell>
                  <TableCell>{getSyncStatusChip(variant.zoho_sync_status)}</TableCell>
                  <TableCell>
                    <Chip
                      size="small"
                      label={variant.is_active ? 'Active' : 'Inactive'}
                      color={variant.is_active ? 'success' : 'default'}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
        {gallerySku && (
          <ImageGalleryModal
            open={!!gallerySku}
            onClose={() => setGallerySku(null)}
            sku={gallerySku}
          />
        )}
      </TableCell>
    </TableRow>
  )
}

export default function InventoryManagement() {
  const [viewMode, setViewMode] = useState<ViewMode>('list')
  const [searchQuery, setSearchQuery] = useState('')
  const [createDialogOpen, setCreateDialogOpen] = useState(false)
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set())
  const [page, setPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(25)
  const [gallerySku, setGallerySku] = useState<string | null>(null)
  const [snackbarOpen, setSnackbarOpen] = useState(false)
  const [snackbarMessage, setSnackbarMessage] = useState('')
  const [snackbarSeverity, setSnackbarSeverity] = useState<'success' | 'error'>('success')
  const [readinessDialogOpen, setReadinessDialogOpen] = useState(false)
  const [readinessData, setReadinessData] = useState<ZohoReadinessResponse | null>(null)
  const { hasRole } = useAuth()
  const queryClient = useQueryClient()

  const backfillThumbnailsMutation = useMutation({
    mutationFn: async () => {
      const response = await axiosClient.post(IMAGES.DEBUG_BACKFILL)
      return response.data
    },
    onSuccess: async (data: ThumbnailBackfillResponse) => {
      setSnackbarSeverity('success')
      setSnackbarMessage(
        `Thumbnail backfill completed: ${data.updated} updated, ${data.failed} failed, ${data.remaining_null_thumbnail_url} remaining.`
      )
      setSnackbarOpen(true)
      await queryClient.invalidateQueries({ queryKey: ['variants'] })
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      const detail = error.response?.data?.detail || 'Failed to run thumbnail backfill.'
      setSnackbarSeverity('error')
      setSnackbarMessage(detail)
      setSnackbarOpen(true)
    },
  })

  const zohoBulkSyncMutation = useMutation({
    mutationFn: async () => {
      const response = await axiosClient.post<ZohoSyncProgressResponse>(ZOHO.SYNC_ITEMS_START, {
        include_images: true,
        include_composites: true,
        force_resync: true,
        limit: 5000,
      })
      return response.data
    },
    onSuccess: async () => {
      setSnackbarSeverity('success')
      setSnackbarMessage('Zoho sync started.')
      setSnackbarOpen(true)
      await queryClient.invalidateQueries({ queryKey: ['zoho-sync-progress'] })
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      const detail = error.response?.data?.detail || 'Zoho sync start failed.'
      setSnackbarSeverity('error')
      setSnackbarMessage(detail)
      setSnackbarOpen(true)
    },
  })

  const zohoStopSyncMutation = useMutation({
    mutationFn: async () => {
      const response = await axiosClient.post<ZohoSyncProgressResponse>(ZOHO.SYNC_ITEMS_STOP)
      return response.data
    },
    onSuccess: async () => {
      setSnackbarSeverity('success')
      setSnackbarMessage('Stop requested for Zoho sync job.')
      setSnackbarOpen(true)
      await queryClient.invalidateQueries({ queryKey: ['zoho-sync-progress'] })
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      const detail = error.response?.data?.detail || 'Failed to stop Zoho sync.'
      setSnackbarSeverity('error')
      setSnackbarMessage(detail)
      setSnackbarOpen(true)
    },
  })

  const { data: zohoSyncProgress } = useQuery<ZohoSyncProgressResponse | null>({
    queryKey: ['zoho-sync-progress'],
    queryFn: async () => {
      try {
        const response = await axiosClient.get<ZohoSyncProgressResponse>(ZOHO.SYNC_ITEMS_PROGRESS)
        return response.data
      } catch (error) {
        const axiosError = error as AxiosError<{ detail?: string }>
        if (axiosError.response?.status === 404) {
          return null
        }
        throw error
      }
    },
    refetchInterval: (query) => {
      const data = query.state.data as ZohoSyncProgressResponse | null | undefined
      if (!data) return false
      return ['queued', 'running', 'stopping'].includes(data.status) ? 1500 : false
    },
  })

  const handleStartZohoSync = async () => {
    await zohoBulkSyncMutation.mutateAsync()
  }

  const runningStatus = zohoSyncProgress?.status
  const isZohoSyncRunning = !!runningStatus && ['queued', 'running', 'stopping'].includes(runningStatus)
  const zohoProgressPct =
    zohoSyncProgress && zohoSyncProgress.total_target > 0
      ? Math.min(100, Math.round((zohoSyncProgress.total_processed / zohoSyncProgress.total_target) * 100))
      : 0

  useEffect(() => {
    if (zohoSyncProgress?.status === 'completed' && zohoSyncProgress.total_target > 0) {
      void queryClient.invalidateQueries({ queryKey: ['variants'] })
    }
  }, [zohoSyncProgress?.status, zohoSyncProgress?.total_target, queryClient])

  const zohoReadinessMutation = useMutation({
    mutationFn: async () => {
      const response = await axiosClient.post<ZohoReadinessResponse>(ZOHO.SYNC_READINESS, {
        include_images: true,
        include_composites: true,
        only_unsynced: false,
        limit: 5000,
      })
      return response.data
    },
    onSuccess: (data: ZohoReadinessResponse) => {
      setReadinessData(data)
      setReadinessDialogOpen(true)
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      const detail = error.response?.data?.detail || 'Zoho readiness check failed.'
      setSnackbarSeverity('error')
      setSnackbarMessage(detail)
      setSnackbarOpen(true)
    },
  })

  // Fetch variants with identity data
  const { data: variantsData, isLoading: variantsLoading } = useQuery({
    queryKey: ['variants'],
    queryFn: async () => {
      const response = await axiosClient.get(CATALOG.VARIANTS, {
        params: { limit: 1000 }
      })
      return response.data.items || []
    },
  })

  // Fetch identities with family data
  const { data: identitiesData, isLoading: identitiesLoading } = useQuery({
    queryKey: ['identities'],
    queryFn: async () => {
      const response = await axiosClient.get(CATALOG.IDENTITIES, {
        params: { limit: 1000 }
      })
      return response.data.items || []
    },
  })

  // Fetch families
  const { data: familiesData } = useQuery({
    queryKey: ['families'],
    queryFn: async () => {
      const response = await axiosClient.get(CATALOG.FAMILIES, {
        params: { limit: 1000 }
      })
      return response.data.items || []
    },
  })

  // Combine data
  const enhancedVariants: EnhancedVariant[] = useMemo(() => {
    if (!variantsData || !identitiesData || !familiesData) return []
    
    const identityMap = new Map<number, ProductIdentity & { family?: ProductFamily }>()
    const familyMap = new Map<number, ProductFamily>()
    
    familiesData.forEach((family: ProductFamily) => {
      familyMap.set(family.product_id, family)
    })
    
    identitiesData.forEach((identity: ProductIdentity) => {
      identityMap.set(identity.id, {
        ...identity,
        family: familyMap.get(identity.product_id),
      })
    })
    
    return variantsData.map((variant: Variant) => ({
      ...variant,
      identity: identityMap.get(variant.identity_id),
    }))
  }, [variantsData, identitiesData, familiesData])

  // Filter by search query
  const filteredVariants = useMemo(() => {
    if (!searchQuery.trim()) return enhancedVariants
    
    const query = searchQuery.toLowerCase()
    return enhancedVariants.filter((variant) => {
      const name = variant.identity?.family?.base_name?.toLowerCase() || ''
      const sku = variant.full_sku?.toLowerCase() || ''
      const upisH = variant.identity?.generated_upis_h?.toLowerCase() || ''
      const brand = variant.identity?.family?.brand?.name?.toLowerCase() || ''
      
      return name.includes(query) || 
             sku.includes(query) || 
             upisH.includes(query) ||
             brand.includes(query)
    })
  }, [enhancedVariants, searchQuery])

  // Group variants by Product Family
  const groupedData: GroupedItem[] = useMemo(() => {
    const groups = new Map<number, GroupedItem>()
    
    filteredVariants.forEach((variant) => {
      const productId = variant.identity?.family?.product_id ?? -1
      
      if (!groups.has(productId)) {
        groups.set(productId, {
          product_id: productId,
          name: variant.identity?.family?.base_name || 'Unknown',
          brand: variant.identity?.family?.brand?.name,
          variant_count: 0,
          variants: [],
        })
      }
      
      const group = groups.get(productId)!
      group.variants.push(variant)
      group.variant_count = group.variants.length
    })
    
    return Array.from(groups.values()).sort((a, b) =>
      a.name.localeCompare(b.name),
    )
  }, [filteredVariants])

  const handleToggleExpand = (productId: number) => {
    setExpandedRows((prev) => {
      const next = new Set(prev)
      if (next.has(productId)) {
        next.delete(productId)
      } else {
        next.add(productId)
      }
      return next
    })
  }

  const handleChangePage = (_: unknown, newPage: number) => {
    setPage(newPage)
  }

  const handleChangeRowsPerPage = (event: React.ChangeEvent<HTMLInputElement>) => {
    setRowsPerPage(parseInt(event.target.value, 10))
    setPage(0)
  }

  const isLoading = variantsLoading || identitiesLoading

  // Paginated data
  const paginatedListData = filteredVariants.slice(
    page * rowsPerPage,
    page * rowsPerPage + rowsPerPage
  )
  const paginatedGroupedData = groupedData.slice(
    page * rowsPerPage,
    page * rowsPerPage + rowsPerPage
  )

  return (
    <Box>
      {/* Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h4">Inventory Management</Typography>
        {hasRole(['ADMIN']) && (
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Button
              variant="outlined"
              onClick={() => zohoReadinessMutation.mutate()}
              disabled={
                zohoReadinessMutation.isPending ||
                zohoBulkSyncMutation.isPending ||
                zohoStopSyncMutation.isPending ||
                isZohoSyncRunning
              }
            >
              {zohoReadinessMutation.isPending
                ? 'Checking Readiness...'
                : zohoBulkSyncMutation.isPending
                  ? 'Starting Zoho Sync...'
                  : isZohoSyncRunning
                    ? 'Zoho Sync Running...'
                  : 'Sync All to Zoho'}
            </Button>
            {isZohoSyncRunning && (
              <Button
                variant="outlined"
                color="error"
                onClick={() => zohoStopSyncMutation.mutate()}
                disabled={zohoStopSyncMutation.isPending}
              >
                {zohoStopSyncMutation.isPending ? 'Stopping...' : 'Stop Zoho Sync'}
              </Button>
            )}
            <Button
              variant="outlined"
              onClick={() => backfillThumbnailsMutation.mutate()}
              disabled={backfillThumbnailsMutation.isPending}
            >
              {backfillThumbnailsMutation.isPending ? 'Backfilling...' : 'Backfill Thumbnails'}
            </Button>
            <Button
              variant="contained"
              startIcon={<Add />}
              onClick={() => setCreateDialogOpen(true)}
            >
              Add New Item
            </Button>
          </Box>
        )}
      </Box>

      {/* Search and View Toggle */}
      {zohoSyncProgress && (
        <Paper sx={{ p: 2, mb: 2 }}>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
              <Typography variant="subtitle2">
                Zoho Sync Job {zohoSyncProgress.job_id.slice(0, 8)} — {zohoSyncProgress.status.toUpperCase()}
              </Typography>
              <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                <Chip size="small" label={`Processed ${zohoSyncProgress.total_processed}/${zohoSyncProgress.total_target}`} />
                <Chip size="small" color="success" label={`Success ${zohoSyncProgress.total_success}`} />
                <Chip size="small" color="error" label={`Failed ${zohoSyncProgress.total_failed}`} />
              </Box>
            </Box>
            <LinearProgress variant={zohoSyncProgress.total_target > 0 ? 'determinate' : 'indeterminate'} value={zohoProgressPct} />
            {zohoSyncProgress.current_sku && (
              <Typography variant="body2" color="text.secondary">
                Current SKU: {zohoSyncProgress.current_sku}
              </Typography>
            )}
            {zohoSyncProgress.last_error && (
              <Alert severity="error" variant="outlined">
                Last error: {zohoSyncProgress.last_error}
              </Alert>
            )}
          </Box>
        </Paper>
      )}

      <Paper sx={{ p: 2, mb: 3 }}>
        <Box sx={{ display: 'flex', gap: 2, alignItems: 'center', flexWrap: 'wrap' }}>
          <TextField
            placeholder="Search by name, SKU, or brand..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            size="small"
            sx={{ flexGrow: 1, minWidth: 300 }}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <Search />
                </InputAdornment>
              ),
            }}
          />
          <ToggleButtonGroup
            value={viewMode}
            exclusive
            onChange={(_, value) => value && setViewMode(value)}
            size="small"
          >
            <ToggleButton value="list">
              <Tooltip title="List View">
                <ViewList />
              </Tooltip>
            </ToggleButton>
            <ToggleButton value="grouped">
              <Tooltip title="Group by Product Family">
                <ViewModule />
              </Tooltip>
            </ToggleButton>
          </ToggleButtonGroup>
        </Box>
      </Paper>

      {/* Data Table */}
      <Paper>
        <TableContainer>
          {viewMode === 'list' ? (
            // List View - Shows all variants
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell width={60}>Image</TableCell>
                  <TableCell>Full SKU</TableCell>
                  <TableCell>Name</TableCell>
                  <TableCell>Type</TableCell>
                  <TableCell>Parent UPIS-H</TableCell>
                  <TableCell>Color</TableCell>
                  <TableCell>Condition</TableCell>
                  <TableCell>Zoho Status</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {isLoading ? (
                  <TableRow>
                    <TableCell colSpan={8} align="center">
                      Loading...
                    </TableCell>
                  </TableRow>
                ) : paginatedListData.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={8} align="center">
                      No items found
                    </TableCell>
                  </TableRow>
                ) : (
                  paginatedListData.map((variant) => (
                    <TableRow key={variant.id} hover>
                      <TableCell>
                        <ProductThumbnail
                          sku={variant.full_sku}
                          thumbnailUrl={variant.thumbnail_url}
                          size={40}
                          onClick={() => setGallerySku(variant.full_sku)}
                        />
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2" fontFamily="monospace">
                          {variant.full_sku}
                        </Typography>
                      </TableCell>
                      <TableCell>{variant.identity?.family?.base_name || '-'}</TableCell>
                      <TableCell>
                        <Chip
                          size="small"
                          label={getTypeLabel(variant.identity?.type || 'Product')}
                          color={getTypeColor(variant.identity?.type || 'Product')}
                        />
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2" fontFamily="monospace">
                          {variant.identity?.generated_upis_h || '-'}
                        </Typography>
                      </TableCell>
                      <TableCell>{variant.color_code || '-'}</TableCell>
                      <TableCell>{variant.condition_code || 'U'}</TableCell>
                      <TableCell>{getSyncStatusChip(variant.zoho_sync_status)}</TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          ) : (
            // Grouped View - Shows grouped by Product Family
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell width={50} />
                  <TableCell>Product Family</TableCell>
                  <TableCell>Brand</TableCell>
                  <TableCell>Variants</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {isLoading ? (
                  <TableRow>
                    <TableCell colSpan={4} align="center">
                      Loading...
                    </TableCell>
                  </TableRow>
                ) : paginatedGroupedData.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={4} align="center">
                      No items found
                    </TableCell>
                  </TableRow>
                ) : (
                  paginatedGroupedData.map((group) => (
                    <>
                      <TableRow
                        key={group.product_id}
                        hover
                        sx={{ cursor: 'pointer' }}
                        onClick={() => handleToggleExpand(group.product_id)}
                      >
                        <TableCell>
                          <IconButton size="small">
                            {expandedRows.has(group.product_id) ? (
                              <ExpandLess />
                            ) : (
                              <ExpandMore />
                            )}
                          </IconButton>
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2" fontWeight={500}>
                            {group.name}
                          </Typography>
                        </TableCell>
                        <TableCell>{group.brand || '-'}</TableCell>
                        <TableCell>
                          <Chip size="small" label={`${group.variant_count} variant(s)`} />
                        </TableCell>
                      </TableRow>
                      {expandedRows.has(group.product_id) && (
                        <ExpandedRow
                          familyName={group.name}
                          variants={group.variants}
                        />
                      )}
                    </>
                  ))
                )}
              </TableBody>
            </Table>
          )}
        </TableContainer>
        <TablePagination
          rowsPerPageOptions={[10, 25, 50, 100]}
          component="div"
          count={viewMode === 'list' ? filteredVariants.length : groupedData.length}
          rowsPerPage={rowsPerPage}
          page={page}
          onPageChange={handleChangePage}
          onRowsPerPageChange={handleChangeRowsPerPage}
        />
      </Paper>

      {/* Create Product Dialog */}
      <CreateProductDialog
        open={createDialogOpen}
        onClose={() => setCreateDialogOpen(false)}
      />

      {/* Image Gallery Modal */}
      {gallerySku && (
        <ImageGalleryModal
          open={!!gallerySku}
          onClose={() => setGallerySku(null)}
          sku={gallerySku}
        />
      )}

      <Snackbar
        open={snackbarOpen}
        autoHideDuration={5000}
        onClose={() => setSnackbarOpen(false)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert
          onClose={() => setSnackbarOpen(false)}
          severity={snackbarSeverity}
          variant="filled"
          sx={{ width: '100%' }}
        >
          {snackbarMessage}
        </Alert>
      </Snackbar>

      <Dialog
        open={readinessDialogOpen}
        onClose={() => setReadinessDialogOpen(false)}
        fullWidth
        maxWidth="md"
      >
        <DialogTitle>Zoho Sync Readiness</DialogTitle>
        <DialogContent>
          {zohoReadinessMutation.isPending ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
              <CircularProgress size={28} />
            </Box>
          ) : readinessData ? (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                <Chip label={`Checked: ${readinessData.total_checked}`} size="small" />
                <Chip label={`Ready: ${readinessData.ready_count}`} size="small" color="success" />
                <Chip label={`Blocked: ${readinessData.blocked_count}`} size="small" color="error" />
                <Chip
                  label={`Warnings: ${readinessData.warning_only_count}`}
                  size="small"
                  color="warning"
                />
              </Box>

              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>SKU</TableCell>
                    <TableCell>Type</TableCell>
                    <TableCell>Status</TableCell>
                    <TableCell>Missing Fields</TableCell>
                    <TableCell>Warnings</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {readinessData.items.slice(0, 25).map((item: ZohoReadinessItem) => (
                    <TableRow key={item.variant_id}>
                      <TableCell>
                        <Typography variant="body2" fontFamily="monospace">
                          {item.sku}
                        </Typography>
                      </TableCell>
                      <TableCell>{item.identity_type}</TableCell>
                      <TableCell>
                        <Chip
                          size="small"
                          label={item.severity.toUpperCase()}
                          color={item.severity === 'error' ? 'error' : item.severity === 'warning' ? 'warning' : 'success'}
                        />
                      </TableCell>
                      <TableCell>{item.missing_fields.join(', ') || '-'}</TableCell>
                      <TableCell>{item.warnings.join(', ') || '-'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Box>
          ) : null}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setReadinessDialogOpen(false)}>Close</Button>
          <Button
            variant="contained"
            disabled={zohoBulkSyncMutation.isPending || isZohoSyncRunning}
            onClick={() => {
              setReadinessDialogOpen(false)
              void handleStartZohoSync()
            }}
          >
            {zohoBulkSyncMutation.isPending ? 'Starting...' : 'Sync Anyway'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}

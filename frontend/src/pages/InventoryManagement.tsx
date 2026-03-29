import { Fragment, useState, useMemo } from 'react'
import {
  Box,
  Typography,
  Button,
  Alert,
  Snackbar,
  Paper,
  TextField,
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
  FormControlLabel,
  Switch,
  Grid,
  FormControl,
  InputLabel,
  Select,
  Menu,
  MenuItem,
} from '@mui/material'
import {
  Add,
  ArrowDropDown,
  ViewList,
  ViewModule,
  ExpandMore,
  ExpandLess,
  PhotoLibrary,
} from '@mui/icons-material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AxiosError } from 'axios'
import axiosClient from '../api/axiosClient'
import { CATALOG, ZOHO } from '../api/endpoints'
import { Variant, ProductIdentity, ProductFamily, ProductType } from '../types/inventory'
import { useAuth } from '../hooks/useAuth'
import CreateProductDialog from '../components/inventory/CreateProductDialog'
import CreateCatalogItemDialog from '../components/inventory/CreateCatalogItemDialog'
import ProductThumbnail from '../components/inventory/ProductThumbnail'
import ImageGalleryModal from '../components/inventory/ImageGalleryModal'
import VariantImageDialog from '../components/inventory/VariantImageDialog'
import SearchField from '../components/common/SearchField'
import HoldActionPromptDialog from '../components/common/HoldActionPromptDialog'
import LongPressTableRow from '../components/common/LongPressTableRow'
import { useDebouncedValue } from '../hooks/useDebouncedValue'
import { compileSearchMatcher } from '../utils/search'

type ViewMode = 'list' | 'grouped'
type ListSortBy = 'name' | 'sku' | 'brand' | 'upis' | 'type' | 'color' | 'condition' | 'zoho'
type GroupSortBy = 'name' | 'brand' | 'variant_count'
type SortDirection = 'asc' | 'desc'

const PAGE_SIZE = 1000
const MAX_PAGE_ITERATIONS = 200

interface ExpandedRowProps {
  group: GroupedItem
  onSyncVariant: (variant: EnhancedVariant) => void
  syncingVariantId: number | null
  syncDisabled: boolean
  onManageImages: (sku: string) => void
  canAdmin: boolean
  onOpenHoldPrompt: (variant: EnhancedVariant) => void
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

interface ZohoBulkSyncItemResult {
  variant_id: number
  success: boolean
  zoho_sync_status?: string | null
  zoho_item_id?: string | null
}

interface ZohoBulkSyncResponse {
  total_processed: number
  total_success: number
  total_failed: number
  items: ZohoBulkSyncItemResult[]
}

interface ZohoRelinkBySkuResponse {
  total_processed: number
  total_matched: number
  total_updated: number
  total_unchanged: number
  total_not_found: number
  total_skipped: number
  dry_run: boolean
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

function ExpandedRow({
  group,
  onSyncVariant,
  syncingVariantId,
  syncDisabled,
  onManageImages,
  canAdmin,
  onOpenHoldPrompt,
}: ExpandedRowProps) {
  const [gallerySku, setGallerySku] = useState<string | null>(null)
  const typeCounts = useMemo(() => {
    return group.variants.reduce<Record<string, number>>((acc, variant) => {
      const key = variant.identity?.type || 'Product'
      acc[key] = (acc[key] || 0) + 1
      return acc
    }, {})
  }, [group.variants])

  const activeCount = useMemo(
    () => group.variants.filter((variant) => variant.is_active).length,
    [group.variants],
  )

  return (
    <TableRow>
      <TableCell colSpan={8} sx={{ py: 0, bgcolor: 'grey.50' }}>
        <Box sx={{ py: 2, px: 4 }}>
          <Box sx={{ mb: 2 }}>
            <Typography variant="h6" sx={{ mb: 0.5 }}>
              {group.name}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
              Product ID: {group.product_id} {group.brand ? `| Brand: ${group.brand}` : ''}
            </Typography>
            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
              <Chip size="small" label={`Variants: ${group.variant_count}`} />
              <Chip size="small" color="success" label={`Active: ${activeCount}`} />
              <Chip
                size="small"
                color={activeCount === group.variant_count ? 'default' : 'warning'}
                label={`Inactive: ${group.variant_count - activeCount}`}
              />
              {Object.entries(typeCounts).map(([type, count]) => (
                <Chip
                  key={type}
                  size="small"
                  color={getTypeColor(type as ProductType)}
                  label={`${getTypeLabel(type as ProductType)}: ${count}`}
                />
              ))}
            </Box>
          </Box>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell width={60}>Image</TableCell>
                <TableCell>Full SKU</TableCell>
                <TableCell>Variant Name</TableCell>
                <TableCell>Type</TableCell>
                <TableCell>UPIS-H</TableCell>
                <TableCell>Color</TableCell>
                <TableCell>Condition</TableCell>
                <TableCell>Zoho Status</TableCell>
                <TableCell align="right">Actions</TableCell>
                <TableCell>Active</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {group.variants.map((variant) => (
                <LongPressTableRow
                  key={variant.id}
                  hover
                  payload={variant}
                  onLongPress={onOpenHoldPrompt}
                  enableLongPress={canAdmin}
                  rowSx={canAdmin ? { cursor: 'pointer' } : undefined}
                >
                  <TableCell>
                    <ProductThumbnail
                      sku={variant.full_sku}
                      thumbnailUrl={variant.thumbnail_url}
                      size={36}
                      onClick={() => setGallerySku(variant.full_sku)}
                    />
                  </TableCell>
                  <TableCell>{variant.full_sku}</TableCell>
                  <TableCell>{variant.variant_name || variant.identity?.family?.base_name || '-'}</TableCell>
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
                  <TableCell align="right">
                    <Box sx={{ display: 'flex', gap: 0.5, justifyContent: 'flex-end' }}>
                      <Button
                        size="small"
                        variant="outlined"
                        startIcon={<PhotoLibrary fontSize="small" />}
                        onClick={() => onManageImages(variant.full_sku)}
                      >
                        Manage Images
                      </Button>
                      <Button
                        size="small"
                        variant="outlined"
                        onClick={() => onSyncVariant(variant)}
                        disabled={syncDisabled || syncingVariantId === variant.id}
                      >
                        {syncingVariantId === variant.id ? 'Syncing...' : 'Sync to Zoho'}
                      </Button>
                    </Box>
                  </TableCell>
                  <TableCell>
                    <Chip
                      size="small"
                      label={variant.is_active ? 'Active' : 'Inactive'}
                      color={variant.is_active ? 'success' : 'default'}
                    />
                  </TableCell>
                </LongPressTableRow>
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
  const [searchInput, setSearchInput] = useState('')
  const debouncedSearch = useDebouncedValue(searchInput, 200)
  const [createDialogOpen, setCreateDialogOpen] = useState(false)
  const [createCatalogDialogOpen, setCreateCatalogDialogOpen] = useState(false)
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set())
  const [page, setPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(25)
  const [listSortBy, setListSortBy] = useState<ListSortBy>('name')
  const [groupSortBy, setGroupSortBy] = useState<GroupSortBy>('name')
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc')
  const [typeFilter, setTypeFilter] = useState<ProductType | ''>('')
  const [conditionFilter, setConditionFilter] = useState<'N' | 'R' | 'U' | ''>('')
  const [syncFilter, setSyncFilter] = useState<'SYNCED' | 'PENDING' | 'DIRTY' | 'ERROR' | ''>('')
  const [activeFilter, setActiveFilter] = useState<'active' | 'inactive' | ''>('')
  const [brandFilter, setBrandFilter] = useState('')
  const [gallerySku, setGallerySku] = useState<string | null>(null)
  const [manageImagesSku, setManageImagesSku] = useState<string | null>(null)
  const [snackbarOpen, setSnackbarOpen] = useState(false)
  const [snackbarMessage, setSnackbarMessage] = useState('')
  const [snackbarSeverity, setSnackbarSeverity] = useState<'success' | 'error'>('success')
  const [exportingZohoCsv, setExportingZohoCsv] = useState(false)
  const [relinkingZohoItemIds, setRelinkingZohoItemIds] = useState(false)
  const [zohoActionsAnchorEl, setZohoActionsAnchorEl] = useState<null | HTMLElement>(null)
  const [syncingVariantId, setSyncingVariantId] = useState<number | null>(null)
  const [holdPromptOpen, setHoldPromptOpen] = useState(false)
  const [selectedVariant, setSelectedVariant] = useState<EnhancedVariant | null>(null)
  const [editBaseName, setEditBaseName] = useState('')
  const [editIdentityName, setEditIdentityName] = useState('')
  const [editDimensionLength, setEditDimensionLength] = useState('')
  const [editDimensionWidth, setEditDimensionWidth] = useState('')
  const [editDimensionHeight, setEditDimensionHeight] = useState('')
  const [editWeight, setEditWeight] = useState('')
  const [editVariantName, setEditVariantName] = useState('')
  const [editColorCode, setEditColorCode] = useState('')
  const [editConditionCode, setEditConditionCode] = useState('')
  const [editIsActive, setEditIsActive] = useState(true)
  const { hasRole } = useAuth()
  const queryClient = useQueryClient()

  const canAdmin = hasRole(['ADMIN'])

  const openHoldPrompt = (variant: EnhancedVariant) => {
    if (!canAdmin) {
      return
    }

    setSelectedVariant(variant)
    setEditBaseName(variant.identity?.family?.base_name || '')
    setEditIdentityName(variant.identity?.identity_name || '')
    setEditDimensionLength(variant.identity?.dimension_length?.toString() || '')
    setEditDimensionWidth(variant.identity?.dimension_width?.toString() || '')
    setEditDimensionHeight(variant.identity?.dimension_height?.toString() || '')
    setEditWeight(variant.identity?.weight?.toString() || '')
    setEditVariantName(variant.variant_name || '')
    setEditColorCode(variant.color_code || '')
    setEditConditionCode(variant.condition_code || '')
    setEditIsActive(variant.is_active)
    setHoldPromptOpen(true)
  }

  const closeHoldPrompt = () => {
    setHoldPromptOpen(false)
    setSelectedVariant(null)
  }

  const updateVariantMutation = useMutation({
    mutationFn: async () => {
      if (!selectedVariant) throw new Error('No variant selected')

      const parseNumberOrNull = (raw: string): number | null => {
        const trimmed = raw.trim()
        if (!trimmed) return null
        const value = Number(trimmed)
        if (!Number.isFinite(value) || value < 0) {
          throw new Error('Length, width, height, and weight must be non-negative numbers.')
        }
        return value
      }

      const family = selectedVariant.identity?.family
      if (family && editBaseName.trim() && editBaseName.trim() !== family.base_name) {
        await axiosClient.patch(CATALOG.FAMILY(family.product_id), {
          base_name: editBaseName.trim(),
        })
      }

      const identity = selectedVariant.identity
      if (identity) {
        const identityPayload = {
          identity_name: editIdentityName.trim() || null,
          dimension_length: parseNumberOrNull(editDimensionLength),
          dimension_width: parseNumberOrNull(editDimensionWidth),
          dimension_height: parseNumberOrNull(editDimensionHeight),
          weight: parseNumberOrNull(editWeight),
        }

        const hasIdentityChanges =
          (identityPayload.identity_name || '') !== (identity.identity_name || '') ||
          (identityPayload.dimension_length ?? null) !== (identity.dimension_length ?? null) ||
          (identityPayload.dimension_width ?? null) !== (identity.dimension_width ?? null) ||
          (identityPayload.dimension_height ?? null) !== (identity.dimension_height ?? null) ||
          (identityPayload.weight ?? null) !== (identity.weight ?? null)

        if (hasIdentityChanges) {
          await axiosClient.patch(CATALOG.IDENTITY(identity.id), identityPayload)
        }
      }

      const response = await axiosClient.patch(CATALOG.VARIANT(selectedVariant.id), {
        variant_name: editVariantName.trim() || null,
        color_code: editColorCode.trim().toUpperCase() || null,
        condition_code: editConditionCode.trim().toUpperCase() || null,
        is_active: editIsActive,
      })
      return response.data
    },
    onSuccess: async () => {
      setSnackbarSeverity('success')
      setSnackbarMessage('Variant updated successfully.')
      setSnackbarOpen(true)
      closeHoldPrompt()
      await queryClient.invalidateQueries({ queryKey: ['variants'] })
      await queryClient.invalidateQueries({ queryKey: ['identities'] })
      await queryClient.invalidateQueries({ queryKey: ['families'] })
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      const detail = error.response?.data?.detail || 'Failed to update variant.'
      setSnackbarSeverity('error')
      setSnackbarMessage(detail)
      setSnackbarOpen(true)
    },
  })

  const deleteVariantMutation = useMutation({
    mutationFn: async () => {
      if (!selectedVariant) throw new Error('No variant selected')
      await axiosClient.delete(CATALOG.VARIANT(selectedVariant.id))
    },
    onSuccess: async () => {
      setSnackbarSeverity('success')
      setSnackbarMessage('Variant deleted successfully.')
      setSnackbarOpen(true)
      closeHoldPrompt()
      await queryClient.invalidateQueries({ queryKey: ['variants'] })
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      const detail = error.response?.data?.detail || 'Failed to delete variant.'
      setSnackbarSeverity('error')
      setSnackbarMessage(detail)
      setSnackbarOpen(true)
    },
  })

  const zohoBulkSyncMutation = useMutation({
    mutationFn: async ({ includeImages, limit, bundleOnly = false }: { includeImages: boolean; limit: number; bundleOnly?: boolean }) => {
      const response = await axiosClient.post<ZohoBulkSyncResponse>(ZOHO.SYNC_ITEMS, {
        include_images: includeImages,
        include_composites: true,
        force_resync: true,
        limit,
        bundle_only: bundleOnly,
      })
      return response.data
    },
    onSuccess: async (data: ZohoBulkSyncResponse) => {
      const statusByVariant = new Map(
        data.items.map((item) => [item.variant_id, item.zoho_sync_status || (item.success ? 'SYNCED' : 'ERROR')])
      )
      queryClient.setQueryData(['variants'], (current: Variant[] | undefined) => {
        if (!current) return current
        return current.map((variant) => {
          const status = statusByVariant.get(variant.id)
          if (!status) return variant
          const item = data.items.find((result) => result.variant_id === variant.id)
          return {
            ...variant,
            zoho_sync_status: status as Variant['zoho_sync_status'],
            zoho_item_id: item?.zoho_item_id || variant.zoho_item_id,
          }
        })
      })

      setSnackbarSeverity('success')
      setSnackbarMessage(
        `Zoho sync completed: ${data.total_success}/${data.total_processed} succeeded, ${data.total_failed} failed.`
      )
      setSnackbarOpen(true)
      await queryClient.invalidateQueries({ queryKey: ['variants'] })
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      const detail = error.response?.data?.detail || 'Zoho sync failed.'
      setSnackbarSeverity('error')
      setSnackbarMessage(detail)
      setSnackbarOpen(true)
    },
  })

  const zohoSingleSyncMutation = useMutation({
    mutationFn: async (variant: EnhancedVariant) => {
      const response = await axiosClient.post(ZOHO.SYNC_SINGLE_ITEM(variant.id), {
        include_images: true,
        include_composites: true,
        force_resync: true,
      })
      return { result: response.data, variant }
    },
    onSuccess: async ({ variant }) => {
      setSnackbarSeverity('success')
      setSnackbarMessage(`Zoho sync completed for ${variant.full_sku}.`)
      setSnackbarOpen(true)
      setSyncingVariantId(null)
      await queryClient.invalidateQueries({ queryKey: ['variants'] })
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      const detail = error.response?.data?.detail || 'Single-item Zoho sync failed.'
      setSnackbarSeverity('error')
      setSnackbarMessage(detail)
      setSnackbarOpen(true)
      setSyncingVariantId(null)
    },
  })

  const handleStartZohoSync = async () => {
    await zohoBulkSyncMutation.mutateAsync({ includeImages: true, limit: 5000 })
  }

  const handleStartZohoSyncNoImages = async () => {
    await zohoBulkSyncMutation.mutateAsync({ includeImages: false, limit: 5000 })
  }

  const handleStartZohoBundleSync = async () => {
    await zohoBulkSyncMutation.mutateAsync({ includeImages: true, limit: 5000, bundleOnly: true })
  }

  const handleSyncSingleVariant = async (variant: EnhancedVariant) => {
    setSyncingVariantId(variant.id)
    await zohoSingleSyncMutation.mutateAsync(variant)
  }

  const isZohoSyncRunning = zohoBulkSyncMutation.isPending

  const handleExportZohoImportCsv = async () => {
    try {
      setExportingZohoCsv(true)
      const response = await axiosClient.get(CATALOG.EXPORT_ZOHO_ITEMS_CSV, {
        responseType: 'blob',
      })

      const contentDisposition = response.headers['content-disposition'] || ''
      const filenameMatch = contentDisposition.match(/filename="?([^";]+)"?/i)
      const filename = filenameMatch?.[1] || 'zoho_items_import.csv'

      const blobUrl = window.URL.createObjectURL(new Blob([response.data], { type: 'text/csv;charset=utf-8;' }))
      const link = document.createElement('a')
      link.href = blobUrl
      link.setAttribute('download', filename)
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      window.URL.revokeObjectURL(blobUrl)

      setSnackbarSeverity('success')
      setSnackbarMessage('Exported Zoho import CSV successfully.')
      setSnackbarOpen(true)
    } catch (error) {
      const detail = (error as AxiosError<{ detail?: string }>)?.response?.data?.detail || 'Failed to export CSV.'
      setSnackbarSeverity('error')
      setSnackbarMessage(detail)
      setSnackbarOpen(true)
    } finally {
      setExportingZohoCsv(false)
    }
  }

  const handleRelinkZohoItemIdsBySku = async () => {
    try {
      setRelinkingZohoItemIds(true)
      const response = await axiosClient.post<ZohoRelinkBySkuResponse>(ZOHO.RELINK_ITEM_IDS_BY_SKU, {
        include_inactive: false,
        overwrite_existing: true,
        dry_run: false,
        limit: 5000,
      })

      const data = response.data
      setSnackbarSeverity('success')
      setSnackbarMessage(
        `Zoho ID relink by SKU completed: ${data.total_updated} updated, ${data.total_unchanged} unchanged, ${data.total_not_found} not found, ${data.total_skipped} skipped.`
      )
      setSnackbarOpen(true)
      await queryClient.invalidateQueries({ queryKey: ['variants'] })
    } catch (error) {
      const detail = (error as AxiosError<{ detail?: string }>)?.response?.data?.detail || 'Failed to relink Zoho IDs by SKU.'
      setSnackbarSeverity('error')
      setSnackbarMessage(detail)
      setSnackbarOpen(true)
    } finally {
      setRelinkingZohoItemIds(false)
    }
  }

  const isZohoActionsMenuOpen = Boolean(zohoActionsAnchorEl)

  const handleOpenZohoActionsMenu = (event: React.MouseEvent<HTMLElement>) => {
    setZohoActionsAnchorEl(event.currentTarget)
  }

  const handleCloseZohoActionsMenu = () => {
    setZohoActionsAnchorEl(null)
  }

  const fetchAllPages = async <T,>(
    endpoint: string,
    baseParams?: Record<string, string | number | boolean>
  ): Promise<T[]> => {
    const allItems: T[] = []

    for (let i = 0; i < MAX_PAGE_ITERATIONS; i += 1) {
      const skip = i * PAGE_SIZE
      const response = await axiosClient.get(endpoint, {
        params: {
          ...(baseParams || {}),
          skip,
          limit: PAGE_SIZE,
        },
      })

      const pageItems: T[] = response.data.items || []
      allItems.push(...pageItems)

      if (pageItems.length < PAGE_SIZE) {
        break
      }
    }

    return allItems
  }

  // Fetch variants with identity data
  const { data: variantsData, isLoading: variantsLoading } = useQuery({
    queryKey: ['variants'],
    queryFn: async () => fetchAllPages<Variant>(CATALOG.VARIANTS, { is_active: true }),
  })

  // Fetch identities with family data
  const { data: identitiesData, isLoading: identitiesLoading } = useQuery({
    queryKey: ['identities'],
    queryFn: async () => fetchAllPages<ProductIdentity>(CATALOG.IDENTITIES),
  })

  // Fetch families
  const { data: familiesData } = useQuery({
    queryKey: ['families'],
    queryFn: async () => fetchAllPages<ProductFamily>(CATALOG.FAMILIES),
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
    const matchesSearch = compileSearchMatcher(debouncedSearch)
    const normalizedBrandFilter = brandFilter.trim().toLowerCase()
    return enhancedVariants.filter((variant) => {
      const conditionCode = variant.condition_code || 'U'
      const brand = variant.identity?.family?.brand?.name || ''
      const passesType = !typeFilter || (variant.identity?.type || 'Product') === typeFilter
      const passesCondition = !conditionFilter || conditionCode === conditionFilter
      const passesSync = !syncFilter || variant.zoho_sync_status === syncFilter
      const passesActive = !activeFilter || (activeFilter === 'active' ? variant.is_active : !variant.is_active)
      const passesBrand = !normalizedBrandFilter || brand.toLowerCase().includes(normalizedBrandFilter)

      return (
        passesType &&
        passesCondition &&
        passesSync &&
        passesActive &&
        passesBrand &&
        matchesSearch([
        variant.identity?.family?.base_name,
        variant.variant_name,
        variant.full_sku,
        variant.identity?.generated_upis_h,
        variant.identity?.family?.brand?.name,
        ])
      )
    })
  }, [enhancedVariants, debouncedSearch, typeFilter, conditionFilter, syncFilter, activeFilter, brandFilter])

  const sortedVariants = useMemo(() => {
    const sorted = [...filteredVariants]
    const multiplier = sortDirection === 'asc' ? 1 : -1

    sorted.sort((a, b) => {
      const valueFor = (variant: EnhancedVariant): string => {
        switch (listSortBy) {
          case 'sku':
            return variant.full_sku || ''
          case 'brand':
            return variant.identity?.family?.brand?.name || ''
          case 'upis':
            return variant.identity?.generated_upis_h || ''
          case 'type':
            return variant.identity?.type || 'Product'
          case 'color':
            return variant.color_code || ''
          case 'condition':
            return variant.condition_code || 'U'
          case 'zoho':
            return variant.zoho_sync_status || ''
          case 'name':
          default:
            return variant.variant_name || variant.identity?.family?.base_name || ''
        }
      }

      return valueFor(a).localeCompare(valueFor(b)) * multiplier
    })

    return sorted
  }, [filteredVariants, listSortBy, sortDirection])

  // Group variants by Product Family
  const groupedData: GroupedItem[] = useMemo(() => {
    const groups = new Map<number, GroupedItem>()
    
    sortedVariants.forEach((variant) => {
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
    
    const multiplier = sortDirection === 'asc' ? 1 : -1
    return Array.from(groups.values()).sort((a, b) => {
      if (groupSortBy === 'variant_count') {
        return (a.variant_count - b.variant_count) * multiplier
      }

      if (groupSortBy === 'brand') {
        return (a.brand || '').localeCompare(b.brand || '') * multiplier
      }

      return a.name.localeCompare(b.name) * multiplier
    })
  }, [sortedVariants, groupSortBy, sortDirection])

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
  const paginatedListData = sortedVariants.slice(
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
              onClick={handleOpenZohoActionsMenu}
              endIcon={<ArrowDropDown />}
              disabled={zohoBulkSyncMutation.isPending || isZohoSyncRunning || relinkingZohoItemIds || exportingZohoCsv}
            >
              {zohoBulkSyncMutation.isPending ? 'Syncing...' : 'Zoho Actions'}
            </Button>
            <Menu
              anchorEl={zohoActionsAnchorEl}
              open={isZohoActionsMenuOpen}
              onClose={handleCloseZohoActionsMenu}
            >
              <MenuItem
                onClick={() => {
                  handleCloseZohoActionsMenu()
                  void handleExportZohoImportCsv()
                }}
                disabled={exportingZohoCsv || relinkingZohoItemIds || zohoBulkSyncMutation.isPending || syncingVariantId !== null}
              >
                {exportingZohoCsv ? 'Exporting CSV...' : 'Export Zoho CSV'}
              </MenuItem>
              <MenuItem
                onClick={() => {
                  handleCloseZohoActionsMenu()
                  void handleStartZohoSync()
                }}
                disabled={zohoBulkSyncMutation.isPending || isZohoSyncRunning}
              >
                Sync All to Zoho
              </MenuItem>
              <MenuItem
                onClick={() => {
                  handleCloseZohoActionsMenu()
                  void handleStartZohoSyncNoImages()
                }}
                disabled={zohoBulkSyncMutation.isPending || isZohoSyncRunning}
              >
                Sync All to Zoho (No Images)
              </MenuItem>
              <MenuItem
                onClick={() => {
                  handleCloseZohoActionsMenu()
                  void handleRelinkZohoItemIdsBySku()
                }}
                disabled={relinkingZohoItemIds || exportingZohoCsv || zohoBulkSyncMutation.isPending || syncingVariantId !== null}
              >
                {relinkingZohoItemIds ? 'Relinking Zoho IDs...' : 'Relink Zoho IDs by SKU'}
              </MenuItem>
              <MenuItem
                onClick={() => {
                  handleCloseZohoActionsMenu()
                  void handleStartZohoBundleSync()
                }}
                disabled={zohoBulkSyncMutation.isPending || isZohoSyncRunning}
              >
                Sync Bundle to Zoho
              </MenuItem>
            </Menu>
            <Button
              variant="outlined"
              startIcon={<Add />}
              onClick={() => setCreateCatalogDialogOpen(true)}
            >
              Add Product
            </Button>
            <Button
              variant="contained"
              startIcon={<Add />}
              onClick={() => setCreateDialogOpen(true)}
            >
              Add Variant
            </Button>
          </Box>
        )}
      </Box>

      {/* Search and View Toggle */}

      <Paper sx={{ p: 2, mb: 3 }}>
        <Grid container spacing={2} alignItems="center">
          <Grid item xs={12} md={6}>
          <SearchField
            placeholder="Search by name, SKU, or brand..."
            value={searchInput}
            onChange={setSearchInput}
            size="small"
              sx={{ width: '100%' }}
          />
          </Grid>
          <Grid item xs={12} md={6}>
            <Box sx={{ display: 'flex', justifyContent: { xs: 'flex-start', md: 'flex-end' } }}>
          <ToggleButtonGroup
            value={viewMode}
            exclusive
                onChange={(_, value) => {
                  if (!value) return
                  setViewMode(value)
                  setPage(0)
                }}
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
          </Grid>

          <Grid item xs={6} md={2}>
            <FormControl size="small" fullWidth>
              <InputLabel>Type</InputLabel>
              <Select
                value={typeFilter}
                label="Type"
                onChange={(e) => {
                  setTypeFilter(e.target.value as ProductType | '')
                  setPage(0)
                }}
              >
                <MenuItem value="">All</MenuItem>
                <MenuItem value="Product">Product</MenuItem>
                <MenuItem value="P">Part</MenuItem>
                <MenuItem value="B">Bundle</MenuItem>
                <MenuItem value="K">Kit</MenuItem>
              </Select>
            </FormControl>
          </Grid>

          <Grid item xs={6} md={2}>
            <FormControl size="small" fullWidth>
              <InputLabel>Condition</InputLabel>
              <Select
                value={conditionFilter}
                label="Condition"
                onChange={(e) => {
                  setConditionFilter(e.target.value as 'N' | 'R' | 'U' | '')
                  setPage(0)
                }}
              >
                <MenuItem value="">All</MenuItem>
                <MenuItem value="N">N</MenuItem>
                <MenuItem value="R">R</MenuItem>
                <MenuItem value="U">U</MenuItem>
              </Select>
            </FormControl>
          </Grid>

          <Grid item xs={6} md={2}>
            <FormControl size="small" fullWidth>
              <InputLabel>Sync</InputLabel>
              <Select
                value={syncFilter}
                label="Sync"
                onChange={(e) => {
                  setSyncFilter(e.target.value as 'SYNCED' | 'PENDING' | 'DIRTY' | 'ERROR' | '')
                  setPage(0)
                }}
              >
                <MenuItem value="">All</MenuItem>
                <MenuItem value="SYNCED">SYNCED</MenuItem>
                <MenuItem value="PENDING">PENDING</MenuItem>
                <MenuItem value="DIRTY">DIRTY</MenuItem>
                <MenuItem value="ERROR">ERROR</MenuItem>
              </Select>
            </FormControl>
          </Grid>

          <Grid item xs={6} md={2}>
            <FormControl size="small" fullWidth>
              <InputLabel>Active</InputLabel>
              <Select
                value={activeFilter}
                label="Active"
                onChange={(e) => {
                  setActiveFilter(e.target.value as 'active' | 'inactive' | '')
                  setPage(0)
                }}
              >
                <MenuItem value="">All</MenuItem>
                <MenuItem value="active">Active</MenuItem>
                <MenuItem value="inactive">Inactive</MenuItem>
              </Select>
            </FormControl>
          </Grid>

          <Grid item xs={12} md={2}>
            <TextField
              size="small"
              label="Brand filter"
              value={brandFilter}
              onChange={(e) => {
                setBrandFilter(e.target.value)
                setPage(0)
              }}
              fullWidth
            />
          </Grid>

          <Grid item xs={6} md={2}>
            <FormControl size="small" fullWidth>
              <InputLabel>Sort by</InputLabel>
              <Select
                value={viewMode === 'list' ? listSortBy : groupSortBy}
                label="Sort by"
                onChange={(e) => {
                  if (viewMode === 'list') {
                    setListSortBy(e.target.value as ListSortBy)
                  } else {
                    setGroupSortBy(e.target.value as GroupSortBy)
                  }
                  setPage(0)
                }}
              >
                {viewMode === 'list' ? (
                  [
                    ['name', 'Name'],
                    ['sku', 'SKU'],
                    ['brand', 'Brand'],
                    ['upis', 'UPIS-H'],
                    ['type', 'Type'],
                    ['color', 'Color'],
                    ['condition', 'Condition'],
                    ['zoho', 'Zoho Status'],
                  ].map(([value, label]) => (
                    <MenuItem key={value} value={value}>{label}</MenuItem>
                  ))
                ) : (
                  [
                    ['name', 'Family name'],
                    ['brand', 'Brand'],
                    ['variant_count', 'Variant count'],
                  ].map(([value, label]) => (
                    <MenuItem key={value} value={value}>{label}</MenuItem>
                  ))
                )}
              </Select>
            </FormControl>
          </Grid>

          <Grid item xs={6} md={2}>
            <FormControl size="small" fullWidth>
              <InputLabel>Direction</InputLabel>
              <Select
                value={sortDirection}
                label="Direction"
                onChange={(e) => {
                  setSortDirection(e.target.value as SortDirection)
                  setPage(0)
                }}
              >
                <MenuItem value="asc">Ascending</MenuItem>
                <MenuItem value="desc">Descending</MenuItem>
              </Select>
            </FormControl>
          </Grid>

          <Grid item xs={12} md={8}>
            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
              <Chip size="small" label={`Results: ${viewMode === 'list' ? sortedVariants.length : groupedData.length}`} />
              <Chip size="small" label={`View: ${viewMode === 'list' ? 'List' : 'Grouped'}`} variant="outlined" />
              <Button
                size="small"
                variant="text"
                onClick={() => {
                  setTypeFilter('')
                  setConditionFilter('')
                  setSyncFilter('')
                  setActiveFilter('')
                  setBrandFilter('')
                  setListSortBy('name')
                  setGroupSortBy('name')
                  setSortDirection('asc')
                  setPage(0)
                }}
              >
                Reset filters/sort
              </Button>
            </Box>
          </Grid>
        </Grid>
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
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {isLoading ? (
                  <TableRow>
                    <TableCell colSpan={9} align="center">
                      Loading...
                    </TableCell>
                  </TableRow>
                ) : paginatedListData.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={9} align="center">
                      No items found
                    </TableCell>
                  </TableRow>
                ) : (
                  paginatedListData.map((variant) => (
                    <LongPressTableRow
                      key={variant.id}
                      hover
                      payload={variant}
                      onLongPress={openHoldPrompt}
                      enableLongPress={canAdmin}
                      rowSx={canAdmin ? { cursor: 'pointer' } : undefined}
                    >
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
                      <TableCell>{variant.variant_name || variant.identity?.family?.base_name || '-'}</TableCell>
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
                      <TableCell align="right">
                        <Box sx={{ display: 'flex', gap: 0.5, justifyContent: 'flex-end' }}>
                          <Button
                            size="small"
                            variant="outlined"
                            startIcon={<PhotoLibrary fontSize="small" />}
                            onClick={() => setManageImagesSku(variant.full_sku)}
                          >
                            Manage Images
                          </Button>
                          <Button
                            size="small"
                            variant="outlined"
                            onClick={() => void handleSyncSingleVariant(variant)}
                            disabled={
                              isZohoSyncRunning ||
                              zohoSingleSyncMutation.isPending ||
                              syncingVariantId === variant.id
                            }
                          >
                            {syncingVariantId === variant.id ? 'Syncing...' : 'Sync to Zoho'}
                          </Button>
                        </Box>
                      </TableCell>
                    </LongPressTableRow>
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
                    <Fragment key={group.product_id}>
                      <TableRow
                        hover
                        sx={{ cursor: 'pointer', '& > *': { borderBottom: expandedRows.has(group.product_id) ? 'unset' : undefined } }}
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
                          group={group}
                          onSyncVariant={(variant) => void handleSyncSingleVariant(variant)}
                          syncingVariantId={syncingVariantId}
                          syncDisabled={isZohoSyncRunning || zohoSingleSyncMutation.isPending}
                          onManageImages={(sku) => setManageImagesSku(sku)}
                          canAdmin={canAdmin}
                          onOpenHoldPrompt={openHoldPrompt}
                        />
                      )}
                    </Fragment>
                  ))
                )}
              </TableBody>
            </Table>
          )}
        </TableContainer>
        <TablePagination
          rowsPerPageOptions={[10, 25, 50, 100]}
          component="div"
          count={viewMode === 'list' ? sortedVariants.length : groupedData.length}
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
        onCreated={(sku) => setManageImagesSku(sku)}
      />

      <CreateCatalogItemDialog
        open={createCatalogDialogOpen}
        onClose={() => setCreateCatalogDialogOpen(false)}
      />

      {/* Image Gallery Modal (read-only preview) */}
      {gallerySku && (
        <ImageGalleryModal
          open={!!gallerySku}
          onClose={() => setGallerySku(null)}
          sku={gallerySku}
        />
      )}

      {/* Image Management Dialog (upload / delete) */}
      {manageImagesSku && (
        <VariantImageDialog
          open={!!manageImagesSku}
          onClose={() => setManageImagesSku(null)}
          sku={manageImagesSku}
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

      <HoldActionPromptDialog
        open={holdPromptOpen}
        onClose={closeHoldPrompt}
        title="Edit Variant"
        onSave={() => updateVariantMutation.mutate()}
        onDelete={() => deleteVariantMutation.mutate()}
        saveDisabled={!selectedVariant}
        deleteDisabled={!selectedVariant}
        saveLoading={updateVariantMutation.isPending}
        deleteLoading={deleteVariantMutation.isPending}
        deleteConfirmTitle="Delete Variant"
        deleteConfirmMessage={
          <Typography>
            Delete variant <strong>{selectedVariant?.full_sku}</strong>? This action cannot be undone.
          </Typography>
        }
      >
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 1 }}>
          <TextField
            label="Full SKU"
            value={selectedVariant?.full_sku || ''}
            fullWidth
            disabled
          />
          <TextField
            label="UPIS-H"
            value={selectedVariant?.identity?.generated_upis_h || ''}
            fullWidth
            disabled
          />
          <TextField
            label="Type"
            value={getTypeLabel(selectedVariant?.identity?.type || 'Product')}
            fullWidth
            disabled
          />
          <TextField
            label="Product Name"
            value={editBaseName}
            onChange={(e) => setEditBaseName(e.target.value)}
            fullWidth
          />
          <TextField
            label="Identity Name"
            value={editIdentityName}
            onChange={(e) => setEditIdentityName(e.target.value)}
            fullWidth
          />
          <Grid container spacing={1.5}>
            <Grid item xs={12} md={6}>
              <TextField
                label="Length"
                value={editDimensionLength}
                onChange={(e) => setEditDimensionLength(e.target.value)}
                type="number"
                fullWidth
              />
            </Grid>
            <Grid item xs={12} md={6}>
              <TextField
                label="Width"
                value={editDimensionWidth}
                onChange={(e) => setEditDimensionWidth(e.target.value)}
                type="number"
                fullWidth
              />
            </Grid>
            <Grid item xs={12} md={6}>
              <TextField
                label="Height"
                value={editDimensionHeight}
                onChange={(e) => setEditDimensionHeight(e.target.value)}
                type="number"
                fullWidth
              />
            </Grid>
            <Grid item xs={12} md={6}>
              <TextField
                label="Weight"
                value={editWeight}
                onChange={(e) => setEditWeight(e.target.value)}
                type="number"
                fullWidth
              />
            </Grid>
          </Grid>
          <TextField
            label="Display Name"
            value={editVariantName}
            onChange={(e) => setEditVariantName(e.target.value)}
            placeholder="Leave empty to fallback to family name"
            fullWidth
          />
          <TextField
            label="Color Code"
            value={editColorCode}
            onChange={(e) => setEditColorCode(e.target.value.slice(0, 2).toUpperCase())}
            placeholder="e.g. BK"
            inputProps={{ maxLength: 2 }}
            fullWidth
          />
          <TextField
            label="Condition Code"
            value={editConditionCode}
            onChange={(e) => setEditConditionCode(e.target.value.slice(0, 1).toUpperCase())}
            placeholder="e.g. N"
            inputProps={{ maxLength: 1 }}
            fullWidth
          />
          <FormControlLabel
            control={
              <Switch
                checked={editIsActive}
                onChange={(e) => setEditIsActive(e.target.checked)}
              />
            }
            label={editIsActive ? 'Active' : 'Inactive'}
          />
        </Box>
      </HoldActionPromptDialog>
    </Box>
  )
}

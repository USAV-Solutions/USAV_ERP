import React, { useEffect, useState, useMemo, Fragment } from 'react'
import {
  Box,
  Typography,
  Button,
  Paper,
  TextField,
  InputAdornment,
  Chip,
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
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Autocomplete,
  IconButton,
  Tooltip,
  Alert,
  CircularProgress,
  SelectChangeEvent,
  AutocompleteRenderInputParams,
  Collapse,
} from '@mui/material'
import {
  Add,
  Refresh,
  Error as ErrorIcon,
  CheckCircle,
  Schedule,
  ExpandMore,
  ExpandLess,
  Visibility,
  Link as LinkIcon,
  LinkOff,
} from '@mui/icons-material'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axiosClient from '../api/axiosClient'
import { CATALOG, LISTINGS } from '../api/endpoints'
import {
  Variant,
  ProductIdentity,
  ProductFamily,
  Platform,
  PlatformListing,
  PlatformListingCreate,
  PlatformListingUpdate,
} from '../types/inventory'
import { useAuth } from '../hooks/useAuth'
import SearchField from '../components/common/SearchField'
import { useDebouncedValue } from '../hooks/useDebouncedValue'
import { compileSearchMatcher } from '../utils/search'

const PLATFORMS: { value: Platform; label: string }[] = [
  { value: 'AMAZON', label: 'Amazon' },
  { value: 'EBAY_MEKONG', label: 'eBay Mekong' },
  { value: 'EBAY_USAV', label: 'eBay USAV' },
  { value: 'EBAY_DRAGON', label: 'eBay Dragon' },
  { value: 'ECWID', label: 'ECWID' },
  { value: 'WALMART', label: 'Walmart' },
]

interface EnhancedListing extends PlatformListing {
  variant?: Variant & {
    identity?: ProductIdentity & { family?: ProductFamily }
  }
}

const getSyncStatusChip = (status: string, errorMessage?: string) => {
  const configs: Record<string, { icon: React.ReactNode; color: 'success' | 'warning' | 'error' | 'default'; label: string }> = {
    SYNCED: { icon: <CheckCircle fontSize="small" />, color: 'success', label: 'Synced' },
    PENDING: { icon: <Schedule fontSize="small" />, color: 'warning', label: 'Pending' },
    ERROR: { icon: <ErrorIcon fontSize="small" />, color: 'error', label: 'Error' },
  }
  const config = configs[status] || { icon: null, color: 'default' as const, label: status }
  return (
    <Tooltip title={errorMessage || ''}>
      <Chip
        size="small"
        icon={config.icon as React.ReactElement}
        color={config.color}
        label={config.label}
      />
    </Tooltip>
  )
}

interface CreateListingDialogProps {
  open: boolean
  onClose: () => void
  variants: (Variant & { identity?: ProductIdentity & { family?: ProductFamily } })[]
}

function CreateListingDialog({ open, onClose, variants }: CreateListingDialogProps) {
  const queryClient = useQueryClient()
  const [selectedVariant, setSelectedVariant] = useState<Variant | null>(null)
  const [selectedPlatform, setSelectedPlatform] = useState<Platform | ''>('')
  const [externalRefId, setExternalRefId] = useState('')
  const [listedName, setListedName] = useState('')
  const [listedDescription, setListedDescription] = useState('')
  const [listingPrice, setListingPrice] = useState('')
  const [listingQuantity, setListingQuantity] = useState('')
  const [listingType, setListingType] = useState('')
  const [listingCondition, setListingCondition] = useState('')
  const [upc, setUpc] = useState('')
  const [error, setError] = useState<string | null>(null)

  const createMutation = useMutation({
    mutationFn: async (data: PlatformListingCreate) => {
      const response = await axiosClient.post(LISTINGS.LIST, data)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['listings'] })
      handleClose()
    },
    onError: (err: any) => {
      setError(err.response?.data?.detail || 'Failed to create listing')
    },
  })

  const handleClose = () => {
    setSelectedVariant(null)
    setSelectedPlatform('')
    setExternalRefId('')
    setListedName('')
    setListedDescription('')
    setListingPrice('')
    setListingQuantity('')
    setListingType('')
    setListingCondition('')
    setUpc('')
    setError(null)
    onClose()
  }

  const handleSubmit = () => {
    if (!selectedVariant || !selectedPlatform) return
    
    setError(null)
    createMutation.mutate({
      variant_id: selectedVariant.id,
      platform: selectedPlatform,
      external_ref_id: externalRefId || undefined,
      listed_name: listedName || undefined,
      listed_description: listedDescription || undefined,
      listing_price: listingPrice ? parseFloat(listingPrice) : undefined,
      listing_quantity: listingQuantity ? parseInt(listingQuantity, 10) : undefined,
      listing_type: listingType || undefined,
      listing_condition: listingCondition || undefined,
      upc: upc || undefined,
    })
  }

  const isValid = selectedVariant && selectedPlatform

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>Add New Platform Listing</DialogTitle>
      <DialogContent>
        <Box sx={{ mt: 2 }}>
          {error && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}
          
          <Autocomplete
            options={variants}
            getOptionLabel={(option: Variant) =>
              `${option.full_sku} - ${(option as any).identity?.family?.base_name || 'Unknown'}`
            }
            value={selectedVariant}
            onChange={(_: React.SyntheticEvent, value: Variant | null) => setSelectedVariant(value)}
            renderInput={(params: AutocompleteRenderInputParams) => (
              <TextField
                {...params}
                label="Product Variant *"
                placeholder="Search by SKU or name..."
              />
            )}
            renderOption={(props: React.HTMLAttributes<HTMLLIElement>, option: Variant) => (
              <li {...props} key={option.id}>
                <Box>
                  <Typography variant="body2" fontFamily="monospace">
                    {option.full_sku}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {(option as any).identity?.family?.base_name || 'Unknown'}
                  </Typography>
                </Box>
              </li>
            )}
            sx={{ mb: 2 }}
          />

          <FormControl fullWidth sx={{ mb: 2 }}>
            <InputLabel>Platform *</InputLabel>
            <Select
              value={selectedPlatform}
              label="Platform *"
              onChange={(e: SelectChangeEvent<Platform | ''>) => setSelectedPlatform(e.target.value as Platform)}
            >
              {PLATFORMS.map((p) => (
                <MenuItem key={p.value} value={p.value}>
                  {p.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <TextField
            fullWidth
            label="External Reference ID"
            value={externalRefId}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setExternalRefId(e.target.value)}
            placeholder="e.g., ASIN, eBay Item ID"
            helperText="The ID from the external platform (optional)"
            sx={{ mb: 2 }}
          />

          <TextField
            fullWidth
            label="Listed Name"
            value={listedName}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setListedName(e.target.value)}
            placeholder="Product title as shown on the platform"
            helperText="The product name displayed on this platform (optional)"
            sx={{ mb: 2 }}
          />

          <TextField
            fullWidth
            label="Listed Description"
            value={listedDescription}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setListedDescription(e.target.value)}
            placeholder="Product description for this platform"
            helperText="The product description displayed on this platform (optional)"
            multiline
            rows={3}
            sx={{ mb: 2 }}
          />

          <TextField
            fullWidth
            label="Listing Price"
            type="number"
            value={listingPrice}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setListingPrice(e.target.value)}
            InputProps={{
              startAdornment: <InputAdornment position="start">$</InputAdornment>,
            }}
            helperText="Platform-specific price (optional)"
            sx={{ mb: 2 }}
          />

          <TextField
            fullWidth
            label="Listing Quantity"
            type="number"
            value={listingQuantity}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setListingQuantity(e.target.value)}
            helperText="Platform-specific quantity/stock (optional)"
            sx={{ mb: 2 }}
          />

          <TextField
            fullWidth
            label="Listing Type"
            value={listingType}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setListingType(e.target.value)}
            helperText="Platform-specific listing type/classification (optional)"
            sx={{ mb: 2 }}
          />

          <TextField
            fullWidth
            label="Listing Condition"
            value={listingCondition}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setListingCondition(e.target.value)}
            helperText="Condition string as shown on this platform (optional)"
            sx={{ mb: 2 }}
          />

          <TextField
            fullWidth
            label="UPC"
            value={upc}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setUpc(e.target.value)}
            helperText="UPC/GTIN for this platform listing (optional)"
          />
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>Cancel</Button>
        <Button
          variant="contained"
          onClick={handleSubmit}
          disabled={!isValid || createMutation.isPending}
        >
          {createMutation.isPending ? <CircularProgress size={24} /> : 'Create Listing'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

interface EditListingDialogProps {
  open: boolean
  onClose: () => void
  listing: EnhancedListing | null
}

function EditListingDialog({ open, onClose, listing }: EditListingDialogProps) {
  const queryClient = useQueryClient()
  const [externalRefId, setExternalRefId] = useState('')
  const [listedName, setListedName] = useState('')
  const [listedDescription, setListedDescription] = useState('')
  const [listingPrice, setListingPrice] = useState('')
  const [listingQuantity, setListingQuantity] = useState('')
  const [listingType, setListingType] = useState('')
  const [listingCondition, setListingCondition] = useState('')
  const [upc, setUpc] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!listing || !open) return
    setExternalRefId(listing.external_ref_id || '')
    setListedName(listing.listed_name || '')
    setListedDescription(listing.listed_description || '')
    setListingPrice(listing.listing_price != null ? String(listing.listing_price) : '')
    setListingQuantity(listing.listing_quantity != null ? String(listing.listing_quantity) : '')
    setListingType(listing.listing_type || '')
    setListingCondition(listing.listing_condition || '')
    setUpc(listing.upc || '')
    setError(null)
  }, [listing, open])

  const updateMutation = useMutation({
    mutationFn: async (payload: PlatformListingUpdate) => {
      if (!listing) throw new Error('Listing not found')
      const response = await axiosClient.patch(LISTINGS.LISTING(listing.id), payload)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['listings'] })
      onClose()
    },
    onError: (err: any) => {
      setError(err.response?.data?.detail || 'Failed to update listing')
    },
  })

  const handleSubmit = () => {
    setError(null)
    updateMutation.mutate({
      external_ref_id: externalRefId || undefined,
      listed_name: listedName || undefined,
      listed_description: listedDescription || undefined,
      listing_price: listingPrice ? parseFloat(listingPrice) : undefined,
      listing_quantity: listingQuantity ? parseInt(listingQuantity, 10) : undefined,
      listing_type: listingType || undefined,
      listing_condition: listingCondition || undefined,
      upc: upc || undefined,
    })
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Edit Platform Listing</DialogTitle>
      <DialogContent>
        <Box sx={{ mt: 2 }}>
          {error && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}
          <TextField fullWidth label="External Reference ID" value={externalRefId} onChange={(e) => setExternalRefId(e.target.value)} sx={{ mb: 2 }} />
          <TextField fullWidth label="Listed Name" value={listedName} onChange={(e) => setListedName(e.target.value)} sx={{ mb: 2 }} />
          <TextField fullWidth label="Listed Description" value={listedDescription} onChange={(e) => setListedDescription(e.target.value)} multiline rows={3} sx={{ mb: 2 }} />
          <TextField fullWidth label="Listing Price" type="number" value={listingPrice} onChange={(e) => setListingPrice(e.target.value)} InputProps={{ startAdornment: <InputAdornment position="start">$</InputAdornment> }} sx={{ mb: 2 }} />
          <TextField fullWidth label="Listing Quantity" type="number" value={listingQuantity} onChange={(e) => setListingQuantity(e.target.value)} sx={{ mb: 2 }} />
          <TextField fullWidth label="Listing Type" value={listingType} onChange={(e) => setListingType(e.target.value)} sx={{ mb: 2 }} />
          <TextField fullWidth label="Listing Condition" value={listingCondition} onChange={(e) => setListingCondition(e.target.value)} sx={{ mb: 2 }} />
          <TextField fullWidth label="UPC" value={upc} onChange={(e) => setUpc(e.target.value)} />
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={handleSubmit} disabled={updateMutation.isPending}>
          {updateMutation.isPending ? <CircularProgress size={24} /> : 'Save'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export default function ProductListings() {
  const [searchInput, setSearchInput] = useState('')
  const debouncedSearch = useDebouncedValue(searchInput, 200)
  const [viewMode, setViewMode] = useState<'ALL' | 'BY_SKU'>('ALL')
  const [platformFilter, setPlatformFilter] = useState<Platform | ''>('')
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [matchFilter, setMatchFilter] = useState<'ALL' | 'MATCHED' | 'UNMATCHED'>('ALL')
  const [filtersDialogOpen, setFiltersDialogOpen] = useState(false)
  const [createDialogOpen, setCreateDialogOpen] = useState(false)
  const [page, setPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(25)
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set())
  const [matchingListingId, setMatchingListingId] = useState<number | null>(null)
  const [selectedMatchVariant, setSelectedMatchVariant] = useState<any | null>(null)
  const [editingListing, setEditingListing] = useState<EnhancedListing | null>(null)
  const [editDialogOpen, setEditDialogOpen] = useState(false)
  const { hasRole } = useAuth()
  const queryClient = useQueryClient()

  const { data: listingsResponse, isLoading: listingsLoading, isFetching: listingsFetching } = useQuery({
    queryKey: ['listings', page, rowsPerPage, platformFilter, statusFilter],
    queryFn: async () => {
      const params: Record<string, any> = { skip: page * rowsPerPage, limit: rowsPerPage }
      if (platformFilter) params.platform = platformFilter
      if (statusFilter) params.sync_status = statusFilter
      const response = await axiosClient.get(LISTINGS.LIST, { params })
      return {
        total: Number(response.data?.total || 0),
        items: (response.data?.items || []) as PlatformListing[],
      }
    },
    placeholderData: (previousData) => previousData,
  })

  // Fetch variants for listing creation
  const { data: variantsData } = useQuery({
    queryKey: ['variants'],
    queryFn: async () => {
      const response = await axiosClient.get(CATALOG.VARIANTS, { params: { limit: 1000 } })
      return response.data.items || []
    },
  })

  // Fetch identities
  const { data: identitiesData } = useQuery({
    queryKey: ['identities'],
    queryFn: async () => {
      const response = await axiosClient.get(CATALOG.IDENTITIES, { params: { limit: 1000 } })
      return response.data.items || []
    },
  })

  // Fetch families
  const { data: familiesData } = useQuery({
    queryKey: ['families'],
    queryFn: async () => {
      const response = await axiosClient.get(CATALOG.FAMILIES, { params: { limit: 1000 } })
      return response.data.items || []
    },
  })

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await axiosClient.delete(LISTINGS.LISTING(id))
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['listings'] })
    },
  })
  const syncMutation = useMutation({
    mutationFn: async (id: number) => {
      const response = await axiosClient.post(LISTINGS.SYNC(id))
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['listings'] })
    },
  })
  const matchMutation = useMutation({
    mutationFn: async ({ listingId, variantId }: { listingId: number; variantId: number }) => {
      const response = await axiosClient.post(LISTINGS.MATCH(listingId), { variant_id: variantId })
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['listings'] })
      setMatchingListingId(null)
      setSelectedMatchVariant(null)
    },
  })
  const unmatchMutation = useMutation({
    mutationFn: async (listingId: number) => {
      const response = await axiosClient.post(LISTINGS.UNMATCH(listingId))
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['listings'] })
      setMatchingListingId(null)
      setSelectedMatchVariant(null)
    },
  })

  // Enhanced variants with identity/family data
  const enhancedVariants = useMemo(() => {
    if (!variantsData || !identitiesData || !familiesData) return []
    
    const familyMap = new Map<number, ProductFamily>()
    familiesData.forEach((f: ProductFamily) => familyMap.set(f.product_id, f))
    
    const identityMap = new Map<number, ProductIdentity & { family?: ProductFamily }>()
    identitiesData.forEach((i: ProductIdentity) => {
      identityMap.set(i.id, { ...i, family: familyMap.get(i.product_id) })
    })
    
    return variantsData.map((v: Variant) => ({
      ...v,
      identity: identityMap.get(v.identity_id),
    }))
  }, [variantsData, identitiesData, familiesData])

  // Enhanced listings with variant/identity/family data
  const enhancedListings: EnhancedListing[] = useMemo(() => {
    if (!listingsResponse?.items) return []
    
    const variantMap = new Map<number, any>()
    enhancedVariants.forEach((v: any) => variantMap.set(v.id, v))
    
    return listingsResponse.items.map((l: PlatformListing) => ({
      ...l,
      variant: variantMap.get(l.variant_id),
    }))
  }, [listingsResponse, enhancedVariants])

  // Filter by search query + match state
  const filteredListings = useMemo(() => {
    const matchesSearch = compileSearchMatcher(debouncedSearch)
    return enhancedListings.filter((listing) => {
      const matchesText = matchesSearch([
        listing.variant?.full_sku,
        listing.variant?.identity?.family?.base_name,
        listing.listed_name,
        listing.external_ref_id,
      ])
      if (!matchesText) return false
      if (matchFilter === 'MATCHED') return Boolean(listing.variant_id)
      if (matchFilter === 'UNMATCHED') return !listing.variant_id
      return true
    })
  }, [enhancedListings, debouncedSearch, matchFilter])

  interface SkuGroup {
    key: string
    sku: string
    name: string
    thumbnail?: string
    type?: string
    condition?: string
    color?: string
    listings: EnhancedListing[]
  }

  const groupedBySku: SkuGroup[] = useMemo(() => {
    const groups = new Map<string, SkuGroup>()

    filteredListings.forEach((listing) => {
      const key = listing.variant_id ? `sku-${listing.variant_id}` : 'unmatched'
      if (!groups.has(key)) {
        groups.set(key, {
          key,
          sku: listing.variant?.full_sku || 'Unmatched Listings',
          name: listing.variant?.identity?.family?.base_name || 'Listings with no matched SKU',
          thumbnail: listing.variant?.thumbnail_url,
          type: listing.variant?.identity?.identity_type || '-',
          condition: listing.listing_condition || listing.variant?.condition_code || '-',
          color: listing.variant?.color_code || '-',
          listings: [],
        })
      }
      groups.get(key)!.listings.push(listing)
    })

    return Array.from(groups.values()).sort((a, b) => {
      if (a.key === 'unmatched') return -1
      if (b.key === 'unmatched') return 1
      return a.sku.localeCompare(b.sku)
    })
  }, [filteredListings])

  const totalListings = listingsResponse?.total || 0
  useEffect(() => {
    setPage(0)
  }, [viewMode, platformFilter, statusFilter, matchFilter, debouncedSearch, rowsPerPage])

  const toggleGroup = (key: string) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const handleDelete = (id: number) => {
    if (confirm('Are you sure you want to delete this listing?')) {
      deleteMutation.mutate(id)
    }
  }

  const handleEdit = (listing: EnhancedListing) => {
    setEditingListing(listing)
    setEditDialogOpen(true)
  }

  const getPlatformLabel = (platform: Platform) => {
    return PLATFORMS.find(p => p.value === platform)?.label || platform
  }

  const buildListingLink = (listing: EnhancedListing) => {
    const externalRef = (listing.external_ref_id || '').trim()
    if (!externalRef) return null
    if (listing.platform.startsWith('EBAY_')) return `https://www.ebay.com/itm/${externalRef}`
    if (listing.platform === 'AMAZON') return `https://amazon.com/dp/${externalRef}`
    if (listing.platform === 'WALMART') return `https://www.walmart.com/ip/${externalRef}`
    return null
  }

  const renderListingRow = (listing: EnhancedListing) => {
    const isMatching = matchingListingId === listing.id
    const listingLink = buildListingLink(listing)
    const anyPending =
      syncMutation.isPending || matchMutation.isPending || unmatchMutation.isPending || deleteMutation.isPending
    return (
      <Fragment key={listing.id}>
        <TableRow hover sx={{ cursor: 'pointer' }} onClick={() => handleEdit(listing)}>
          <TableCell>
            <Chip size="small" label={getPlatformLabel(listing.platform)} variant="outlined" />
          </TableCell>
          <TableCell>{listing.listed_name || '-'}</TableCell>
          <TableCell>
            <Typography variant="body2" fontFamily="monospace">
              {listing.external_ref_id || '-'}
            </Typography>
          </TableCell>
          <TableCell>{listing.listing_price != null ? `$${listing.listing_price.toFixed(2)}` : '-'}</TableCell>
          <TableCell>{listing.listing_quantity ?? '-'}</TableCell>
          <TableCell>{getSyncStatusChip(listing.sync_status, listing.sync_error_message)}</TableCell>
          <TableCell>
            <Box sx={{ display: 'flex', gap: 0.5 }}>
              <Tooltip title="Queue Sync">
                <span>
                  <IconButton
                    size="small"
                    onClick={(e) => {
                      e.stopPropagation()
                      syncMutation.mutate(listing.id)
                    }}
                    disabled={anyPending}
                  >
                    <Refresh fontSize="small" />
                  </IconButton>
                </span>
              </Tooltip>
              <Tooltip title="View Platform Listing">
                <span>
                  <IconButton
                    size="small"
                    onClick={(e) => {
                      e.stopPropagation()
                      if (listingLink) window.open(listingLink, '_blank', 'noopener,noreferrer')
                    }}
                    disabled={!listingLink}
                  >
                    <Visibility fontSize="small" />
                  </IconButton>
                </span>
              </Tooltip>
              {!listing.variant_id ? (
                <Tooltip title="Match to SKU">
                  <span>
                    <IconButton
                      size="small"
                      color="primary"
                      onClick={(e) => {
                        e.stopPropagation()
                        setMatchingListingId((prev) => (prev === listing.id ? null : listing.id))
                        setSelectedMatchVariant(null)
                      }}
                      disabled={anyPending}
                    >
                      <LinkIcon fontSize="small" />
                    </IconButton>
                  </span>
                </Tooltip>
              ) : (
                <Tooltip title="Unmatch from SKU">
                  <span>
                    <IconButton
                      size="small"
                      color="error"
                      onClick={(e) => {
                        e.stopPropagation()
                        unmatchMutation.mutate(listing.id)
                      }}
                      disabled={anyPending}
                    >
                      <LinkOff fontSize="small" />
                    </IconButton>
                  </span>
                </Tooltip>
              )}
            </Box>
          </TableCell>
        </TableRow>
        {isMatching && (
          <TableRow>
            <TableCell colSpan={7}>
              <Box sx={{ display: 'flex', gap: 1.5, alignItems: 'center', py: 1 }}>
                <Autocomplete
                  options={enhancedVariants}
                  getOptionLabel={(option: any) => `${option.full_sku} - ${option.identity?.family?.base_name || 'Unknown'}`}
                  value={selectedMatchVariant}
                  onChange={(_, value) => setSelectedMatchVariant(value)}
                  renderInput={(params) => <TextField {...params} label="Match to SKU" size="small" />}
                  sx={{ minWidth: 360 }}
                />
                <Button
                  size="small"
                  variant="contained"
                  onClick={() => {
                    if (!selectedMatchVariant) return
                    matchMutation.mutate({ listingId: listing.id, variantId: selectedMatchVariant.id })
                  }}
                  disabled={!selectedMatchVariant || matchMutation.isPending}
                >
                  Match
                </Button>
                <Button size="small" onClick={() => setMatchingListingId(null)}>
                  Cancel
                </Button>
              </Box>
            </TableCell>
          </TableRow>
        )}
      </Fragment>
    )
  }

  const clearAllFilters = () => {
    setPlatformFilter('')
    setStatusFilter('')
    setMatchFilter('ALL')
  }

  const activeFilterCount = [platformFilter ? 1 : 0, statusFilter ? 1 : 0, matchFilter !== 'ALL' ? 1 : 0].reduce(
    (sum, n) => sum + n,
    0,
  )

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h4">Active Listings</Typography>
        {hasRole(['ADMIN', 'SALES_REP']) && (
          <Button
            variant="contained"
            startIcon={<Add />}
            onClick={() => setCreateDialogOpen(true)}
          >
            Add Listing
          </Button>
        )}
      </Box>

      <Paper sx={{ p: 2, mb: 3 }}>
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
          <Button
            size="small"
            variant={viewMode === 'ALL' ? 'contained' : 'outlined'}
            onClick={() => setViewMode('ALL')}
          >
            All Listings
          </Button>
          <Button
            size="small"
            variant={viewMode === 'BY_SKU' ? 'contained' : 'outlined'}
            onClick={() => setViewMode('BY_SKU')}
          >
            Listings to SKU
          </Button>
          <SearchField
            placeholder="Search by SKU, item name, external ID, or listed name..."
            value={searchInput}
            onChange={setSearchInput}
            size="small"
            sx={{ flexGrow: 1, minWidth: 250 }}
          />
          <Button
            size="small"
            variant="outlined"
            onClick={() => setFiltersDialogOpen(true)}
          >
            Filters{activeFilterCount > 0 ? ` (${activeFilterCount})` : ''}
          </Button>
          <Button size="small" onClick={clearAllFilters} disabled={activeFilterCount === 0}>
            Clear
          </Button>
          <IconButton onClick={() => queryClient.invalidateQueries({ queryKey: ['listings'] })} title="Refresh">
            <Refresh />
          </IconButton>
        </Box>
      </Paper>

      <Paper>
        {listingsFetching && !listingsLoading && (
          <Box sx={{ px: 2, pt: 1 }}>
            <Typography variant="caption" color="text.secondary">
              Loading page...
            </Typography>
          </Box>
        )}
        {listingsLoading ? (
          <Box sx={{ py: 6, textAlign: 'center' }}>
            <CircularProgress size={24} />
          </Box>
        ) : filteredListings.length === 0 ? (
          <Box sx={{ py: 6, textAlign: 'center' }}>
            <Typography color="text.secondary">No listings found</Typography>
          </Box>
        ) : viewMode === 'ALL' ? (
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>Platform</TableCell>
                  <TableCell>Listed Name</TableCell>
                  <TableCell>External Ref ID</TableCell>
                  <TableCell>Price</TableCell>
                  <TableCell>Qty</TableCell>
                  <TableCell>Sync Status</TableCell>
                  <TableCell>Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>{filteredListings.map((listing) => renderListingRow(listing))}</TableBody>
            </Table>
          </TableContainer>
        ) : (
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell sx={{ width: 40 }} />
                  <TableCell>SKU</TableCell>
                  <TableCell>Name</TableCell>
                  <TableCell>Thumbnail</TableCell>
                  <TableCell>Type</TableCell>
                  <TableCell>Condition</TableCell>
                  <TableCell>Color</TableCell>
                  <TableCell align="center">Listings</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {groupedBySku.map((group) => {
                  const isExpanded = expandedGroups.has(group.key)
                  return (
                    <Fragment key={group.key}>
                      <TableRow hover sx={{ cursor: 'pointer' }} onClick={() => toggleGroup(group.key)}>
                        <TableCell>
                          <IconButton size="small">{isExpanded ? <ExpandLess /> : <ExpandMore />}</IconButton>
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2" fontFamily="monospace">
                            {group.sku}
                          </Typography>
                        </TableCell>
                        <TableCell>{group.name}</TableCell>
                        <TableCell>
                          {group.thumbnail ? (
                            <img src={group.thumbnail} alt={group.sku} style={{ width: 40, height: 40, objectFit: 'cover', borderRadius: 4 }} />
                          ) : (
                            '-'
                          )}
                        </TableCell>
                        <TableCell>{group.type || '-'}</TableCell>
                        <TableCell>{group.condition || '-'}</TableCell>
                        <TableCell>{group.color || '-'}</TableCell>
                        <TableCell align="center">
                          <Chip size="small" label={group.listings.length} />
                        </TableCell>
                      </TableRow>
                      <TableRow>
                        <TableCell colSpan={8} sx={{ py: 0 }}>
                          <Collapse in={isExpanded} timeout="auto" unmountOnExit>
                            <Box sx={{ p: 1.5, bgcolor: 'grey.50' }}>
                              <Table size="small">
                                <TableHead>
                                  <TableRow>
                                    <TableCell>Platform</TableCell>
                                    <TableCell>Listed Name</TableCell>
                                    <TableCell>External Ref ID</TableCell>
                                    <TableCell>Price</TableCell>
                                    <TableCell>Qty</TableCell>
                                    <TableCell>Sync Status</TableCell>
                                    <TableCell>Actions</TableCell>
                                  </TableRow>
                                </TableHead>
                                <TableBody>{group.listings.map((listing) => renderListingRow(listing))}</TableBody>
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
        <TablePagination
          component="div"
          rowsPerPageOptions={[10, 25, 50, 100]}
          count={totalListings}
          rowsPerPage={rowsPerPage}
          page={page}
          onPageChange={(_event, newPage) => setPage(newPage)}
          onRowsPerPageChange={(event) => {
            setRowsPerPage(parseInt(event.target.value, 10))
            setPage(0)
          }}
        />
      </Paper>

      <CreateListingDialog
        open={createDialogOpen}
        onClose={() => setCreateDialogOpen(false)}
        variants={enhancedVariants}
      />
      <EditListingDialog
        open={editDialogOpen}
        onClose={() => setEditDialogOpen(false)}
        listing={editingListing}
      />

      <Dialog open={filtersDialogOpen} onClose={() => setFiltersDialogOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Listing Filters</DialogTitle>
        <DialogContent>
          <Box sx={{ display: 'grid', gap: 2, mt: 1 }}>
            <FormControl fullWidth size="small">
              <InputLabel>Platform</InputLabel>
              <Select
                value={platformFilter}
                label="Platform"
                onChange={(e: SelectChangeEvent<Platform | ''>) => setPlatformFilter(e.target.value as Platform | '')}
              >
                <MenuItem value="">All Platforms</MenuItem>
                {PLATFORMS.map((p) => (
                  <MenuItem key={p.value} value={p.value}>
                    {p.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl fullWidth size="small">
              <InputLabel>Sync Status</InputLabel>
              <Select value={statusFilter} label="Sync Status" onChange={(e: SelectChangeEvent<string>) => setStatusFilter(e.target.value)}>
                <MenuItem value="">All Statuses</MenuItem>
                <MenuItem value="SYNCED">Synced</MenuItem>
                <MenuItem value="PENDING">Pending</MenuItem>
                <MenuItem value="ERROR">Error</MenuItem>
              </Select>
            </FormControl>
            <FormControl fullWidth size="small">
              <InputLabel>Match State</InputLabel>
              <Select
                value={matchFilter}
                label="Match State"
                onChange={(e: SelectChangeEvent<'ALL' | 'MATCHED' | 'UNMATCHED'>) =>
                  setMatchFilter(e.target.value as 'ALL' | 'MATCHED' | 'UNMATCHED')
                }
              >
                <MenuItem value="ALL">All</MenuItem>
                <MenuItem value="MATCHED">Matched</MenuItem>
                <MenuItem value="UNMATCHED">Unmatched</MenuItem>
              </Select>
            </FormControl>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => {
              clearAllFilters()
              setFiltersDialogOpen(false)
            }}
          >
            Reset
          </Button>
          <Button variant="contained" onClick={() => setFiltersDialogOpen(false)}>
            Apply
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}

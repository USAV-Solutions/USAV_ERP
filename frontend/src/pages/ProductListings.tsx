import React, { useState, useMemo } from 'react'
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
} from '@mui/material'
import {
  Add,
  Search,
  Refresh,
  Error as ErrorIcon,
  CheckCircle,
  Schedule,
  Delete,
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
} from '../types/inventory'
import { useAuth } from '../hooks/useAuth'

const PLATFORMS: { value: Platform; label: string }[] = [
  { value: 'AMAZON', label: 'Amazon' },
  { value: 'EBAY_MEKONG', label: 'eBay Mekong' },
  { value: 'EBAY_USAV', label: 'eBay USAV' },
  { value: 'EBAY_DRAGON', label: 'eBay Dragon' },
  { value: 'ECWID', label: 'ECWID' },
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

export default function ProductListings() {
  const [searchQuery, setSearchQuery] = useState('')
  const [platformFilter, setPlatformFilter] = useState<Platform | ''>('')
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [createDialogOpen, setCreateDialogOpen] = useState(false)
  const [page, setPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(25)
  const { hasRole } = useAuth()
  const queryClient = useQueryClient()

  // Fetch listings
  const { data: listingsData, isLoading: listingsLoading } = useQuery({
    queryKey: ['listings', platformFilter, statusFilter],
    queryFn: async () => {
      const params: Record<string, any> = { limit: 1000 }
      if (platformFilter) params.platform = platformFilter
      if (statusFilter) params.sync_status = statusFilter
      
      const response = await axiosClient.get(LISTINGS.LIST, { params })
      return response.data.items || []
    },
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
    if (!listingsData) return []
    
    const variantMap = new Map<number, any>()
    enhancedVariants.forEach((v: any) => variantMap.set(v.id, v))
    
    return listingsData.map((l: PlatformListing) => ({
      ...l,
      variant: variantMap.get(l.variant_id),
    }))
  }, [listingsData, enhancedVariants])

  // Filter by search query
  const filteredListings = useMemo(() => {
    if (!searchQuery.trim()) return enhancedListings
    
    const query = searchQuery.toLowerCase()
    return enhancedListings.filter((listing) => {
      const sku = listing.variant?.full_sku?.toLowerCase() || ''
      const name = listing.variant?.identity?.family?.base_name?.toLowerCase() || ''
      const refId = listing.external_ref_id?.toLowerCase() || ''
      
      return sku.includes(query) || name.includes(query) || refId.includes(query)
    })
  }, [enhancedListings, searchQuery])

  // Paginated data
  const paginatedData = filteredListings.slice(
    page * rowsPerPage,
    page * rowsPerPage + rowsPerPage
  )

  const handleDelete = (id: number) => {
    if (confirm('Are you sure you want to delete this listing?')) {
      deleteMutation.mutate(id)
    }
  }

  const getPlatformLabel = (platform: Platform) => {
    return PLATFORMS.find(p => p.value === platform)?.label || platform
  }

  return (
    <Box>
      {/* Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h4">Product Listings</Typography>
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

      {/* Filters */}
      <Paper sx={{ p: 2, mb: 3 }}>
        <Box sx={{ display: 'flex', gap: 2, alignItems: 'center', flexWrap: 'wrap' }}>
          <TextField
            placeholder="Search by SKU, name, or external ID..."
            value={searchQuery}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSearchQuery(e.target.value)}
            size="small"
            sx={{ flexGrow: 1, minWidth: 250 }}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <Search />
                </InputAdornment>
              ),
            }}
          />
          
          <FormControl size="small" sx={{ minWidth: 150 }}>
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

          <FormControl size="small" sx={{ minWidth: 130 }}>
            <InputLabel>Status</InputLabel>
            <Select
              value={statusFilter}
              label="Status"
              onChange={(e: SelectChangeEvent<string>) => setStatusFilter(e.target.value)}
            >
              <MenuItem value="">All Statuses</MenuItem>
              <MenuItem value="SYNCED">Synced</MenuItem>
              <MenuItem value="PENDING">Pending</MenuItem>
              <MenuItem value="ERROR">Error</MenuItem>
            </Select>
          </FormControl>

          <IconButton
            onClick={() => queryClient.invalidateQueries({ queryKey: ['listings'] })}
            title="Refresh"
          >
            <Refresh />
          </IconButton>
        </Box>
      </Paper>

      {/* Listings Table */}
      <Paper>
        <TableContainer>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>SKU</TableCell>
                <TableCell>Product Name</TableCell>
                <TableCell>Platform</TableCell>
                <TableCell>Listed Name</TableCell>
                <TableCell>Listed Description</TableCell>
                <TableCell>External Ref ID</TableCell>
                <TableCell>Price</TableCell>
                <TableCell>Sync Status</TableCell>
                <TableCell>Last Synced</TableCell>
                <TableCell>Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {listingsLoading ? (
                <TableRow>
                  <TableCell colSpan={10} align="center">
                    <CircularProgress size={24} />
                  </TableCell>
                </TableRow>
              ) : paginatedData.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={10} align="center">
                    No listings found
                  </TableCell>
                </TableRow>
              ) : (
                paginatedData.map((listing: EnhancedListing) => (
                  <TableRow key={listing.id} hover>
                    <TableCell>
                      <Typography variant="body2" fontFamily="monospace">
                        {listing.variant?.full_sku || '-'}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      {listing.variant?.identity?.family?.base_name || '-'}
                    </TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        label={getPlatformLabel(listing.platform)}
                        variant="outlined"
                      />
                    </TableCell>
                    <TableCell>
                      <Tooltip title={listing.listed_name || ''}>
                        <Typography variant="body2" noWrap sx={{ maxWidth: 200 }}>
                          {listing.listed_name || '-'}
                        </Typography>
                      </Tooltip>
                    </TableCell>
                    <TableCell>
                      <Tooltip title={listing.listed_description || ''}>
                        <Typography variant="body2" noWrap sx={{ maxWidth: 200 }}>
                          {listing.listed_description || '-'}
                        </Typography>
                      </Tooltip>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" fontFamily="monospace">
                        {listing.external_ref_id || '-'}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      {listing.listing_price != null ? `$${listing.listing_price.toFixed(2)}` : '-'}
                    </TableCell>
                    <TableCell>
                      {getSyncStatusChip(listing.sync_status, listing.sync_error_message)}
                    </TableCell>
                    <TableCell>
                      {listing.last_synced_at
                        ? new Date(listing.last_synced_at).toLocaleDateString()
                        : '-'}
                    </TableCell>
                    <TableCell>
                      {hasRole(['ADMIN']) && (
                        <Tooltip title="Delete Listing">
                          <IconButton
                            size="small"
                            color="error"
                            onClick={() => handleDelete(listing.id)}
                            disabled={deleteMutation.isPending}
                          >
                            <Delete fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      )}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </TableContainer>
        <TablePagination
          rowsPerPageOptions={[10, 25, 50, 100]}
          component="div"
          count={filteredListings.length}
          rowsPerPage={rowsPerPage}
          page={page}
          onPageChange={(_: unknown, newPage: number) => setPage(newPage)}
          onRowsPerPageChange={(e: React.ChangeEvent<HTMLInputElement>) => {
            setRowsPerPage(parseInt(e.target.value, 10))
            setPage(0)
          }}
        />
      </Paper>

      {/* Create Listing Dialog */}
      <CreateListingDialog
        open={createDialogOpen}
        onClose={() => setCreateDialogOpen(false)}
        variants={enhancedVariants}
      />
    </Box>
  )
}

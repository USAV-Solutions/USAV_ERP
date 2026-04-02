import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Autocomplete,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  MenuItem,
  Snackbar,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { Add, DeleteOutline } from '@mui/icons-material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import axiosClient from '../../api/axiosClient'
import { CATALOG, LOOKUPS } from '../../api/endpoints'
import IdentitySearchAutocomplete from '../common/IdentitySearchAutocomplete'
import VariantSearchAutocomplete from '../common/VariantSearchAutocomplete'
import type { VariantSearchResult } from '../../types/orders'
import type { Brand, IdentitySearchResult, LCIDefinition, ProductIdentity } from '../../types/inventory'

type Mode = 'product' | 'part' | 'bundle' | 'stationery'
type BundleRole = 'Primary' | 'Accessory' | 'Satellite'

interface BundleLine {
  key: string
  variant: VariantSearchResult | null
  quantity: number
  role: BundleRole
}

interface CreateCatalogItemDialogProps {
  open: boolean
  onClose: () => void
}

export default function CreateCatalogItemDialog({ open, onClose }: CreateCatalogItemDialogProps) {
  const queryClient = useQueryClient()

  const [mode, setMode] = useState<Mode>('product')
  const [name, setName] = useState('')
  const [selectedBrand, setSelectedBrand] = useState<Brand | null>(null)
  const [brandNameInput, setBrandNameInput] = useState('')

  const [dimensionLength, setDimensionLength] = useState('')
  const [dimensionWidth, setDimensionWidth] = useState('')
  const [dimensionHeight, setDimensionHeight] = useState('')
  const [weight, setWeight] = useState('')

  const [partParentIdentity, setPartParentIdentity] = useState<IdentitySearchResult | null>(null)
  const [selectedLciDefinition, setSelectedLciDefinition] = useState<LCIDefinition | null>(null)
  const [partLciNameInput, setPartLciNameInput] = useState('')

  const [bundleLines, setBundleLines] = useState<BundleLine[]>([
    { key: 'line-1', variant: null, quantity: 1, role: 'Primary' },
  ])

  const [snackbar, setSnackbar] = useState<{ open: boolean; msg: string; severity: 'success' | 'error' }>({
    open: false,
    msg: '',
    severity: 'success',
  })

  useEffect(() => {
    if (!open) return
    setMode('product')
    setName('')
    setSelectedBrand(null)
    setBrandNameInput('')
    setDimensionLength('')
    setDimensionWidth('')
    setDimensionHeight('')
    setWeight('')
    setPartParentIdentity(null)
    setSelectedLciDefinition(null)
    setPartLciNameInput('')
    setBundleLines([{ key: `line-${Date.now()}`, variant: null, quantity: 1, role: 'Primary' }])
  }, [open])

  const { data: brands = [] } = useQuery({
    queryKey: ['brands'],
    queryFn: async () => {
      const response = await axiosClient.get(LOOKUPS.BRANDS, { params: { limit: 1000 } })
      return response.data.items || []
    },
    enabled: open,
  })

  const { data: lciDefinitions = [] } = useQuery({
    queryKey: ['lci-definitions', partParentIdentity?.product_id],
    queryFn: async () => {
      if (!partParentIdentity) return []
      const response = await axiosClient.get(LOOKUPS.LCI_DEFINITIONS, {
        params: { product_id: partParentIdentity.product_id, limit: 1000 },
      })
      return response.data.items || []
    },
    enabled: open && mode === 'part' && !!partParentIdentity,
  })

  const normalizedBrandNameInput = brandNameInput.trim().toLowerCase()
  const matchingBrandByName = (brands as Brand[]).find(
    (brand) => brand.name.trim().toLowerCase() === normalizedBrandNameInput,
  )
  const canCreateBrand = normalizedBrandNameInput.length > 0 && !matchingBrandByName

  const normalizedLciNameInput = partLciNameInput.trim().toLowerCase()
  const matchingLciByName = (lciDefinitions as LCIDefinition[]).find(
    (definition) => definition.component_name.trim().toLowerCase() === normalizedLciNameInput,
  )
  const canCreateLci = !!partParentIdentity && normalizedLciNameInput.length > 0 && !matchingLciByName

  const skuPreview = useMemo(() => {
    const normalizedName = name.trim()
    if (!normalizedName) return 'Enter a name to preview SKU'

    const padFamilyId = (id: number) => String(id).padStart(5, '0')

    if (mode === 'product') {
      return 'UPIS-H: [auto family id], Default Variant SKU: [same as UPIS-H]'
    }

    if (mode === 'stationery') {
      return 'SKU: STAT-[auto 5-digit sequence], single-SKU only'
    }

    if (mode === 'bundle') {
      return 'UPIS-H: [auto family id]-B'
    }

    if (!partParentIdentity) {
      return 'Select parent product to preview part SKU'
    }

    return `UPIS-H: ${padFamilyId(partParentIdentity.product_id)}-P-[auto], Default Variant SKU: same as UPIS-H`
  }, [mode, name, partParentIdentity])

  const createBrandMutation = useMutation({
    mutationFn: async () => {
      const brandName = brandNameInput.trim()
      if (!brandName) {
        throw new Error('Brand name is required.')
      }
      const response = await axiosClient.post(LOOKUPS.BRANDS, { name: brandName })
      return response.data as Brand
    },
    onSuccess: async (brand) => {
      setSelectedBrand(brand)
      setBrandNameInput(brand.name)
      await queryClient.invalidateQueries({ queryKey: ['brands'] })
      setSnackbar({ open: true, msg: `Brand '${brand.name}' created.`, severity: 'success' })
    },
    onError: (error: any) => {
      const detail = error?.response?.data?.detail || error?.message || 'Failed to create brand.'
      setSnackbar({ open: true, msg: detail, severity: 'error' })
    },
  })

  const createLciMutation = useMutation({
    mutationFn: async () => {
      if (!partParentIdentity) {
        throw new Error('Select a parent product first.')
      }
      const componentName = partLciNameInput.trim()
      if (!componentName) {
        throw new Error('LCI name is required.')
      }

      const response = await axiosClient.post(LOOKUPS.LCI_DEFINITIONS, {
        product_id: partParentIdentity.product_id,
        component_name: componentName,
      })
      return response.data as LCIDefinition
    },
    onSuccess: async (definition) => {
      setSelectedLciDefinition(definition)
      setPartLciNameInput(definition.component_name)
      await queryClient.invalidateQueries({ queryKey: ['lci-definitions', partParentIdentity?.product_id] })
      setSnackbar({ open: true, msg: `LCI '${definition.component_name}' created.`, severity: 'success' })
    },
    onError: (error: any) => {
      const detail = error?.response?.data?.detail || error?.message || 'Failed to create LCI definition.'
      setSnackbar({ open: true, msg: detail, severity: 'error' })
    },
  })

  const createMutation = useMutation({
    mutationFn: async () => {
      if (!name.trim()) {
        throw new Error('Name is required.')
      }

      const parseNumberOrUndefined = (raw: string): number | undefined => {
        const normalized = raw.trim()
        if (!normalized) return undefined
        const value = Number(normalized)
        if (!Number.isFinite(value) || value < 0) {
          throw new Error('Length, width, height, and weight must be non-negative numbers.')
        }
        return value
      }

      const dimensionsPayload = {
        dimension_length: parseNumberOrUndefined(dimensionLength),
        dimension_width: parseNumberOrUndefined(dimensionWidth),
        dimension_height: parseNumberOrUndefined(dimensionHeight),
        weight: parseNumberOrUndefined(weight),
      }

      if (mode === 'product') {
        const familyResponse = await axiosClient.post(CATALOG.FAMILIES, {
          base_name: name.trim(),
          brand_id: selectedBrand?.id,
        })

        await axiosClient.post(CATALOG.IDENTITIES, {
          product_id: familyResponse.data.product_id,
          type: 'Product',
          identity_name: name.trim(),
          is_stationery: false,
          ...dimensionsPayload,
        })
        return
      }

      if (mode === 'stationery') {
        const familyResponse = await axiosClient.post(CATALOG.FAMILIES, {
          base_name: name.trim(),
          brand_id: selectedBrand?.id,
        })

        await axiosClient.post(CATALOG.IDENTITIES, {
          product_id: familyResponse.data.product_id,
          type: 'Product',
          identity_name: name.trim(),
          is_stationery: true,
          ...dimensionsPayload,
        })
        return
      }

      if (mode === 'part') {
        if (!partParentIdentity) throw new Error('Please select a parent product identity.')
        const lciComponentName = partLciNameInput.trim() || selectedLciDefinition?.component_name?.trim() || ''

        const identityPayload: Record<string, unknown> = {
          product_id: partParentIdentity.product_id,
          type: 'P',
          identity_name: name.trim() || undefined,
          ...dimensionsPayload,
        }

        const identityResponse = await axiosClient.post(CATALOG.IDENTITIES, identityPayload)
        const createdIdentity = identityResponse.data as ProductIdentity

        const definitionExists = (lciDefinitions as LCIDefinition[]).some(
          (definition) => definition.component_name.trim().toLowerCase() === lciComponentName.toLowerCase(),
        )

        if (lciComponentName && !definitionExists) {
          await axiosClient.post(LOOKUPS.LCI_DEFINITIONS, {
            product_id: partParentIdentity.product_id,
            lci_index: createdIdentity.lci,
            component_name: lciComponentName,
          })
        }
        return
      }

      // bundle
      const validLines = bundleLines.filter((line) => line.variant && line.quantity > 0)
      if (validLines.length === 0) {
        throw new Error('Bundle needs at least one valid line item.')
      }

      const familyResponse = await axiosClient.post(CATALOG.FAMILIES, {
        base_name: name.trim(),
      })

      const identityResponse = await axiosClient.post(CATALOG.IDENTITIES, {
        product_id: familyResponse.data.product_id,
        type: 'B',
        identity_name: name.trim(),
      })
      const bundleIdentity = identityResponse.data as ProductIdentity

      for (const line of validLines) {
        const childIdentityId = line.variant?.identity_id
        if (!childIdentityId) {
          throw new Error('Selected variant is missing identity mapping.')
        }
        await axiosClient.post(CATALOG.BUNDLES, {
          parent_identity_id: bundleIdentity.id,
          child_identity_id: childIdentityId,
          quantity_required: line.quantity,
          role: line.role,
        })
      }
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['families'] })
      await queryClient.invalidateQueries({ queryKey: ['identities'] })
      await queryClient.invalidateQueries({ queryKey: ['variants'] })
      setSnackbar({ open: true, msg: 'Catalog item created.', severity: 'success' })
      onClose()
    },
    onError: (error: any) => {
      const detail = error?.response?.data?.detail || error?.message || 'Failed to create catalog item.'
      setSnackbar({ open: true, msg: detail, severity: 'error' })
    },
  })

  const addBundleLine = () => {
    setBundleLines((prev) => [...prev, { key: `line-${Date.now()}-${prev.length}`, variant: null, quantity: 1, role: 'Accessory' }])
  }

  const updateBundleLine = (key: string, updater: (line: BundleLine) => BundleLine) => {
    setBundleLines((prev) => prev.map((line) => (line.key === key ? updater(line) : line)))
  }

  const removeBundleLine = (key: string) => {
    setBundleLines((prev) => prev.filter((line) => line.key !== key))
  }

  return (
    <>
      <Dialog open={open} onClose={onClose} fullWidth maxWidth="md">
        <DialogTitle>Add Product</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              select
              label="Mode"
              value={mode}
              onChange={(e) => setMode(e.target.value as Mode)}
              fullWidth
            >
              <MenuItem value="product">Product</MenuItem>
              <MenuItem value="part">Part</MenuItem>
              <MenuItem value="bundle">Bundle</MenuItem>
              <MenuItem value="stationery">Stationery</MenuItem>
            </TextField>

            <TextField
              label={
                mode === 'part'
                  ? 'Part Name'
                  : mode === 'bundle'
                    ? 'Bundle Name'
                    : mode === 'stationery'
                      ? 'Stationery Name'
                      : 'Product Name'
              }
              value={name}
              onChange={(e) => setName(e.target.value)}
              fullWidth
            />

            {(mode === 'product' || mode === 'stationery') && (
              <>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Autocomplete
                    sx={{ flex: 1 }}
                    options={brands as Brand[]}
                    value={selectedBrand}
                    inputValue={brandNameInput}
                    onInputChange={(_, value, reason) => {
                      if (reason === 'input' || reason === 'clear') {
                        setBrandNameInput(value)
                      }
                    }}
                    onChange={(_, value) => {
                      setSelectedBrand(value)
                      setBrandNameInput(value?.name || '')
                    }}
                    getOptionLabel={(option) => option.name}
                    renderInput={(params) => <TextField {...params} label="Brand (optional)" />}
                  />
                  <IconButton
                    color="primary"
                    onClick={() => createBrandMutation.mutate()}
                    disabled={!canCreateBrand || createBrandMutation.isPending}
                  >
                    {createBrandMutation.isPending ? <CircularProgress size={16} /> : <Add />}
                  </IconButton>
                </Stack>
                <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5}>
                  <TextField
                    label="Length"
                    type="number"
                    value={dimensionLength}
                    onChange={(e) => setDimensionLength(e.target.value)}
                    fullWidth
                  />
                  <TextField
                    label="Width"
                    type="number"
                    value={dimensionWidth}
                    onChange={(e) => setDimensionWidth(e.target.value)}
                    fullWidth
                  />
                  <TextField
                    label="Height"
                    type="number"
                    value={dimensionHeight}
                    onChange={(e) => setDimensionHeight(e.target.value)}
                    fullWidth
                  />
                  <TextField
                    label="Weight"
                    type="number"
                    value={weight}
                    onChange={(e) => setWeight(e.target.value)}
                    fullWidth
                  />
                </Stack>
              </>
            )}

            {mode === 'part' && (
              <>
                <IdentitySearchAutocomplete
                  value={partParentIdentity}
                  onChange={(value) => {
                    setPartParentIdentity(value)
                    setName((current) => (current.trim().length === 0 ? value?.family_name || '' : current))
                    setSelectedLciDefinition(null)
                    setPartLciNameInput('')
                  }}
                  includeTypes={['Product']}
                  label="Select Parent Product"
                  placeholder="Search by UPIS-H or product name..."
                  width="100%"
                />
                <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5}>
                  <TextField
                    label="Length"
                    type="number"
                    value={dimensionLength}
                    onChange={(e) => setDimensionLength(e.target.value)}
                    fullWidth
                  />
                  <TextField
                    label="Width"
                    type="number"
                    value={dimensionWidth}
                    onChange={(e) => setDimensionWidth(e.target.value)}
                    fullWidth
                  />
                  <TextField
                    label="Height"
                    type="number"
                    value={dimensionHeight}
                    onChange={(e) => setDimensionHeight(e.target.value)}
                    fullWidth
                  />
                  <TextField
                    label="Weight"
                    type="number"
                    value={weight}
                    onChange={(e) => setWeight(e.target.value)}
                    fullWidth
                  />
                </Stack>
                <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5}>
                  <Autocomplete
                    sx={{ flex: 1 }}
                    options={lciDefinitions as LCIDefinition[]}
                    value={selectedLciDefinition}
                    inputValue={partLciNameInput}
                    onInputChange={(_, value, reason) => {
                      if (reason === 'input' || reason === 'clear') {
                        setPartLciNameInput(value)
                      }
                    }}
                    onChange={(_, value) => {
                      setSelectedLciDefinition(value)
                      setPartLciNameInput(value ? value.component_name : '')
                    }}
                    getOptionLabel={(option) => `${option.lci_index} - ${option.component_name}`}
                    renderInput={(params) => <TextField {...params} label="LCI Name" />}
                    disabled={!partParentIdentity}
                  />
                  <IconButton
                    color="primary"
                    onClick={() => createLciMutation.mutate()}
                    disabled={!canCreateLci || createLciMutation.isPending}
                  >
                    {createLciMutation.isPending ? <CircularProgress size={16} /> : <Add />}
                  </IconButton>
                </Stack>
              </>
            )}

            {mode === 'bundle' && (
              <>
                <Typography variant="subtitle2">Bundle Items</Typography>
                {bundleLines.map((line) => (
                  <Stack key={line.key} direction={{ xs: 'column', md: 'row' }} spacing={1} alignItems="center">
                    <VariantSearchAutocomplete
                      value={line.variant}
                      onChange={(value) => updateBundleLine(line.key, (current) => ({ ...current, variant: value }))}
                      label="Search variant"
                      placeholder="Search by SKU, variant name, or product name..."
                      excludeIdentityTypes={['B', 'K']}
                      width="100%"
                    />
                    <TextField
                      label="Qty"
                      type="number"
                      value={line.quantity}
                      onChange={(e) =>
                        updateBundleLine(line.key, (current) => ({
                          ...current,
                          quantity: Math.max(1, Number(e.target.value) || 1),
                        }))
                      }
                      sx={{ width: 100 }}
                    />
                    <TextField
                      select
                      label="Role"
                      value={line.role}
                      onChange={(e) =>
                        updateBundleLine(line.key, (current) => ({ ...current, role: e.target.value as BundleRole }))
                      }
                      sx={{ width: 140 }}
                    >
                      <MenuItem value="Primary">Primary</MenuItem>
                      <MenuItem value="Accessory">Accessory</MenuItem>
                      <MenuItem value="Satellite">Satellite</MenuItem>
                    </TextField>
                    <IconButton color="error" onClick={() => removeBundleLine(line.key)}>
                      <DeleteOutline />
                    </IconButton>
                  </Stack>
                ))}
                <Button variant="outlined" startIcon={<Add />} onClick={addBundleLine}>
                  Add Line
                </Button>
                <Alert severity="info">Bundle creation here creates family + bundle identity + bundle component lines only.</Alert>
              </>
            )}

            <Stack>
              <Typography variant="subtitle2" color="text.secondary">
                SKU Preview
              </Typography>
              <Typography variant="body2" fontFamily="monospace">
                {skuPreview}
              </Typography>
            </Stack>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="contained" onClick={() => createMutation.mutate()} disabled={createMutation.isPending}>
            {createMutation.isPending ? <CircularProgress size={18} /> : 'Create'}
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={snackbar.open}
        autoHideDuration={3500}
        onClose={() => setSnackbar((prev) => ({ ...prev, open: false }))}
      >
        <Alert severity={snackbar.severity} sx={{ width: '100%' }}>
          {snackbar.msg}
        </Alert>
      </Snackbar>
    </>
  )
}

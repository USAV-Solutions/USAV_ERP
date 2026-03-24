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
import type { Brand, ProductFamily, ProductIdentity } from '../../types/inventory'

type Mode = 'product' | 'part' | 'bundle'
type BundleRole = 'Primary' | 'Accessory' | 'Satellite'

interface EnhancedIdentity extends ProductIdentity {
  family?: ProductFamily
}

interface BundleLine {
  key: string
  identity: EnhancedIdentity | null
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

  const [partParentFamily, setPartParentFamily] = useState<ProductFamily | null>(null)
  const [partIdentityName, setPartIdentityName] = useState('')
  const [partLciIndex, setPartLciIndex] = useState('')
  const [partLciComponentName, setPartLciComponentName] = useState('')

  const [bundleLines, setBundleLines] = useState<BundleLine[]>([
    { key: 'line-1', identity: null, quantity: 1, role: 'Primary' },
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
    setPartParentFamily(null)
    setPartIdentityName('')
    setPartLciIndex('')
    setPartLciComponentName('')
    setBundleLines([{ key: `line-${Date.now()}`, identity: null, quantity: 1, role: 'Primary' }])
  }, [open])

  const { data: brands = [] } = useQuery({
    queryKey: ['brands'],
    queryFn: async () => {
      const response = await axiosClient.get(LOOKUPS.BRANDS, { params: { limit: 1000 } })
      return response.data.items || []
    },
    enabled: open,
  })

  const { data: families = [] } = useQuery({
    queryKey: ['families'],
    queryFn: async () => {
      const response = await axiosClient.get(CATALOG.FAMILIES, { params: { limit: 1000 } })
      return response.data.items || []
    },
    enabled: open,
  })

  const { data: identities = [] } = useQuery({
    queryKey: ['identities'],
    queryFn: async () => {
      const response = await axiosClient.get(CATALOG.IDENTITIES, { params: { limit: 1000 } })
      return response.data.items || []
    },
    enabled: open,
  })

  const enhancedIdentities = useMemo<EnhancedIdentity[]>(() => {
    const familyMap = new Map<number, ProductFamily>()
    ;(families as ProductFamily[]).forEach((family) => familyMap.set(family.product_id, family))
    return (identities as ProductIdentity[]).map((identity) => ({
      ...identity,
      family: familyMap.get(identity.product_id),
    }))
  }, [families, identities])

  const createMutation = useMutation({
    mutationFn: async () => {
      if (!name.trim()) {
        throw new Error('Name is required.')
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
        })
        return
      }

      if (mode === 'part') {
        if (!partParentFamily) throw new Error('Please select a parent product family.')

        const identityPayload: Record<string, unknown> = {
          product_id: partParentFamily.product_id,
          type: 'P',
          identity_name: partIdentityName.trim() || name.trim() || undefined,
        }
        const parsedLci = Number(partLciIndex)
        if (partLciIndex && Number.isFinite(parsedLci) && parsedLci > 0) {
          identityPayload.lci = parsedLci
        }

        const identityResponse = await axiosClient.post(CATALOG.IDENTITIES, identityPayload)
        const createdIdentity = identityResponse.data as ProductIdentity

        if (partLciComponentName.trim()) {
          await axiosClient.post(LOOKUPS.LCI_DEFINITIONS, {
            product_id: partParentFamily.product_id,
            lci_index: createdIdentity.lci,
            component_name: partLciComponentName.trim(),
          })
        }
        return
      }

      // bundle
      const validLines = bundleLines.filter((line) => line.identity && line.quantity > 0)
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
        await axiosClient.post(CATALOG.BUNDLES, {
          parent_identity_id: bundleIdentity.id,
          child_identity_id: line.identity!.id,
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
    setBundleLines((prev) => [...prev, { key: `line-${Date.now()}-${prev.length}`, identity: null, quantity: 1, role: 'Accessory' }])
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
            </TextField>

            <TextField
              label={mode === 'part' ? 'Part Name' : mode === 'bundle' ? 'Bundle Name' : 'Product Name'}
              value={name}
              onChange={(e) => setName(e.target.value)}
              fullWidth
            />

            {mode === 'product' && (
              <Autocomplete
                options={brands as Brand[]}
                value={selectedBrand}
                onChange={(_, value) => setSelectedBrand(value)}
                getOptionLabel={(option) => option.name}
                renderInput={(params) => <TextField {...params} label="Brand (optional)" />}
              />
            )}

            {mode === 'part' && (
              <>
                <Autocomplete
                  options={families as ProductFamily[]}
                  value={partParentFamily}
                  onChange={(_, value) => setPartParentFamily(value)}
                  getOptionLabel={(option) => `${option.product_id} - ${option.base_name}`}
                  renderInput={(params) => <TextField {...params} label="Select Parent Product" />}
                />
                <TextField
                  label="Part Identity Name (optional)"
                  value={partIdentityName}
                  onChange={(e) => setPartIdentityName(e.target.value)}
                  fullWidth
                />
                <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5}>
                  <TextField
                    label="LCI Index (optional)"
                    type="number"
                    value={partLciIndex}
                    onChange={(e) => setPartLciIndex(e.target.value)}
                    fullWidth
                  />
                  <TextField
                    label="LCI Component Name"
                    value={partLciComponentName}
                    onChange={(e) => setPartLciComponentName(e.target.value)}
                    fullWidth
                  />
                </Stack>
              </>
            )}

            {mode === 'bundle' && (
              <>
                <Typography variant="subtitle2">Bundle Items</Typography>
                {bundleLines.map((line) => (
                  <Stack key={line.key} direction={{ xs: 'column', md: 'row' }} spacing={1} alignItems="center">
                    <Autocomplete
                      sx={{ flex: 1 }}
                      options={enhancedIdentities}
                      value={line.identity}
                      onChange={(_, value) => updateBundleLine(line.key, (current) => ({ ...current, identity: value }))}
                      getOptionLabel={(option) =>
                        `${option.generated_upis_h} - ${option.family?.base_name || 'Unknown'}`
                      }
                      renderInput={(params) => <TextField {...params} label="Search item" />}
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

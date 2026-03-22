import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  InputAdornment,
  Paper,
  TextField,
  Typography,
} from '@mui/material'
import { Search } from '@mui/icons-material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import axiosClient from '../../api/axiosClient'
import { CATALOG, LOOKUPS } from '../../api/endpoints'
import { Color, Condition, ProductFamily, ProductIdentity, Variant } from '../../types/inventory'

interface CreateProductDialogProps {
  open: boolean
  onClose: () => void
  onCreated?: (fullSku: string) => void
}

type EnhancedIdentity = ProductIdentity & { family?: ProductFamily }

const normalizeConditionCode = (condition: Condition | null): string | undefined => {
  const code = condition?.code?.trim().toUpperCase()
  if (!code || code === 'U') {
    return undefined
  }
  return code
}

export default function CreateProductDialog({ open, onClose, onCreated }: CreateProductDialogProps) {
  const queryClient = useQueryClient()

  const [selectedExistingParent, setSelectedExistingParent] = useState<EnhancedIdentity | null>(null)
  const [name, setName] = useState('')
  const [selectedColor, setSelectedColor] = useState<Color | null>(null)
  const [selectedCondition, setSelectedCondition] = useState<Condition | null>(null)

  useEffect(() => {
    if (!open) return
    setSelectedExistingParent(null)
    setName('')
    setSelectedColor(null)
    setSelectedCondition(null)
  }, [open])

  const { data: colorsData } = useQuery({
    queryKey: ['colors'],
    queryFn: async () => {
      const response = await axiosClient.get(LOOKUPS.COLORS, { params: { limit: 1000 } })
      return response.data.items || []
    },
    enabled: open,
  })

  const { data: conditionsData } = useQuery({
    queryKey: ['conditions'],
    queryFn: async () => {
      const response = await axiosClient.get(LOOKUPS.CONDITIONS, { params: { limit: 1000 } })
      return response.data.items || []
    },
    enabled: open,
  })

  const { data: identitiesData } = useQuery({
    queryKey: ['identities'],
    queryFn: async () => {
      const response = await axiosClient.get(CATALOG.IDENTITIES, { params: { limit: 1000 } })
      return response.data.items || []
    },
    enabled: open,
  })

  const { data: familiesData } = useQuery({
    queryKey: ['families'],
    queryFn: async () => {
      const response = await axiosClient.get(CATALOG.FAMILIES, { params: { limit: 1000 } })
      return response.data.items || []
    },
    enabled: open,
  })

  const { data: variantsData } = useQuery({
    queryKey: ['variants'],
    queryFn: async () => {
      const response = await axiosClient.get(CATALOG.VARIANTS, { params: { limit: 1000, is_active: true } })
      return response.data.items || []
    },
    enabled: open,
  })

  const enhancedIdentities = useMemo<EnhancedIdentity[]>(() => {
    if (!identitiesData || !familiesData) return []
    const familyMap = new Map<number, ProductFamily>()
    familiesData.forEach((f: ProductFamily) => familyMap.set(f.product_id, f))
    return identitiesData
      .map((i: ProductIdentity) => ({
        ...i,
        family: familyMap.get(i.product_id),
      }))
        .filter((identity: EnhancedIdentity) => identity.type === 'Product' || identity.type === 'K')
  }, [identitiesData, familiesData])

  const existingVariantsForParent = useMemo(() => {
    if (!selectedExistingParent || !variantsData) return []
    return (variantsData as Variant[]).filter((v) => v.identity_id === selectedExistingParent.id)
  }, [selectedExistingParent, variantsData])

  const skuPreview = useMemo(() => {
    if (!selectedExistingParent) {
      return 'Select an existing product first'
    }

    const parts: string[] = [selectedExistingParent.generated_upis_h || '?????']
    if (selectedColor?.code) parts.push(selectedColor.code.trim().toUpperCase())
    const normalizedCondition = normalizeConditionCode(selectedCondition)
    if (normalizedCondition) parts.push(normalizedCondition)
    return parts.join('-')
  }, [selectedExistingParent, selectedColor, selectedCondition])

  const createVariantMutation = useMutation({
    mutationFn: async () => {
      if (!selectedExistingParent) {
        throw new Error('No parent identity selected')
      }

      const originalName = selectedExistingParent.family?.base_name || ''
      const trimmedName = name.trim()
      const nameChanged = trimmedName.length > 0 && trimmedName !== originalName

      if (nameChanged) {
        await axiosClient.put(CATALOG.FAMILY(selectedExistingParent.product_id), {
          base_name: trimmedName,
        })
      }

      const payload: { identity_id: number; color_code?: string; condition_code?: string } = {
        identity_id: selectedExistingParent.id,
      }
      if (selectedColor?.code) {
        payload.color_code = selectedColor.code.trim().toUpperCase()
      }
      const normalizedCondition = normalizeConditionCode(selectedCondition)
      if (normalizedCondition) {
        payload.condition_code = normalizedCondition
      }

      const response = await axiosClient.post(CATALOG.VARIANTS, payload)
      return response.data
    },
    onSuccess: async (data) => {
      await queryClient.invalidateQueries({ queryKey: ['variants'] })
      await queryClient.invalidateQueries({ queryKey: ['families'] })
      await queryClient.invalidateQueries({ queryKey: ['identities'] })
      onClose()
      if (data?.full_sku) onCreated?.(data.full_sku)
    },
    onError: (error: any) => {
      console.error('Failed to create variant:', error)
      alert(error.response?.data?.detail || 'Failed to create variant')
    },
  })

  const isValid = selectedExistingParent !== null

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>Add Variant</DialogTitle>
      <DialogContent>
        <Box sx={{ mt: 2 }}>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            New product creation is disabled in this panel. Use this dialog to add variants to existing products only.
          </Typography>

          <Divider sx={{ mb: 3 }} />

          <Box sx={{ mb: 3 }}>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>
              Select Existing Parent Product *
            </Typography>
            <Autocomplete
              options={enhancedIdentities}
              getOptionLabel={(option: EnhancedIdentity) =>
                `${option.generated_upis_h} - ${option.family?.base_name || 'Unknown'}`
              }
              value={selectedExistingParent}
              onChange={(_, value) => {
                setSelectedExistingParent(value)
                setName(value?.family?.base_name || '')
              }}
              renderInput={(params) => (
                <TextField
                  {...params}
                  placeholder="Search by UPIS-H or product name..."
                  InputProps={{
                    ...params.InputProps,
                    startAdornment: (
                      <InputAdornment position="start">
                        <Search />
                      </InputAdornment>
                    ),
                  }}
                />
              )}
              renderOption={(props, option: EnhancedIdentity) => (
                <li {...props} key={option.id}>
                  <Box>
                    <Typography variant="body2" fontFamily="monospace">
                      {option.generated_upis_h}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {option.family?.base_name || 'Unknown'}
                      {option.family?.brand?.name && ` • ${option.family.brand.name}`}
                    </Typography>
                  </Box>
                </li>
              )}
            />

            {selectedExistingParent && existingVariantsForParent.length > 0 && (
              <Alert severity="info" sx={{ mt: 2 }}>
                <Typography variant="body2">Existing variants for this product:</Typography>
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 1 }}>
                  {existingVariantsForParent.map((v) => (
                    <Chip
                      key={v.id}
                      size="small"
                      label={`${v.color_code || '-'}/${v.condition_code || '-'}`}
                      variant="outlined"
                    />
                  ))}
                </Box>
              </Alert>
            )}
          </Box>

          {selectedExistingParent && (
            <TextField
              fullWidth
              label="Variant Name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Customize the family name if needed..."
              helperText="Leave unchanged to keep the current family name."
              sx={{ mb: 3 }}
            />
          )}

          <Typography variant="subtitle2" sx={{ mb: 2 }}>
            Variant Attributes
          </Typography>

          <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' } }}>
            <Autocomplete
              options={colorsData || []}
              getOptionLabel={(option: Color) => `${option.name} - ${option.code}`}
              value={selectedColor}
              onChange={(_, value) => setSelectedColor(value)}
              renderInput={(params) => <TextField {...params} label="Color" placeholder="Optional" />}
              renderOption={(props, option) => (
                <li {...props} key={option.id}>
                  {option.name} - {option.code}
                </li>
              )}
            />

            <Autocomplete
              options={conditionsData || []}
              getOptionLabel={(option: Condition) => `${option.name} - ${option.code}`}
              value={selectedCondition}
              onChange={(_, value) => setSelectedCondition(value)}
              renderInput={(params) => (
                <TextField
                  {...params}
                  label="Condition"
                  placeholder="Optional (U/Used will be treated as empty)"
                />
              )}
              renderOption={(props, option) => (
                <li {...props} key={option.id}>
                  {option.name} - {option.code}
                </li>
              )}
            />
          </Box>

          <Paper sx={{ p: 2, mt: 3, bgcolor: 'grey.100' }}>
            <Typography variant="subtitle2" color="text.secondary" gutterBottom>
              SKU Preview
            </Typography>
            <Typography variant="h6" fontFamily="monospace">
              {skuPreview}
            </Typography>
          </Paper>
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          onClick={() => createVariantMutation.mutate()}
          disabled={!isValid || createVariantMutation.isPending}
        >
          {createVariantMutation.isPending ? <CircularProgress size={20} /> : 'Create Variant'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

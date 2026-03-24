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
  IconButton,
  Paper,
  Snackbar,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { Add } from '@mui/icons-material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import axiosClient from '../../api/axiosClient'
import { CATALOG, LOOKUPS } from '../../api/endpoints'
import IdentitySearchAutocomplete from '../common/IdentitySearchAutocomplete'
import type { Color, Condition, IdentitySearchResult, Variant } from '../../types/inventory'

interface CreateProductDialogProps {
  open: boolean
  onClose: () => void
  onCreated?: (fullSku: string) => void
}

const normalizeConditionCode = (code: string | undefined): string | undefined => {
  const normalized = (code || '').trim().toUpperCase()
  if (!normalized || normalized === 'U') return undefined
  return normalized
}

export default function CreateProductDialog({ open, onClose, onCreated }: CreateProductDialogProps) {
  const queryClient = useQueryClient()

  const [selectedParent, setSelectedParent] = useState<IdentitySearchResult | null>(null)
  const [variantName, setVariantName] = useState('')

  const [selectedColor, setSelectedColor] = useState<Color | null>(null)
  const [colorNameInput, setColorNameInput] = useState('')
  const [newColorCode, setNewColorCode] = useState('')

  const [selectedCondition, setSelectedCondition] = useState<Condition | null>(null)
  const [conditionNameInput, setConditionNameInput] = useState('')
  const [newConditionCode, setNewConditionCode] = useState('')

  const [snackbar, setSnackbar] = useState<{ open: boolean; msg: string; severity: 'success' | 'error' }>({
    open: false,
    msg: '',
    severity: 'success',
  })

  useEffect(() => {
    if (!open) return
    setSelectedParent(null)
    setVariantName('')
    setSelectedColor(null)
    setColorNameInput('')
    setNewColorCode('')
    setSelectedCondition(null)
    setConditionNameInput('')
    setNewConditionCode('')
  }, [open])

  const { data: colors = [] } = useQuery({
    queryKey: ['colors'],
    queryFn: async () => {
      const response = await axiosClient.get(LOOKUPS.COLORS, { params: { limit: 1000 } })
      return response.data.items || []
    },
    enabled: open,
  })

  const { data: conditions = [] } = useQuery({
    queryKey: ['conditions'],
    queryFn: async () => {
      const response = await axiosClient.get(LOOKUPS.CONDITIONS, { params: { limit: 1000 } })
      return response.data.items || []
    },
    enabled: open,
  })

  const { data: variants = [] } = useQuery({
    queryKey: ['variants'],
    queryFn: async () => {
      const response = await axiosClient.get(CATALOG.VARIANTS, { params: { limit: 1000, is_active: true } })
      return response.data.items || []
    },
    enabled: open,
  })

  const existingVariantsForParent = useMemo(() => {
    if (!selectedParent) return []
    return (variants as Variant[]).filter((variant) => variant.identity_id === selectedParent.id)
  }, [variants, selectedParent])

  const normalizedColorNameInput = colorNameInput.trim().toLowerCase()
  const matchingColorByName = (colors as Color[]).find(
    (color) => color.name.trim().toLowerCase() === normalizedColorNameInput,
  )
  const canCreateColor = normalizedColorNameInput.length > 0 && !matchingColorByName

  const normalizedConditionNameInput = conditionNameInput.trim().toLowerCase()
  const matchingConditionByName = (conditions as Condition[]).find(
    (condition) => condition.name.trim().toLowerCase() === normalizedConditionNameInput,
  )
  const canCreateCondition = normalizedConditionNameInput.length > 0 && !matchingConditionByName

  const createColorMutation = useMutation({
    mutationFn: async () => {
      const name = colorNameInput.trim()
      const code = newColorCode.trim().toUpperCase()
      if (!name || code.length !== 2) {
        throw new Error('Color name is required and color code must be exactly 2 characters.')
      }

      const foundByName = (colors as Color[]).find((c) => c.name.trim().toLowerCase() === name.toLowerCase())
      if (foundByName) {
        if (foundByName.code.toUpperCase() !== code) {
          throw new Error(`Color '${name}' already exists with code '${foundByName.code}'.`)
        }
        return foundByName
      }

      const foundByCode = (colors as Color[]).find((c) => c.code.trim().toUpperCase() === code)
      if (foundByCode) {
        throw new Error(`Color code '${code}' already exists for '${foundByCode.name}'.`)
      }

      const response = await axiosClient.post(LOOKUPS.COLORS, { name, code })
      return response.data as Color
    },
    onSuccess: async (color) => {
      setSelectedColor(color)
      setColorNameInput(color.name)
      setNewColorCode(color.code)
      await queryClient.invalidateQueries({ queryKey: ['colors'] })
      setSnackbar({ open: true, msg: `Color '${color.name}' ready.`, severity: 'success' })
    },
    onError: (error: any) => {
      setSnackbar({ open: true, msg: error?.message || 'Failed to prepare color.', severity: 'error' })
    },
  })

  const createConditionMutation = useMutation({
    mutationFn: async () => {
      const name = conditionNameInput.trim()
      const code = newConditionCode.trim().toUpperCase()
      if (!name || code.length !== 1) {
        throw new Error('Condition name is required and condition code must be exactly 1 character.')
      }

      const foundByName = (conditions as Condition[]).find(
        (c) => c.name.trim().toLowerCase() === name.toLowerCase(),
      )
      if (foundByName) {
        if (foundByName.code.toUpperCase() !== code) {
          throw new Error(`Condition '${name}' already exists with code '${foundByName.code}'.`)
        }
        return foundByName
      }

      const foundByCode = (conditions as Condition[]).find((c) => c.code.trim().toUpperCase() === code)
      if (foundByCode) {
        throw new Error(`Condition code '${code}' already exists for '${foundByCode.name}'.`)
      }

      const response = await axiosClient.post(LOOKUPS.CONDITIONS, { name, code })
      return response.data as Condition
    },
    onSuccess: async (condition) => {
      setSelectedCondition(condition)
      setConditionNameInput(condition.name)
      setNewConditionCode(condition.code)
      await queryClient.invalidateQueries({ queryKey: ['conditions'] })
      setSnackbar({ open: true, msg: `Condition '${condition.name}' ready.`, severity: 'success' })
    },
    onError: (error: any) => {
      setSnackbar({ open: true, msg: error?.message || 'Failed to prepare condition.', severity: 'error' })
    },
  })

  const createVariantMutation = useMutation({
    mutationFn: async () => {
      if (!selectedParent) throw new Error('Please select a parent product/part identity.')

      const payload: Record<string, unknown> = {
        identity_id: selectedParent.id,
        variant_name: variantName.trim() || undefined,
      }
      if (selectedColor?.code) payload.color_code = selectedColor.code.trim().toUpperCase()
      const normalizedCondition = normalizeConditionCode(selectedCondition?.code)
      if (normalizedCondition) payload.condition_code = normalizedCondition

      const response = await axiosClient.post(CATALOG.VARIANTS, payload)
      return response.data
    },
    onSuccess: async (data) => {
      queryClient.setQueryData(['variants'], (previous: Variant[] | undefined) => {
        if (!previous) return previous
        const exists = previous.some((variant) => variant.id === data?.id)
        if (exists) return previous
        return [data as Variant, ...previous]
      })
      await queryClient.invalidateQueries({ queryKey: ['variants'] })
      await queryClient.invalidateQueries({ queryKey: ['identities'] })
      onClose()
      if (data?.full_sku) onCreated?.(data.full_sku)
      setSnackbar({ open: true, msg: 'Variant created successfully.', severity: 'success' })
    },
    onError: (error: any) => {
      const detail = error?.response?.data?.detail || error?.message || 'Failed to create variant.'
      setSnackbar({ open: true, msg: detail, severity: 'error' })
    },
  })

  const skuPreview = useMemo(() => {
    if (!selectedParent) return 'Select parent identity'
    const parts: string[] = [selectedParent.generated_upis_h]
    if (selectedColor?.code) parts.push(selectedColor.code.trim().toUpperCase())
    const normalizedCondition = normalizeConditionCode(selectedCondition?.code)
    if (normalizedCondition) parts.push(normalizedCondition)
    return parts.join('-')
  }, [selectedParent, selectedColor, selectedCondition])

  return (
    <>
      <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
        <DialogTitle>Add Variant</DialogTitle>
        <DialogContent>
          <Box sx={{ mt: 2 }}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Create a variant under an existing Product or Part identity.
            </Typography>

            <Divider sx={{ mb: 2 }} />

            <Typography variant="subtitle2" sx={{ mb: 1 }}>
              Parent Identity (Product / Part)
            </Typography>
            <IdentitySearchAutocomplete
              value={selectedParent}
              onChange={(value) => {
                setSelectedParent(value)
                setVariantName(value?.family_name || '')
              }}
              includeTypes={['Product', 'P']}
              placeholder="Search by UPIS-H, identity name, or product family..."
              width="100%"
            />

            {selectedParent && existingVariantsForParent.length > 0 && (
              <Alert severity="info" sx={{ mt: 1.5 }}>
                <Typography variant="body2">Existing variants for this identity:</Typography>
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 1 }}>
                  {existingVariantsForParent.map((variant) => (
                    <Chip
                      key={variant.id}
                      size="small"
                      variant="outlined"
                      label={`${variant.color_code || '-'}/${variant.condition_code || '-'}`}
                    />
                  ))}
                </Box>
              </Alert>
            )}

            <TextField
              fullWidth
              sx={{ mt: 2 }}
              label="Variant Name"
              placeholder="Optional display name"
              value={variantName}
              onChange={(e) => setVariantName(e.target.value)}
            />

            <Stack spacing={1.25} sx={{ mt: 2 }}>
              <Typography variant="subtitle2">Color</Typography>
              <Stack direction="row" spacing={1} alignItems="center">
                <Autocomplete
                  sx={{ flex: 1 }}
                  options={colors as Color[]}
                  value={selectedColor}
                  inputValue={colorNameInput}
                  onInputChange={(_, value, reason) => {
                    // Keep free-typed input stable when focus leaves the field.
                    if (reason === 'input' || reason === 'clear') {
                      setColorNameInput(value)
                      if (reason === 'input' && selectedColor && selectedColor.name !== value) {
                        setSelectedColor(null)
                      }
                    }
                  }}
                  onChange={(_, value) => {
                    setSelectedColor(value)
                    setColorNameInput(value?.name || '')
                    setNewColorCode(value?.code || '')
                  }}
                  getOptionLabel={(option) => `${option.name} (${option.code})`}
                  renderInput={(params) => <TextField {...params} label="Color Name" />}
                />
                <TextField
                  label="Code"
                  value={newColorCode}
                  onChange={(e) => setNewColorCode(e.target.value.toUpperCase().slice(0, 2))}
                  sx={{ width: 90 }}
                  disabled={!canCreateColor}
                  inputProps={{ maxLength: 2 }}
                />
                <IconButton
                  color="primary"
                  onClick={() => createColorMutation.mutate()}
                  disabled={!canCreateColor || newColorCode.trim().length !== 2 || createColorMutation.isPending}
                >
                  {createColorMutation.isPending ? <CircularProgress size={16} /> : <Add />}
                </IconButton>
              </Stack>

              <Typography variant="subtitle2">Condition</Typography>
              <Stack direction="row" spacing={1} alignItems="center">
                <Autocomplete
                  sx={{ flex: 1 }}
                  options={conditions as Condition[]}
                  value={selectedCondition}
                  inputValue={conditionNameInput}
                  onInputChange={(_, value, reason) => {
                    // Keep free-typed input stable when focus leaves the field.
                    if (reason === 'input' || reason === 'clear') {
                      setConditionNameInput(value)
                      if (reason === 'input' && selectedCondition && selectedCondition.name !== value) {
                        setSelectedCondition(null)
                      }
                    }
                  }}
                  onChange={(_, value) => {
                    setSelectedCondition(value)
                    setConditionNameInput(value?.name || '')
                    setNewConditionCode(value?.code || '')
                  }}
                  getOptionLabel={(option) => `${option.name} (${option.code})`}
                  renderInput={(params) => <TextField {...params} label="Condition Name" />}
                />
                <TextField
                  label="Code"
                  value={newConditionCode}
                  onChange={(e) => setNewConditionCode(e.target.value.toUpperCase().slice(0, 1))}
                  sx={{ width: 90 }}
                  disabled={!canCreateCondition}
                  inputProps={{ maxLength: 1 }}
                />
                <IconButton
                  color="primary"
                  onClick={() => createConditionMutation.mutate()}
                  disabled={
                    !canCreateCondition || newConditionCode.trim().length !== 1 || createConditionMutation.isPending
                  }
                >
                  {createConditionMutation.isPending ? <CircularProgress size={16} /> : <Add />}
                </IconButton>
              </Stack>
            </Stack>

            <Paper sx={{ p: 2, mt: 2, bgcolor: 'grey.100' }}>
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
            disabled={!selectedParent || createVariantMutation.isPending}
          >
            {createVariantMutation.isPending ? <CircularProgress size={18} /> : 'Create Variant'}
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
import React, { useState } from 'react'
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Typography,
  Stack,
  Box,
  RadioGroup,
  FormControlLabel,
  Radio,
  IconButton,
  Alert,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  MenuItem,
  Select,
} from '@mui/material'
import {
  ChangeCircle,
  Handyman,
  Inventory2,
  Category,
  Close,
  CheckCircle,
  Add,
  Remove,
  Delete,
  Search,
} from '@mui/icons-material'
import axiosClient from '../../api/axiosClient'
import { ORBIT } from '../../api/endpoints'
import VariantSearchAutocomplete from '../common/VariantSearchAutocomplete'
import type { BundleComponentInput, ProductNode } from '../../types/inventory'
import type { VariantSearchResult } from '../../types/orders'

interface OrbitConvertTypeModalProps {
  open: boolean
  onClose: () => void
  variant: VariantSearchResult | ProductNode
  isDarkMode?: boolean
  onSuccess: (updatedNode: ProductNode) => void
}

const KIT_ROLES = ['MAIN_UNIT', 'SATELLITE_SPEAKER', 'SUBWOOFER', 'ACCESSORY', 'CABLE_HARNESS']
const BUNDLE_ROLES = ['PRIMARY', 'ACCESSORY', 'SECONDARY', 'BONUS_ITEM']

export default function OrbitConvertTypeModal({
  open,
  onClose,
  variant,
  isDarkMode = true,
  onSuccess,
}: OrbitConvertTypeModalProps) {
  const [targetType, setTargetType] = useState<'K' | 'B' | 'Product'>('K')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [components, setComponents] = useState<BundleComponentInput[]>([])
  const [componentMetaMap, setComponentMetaMap] = useState<Record<number, { sku: string; name: string }>>({})
  const [searchedVariant, setSearchedVariant] = useState<VariantSearchResult | null>(null)

  const variantName =
    'variant_name' in variant
      ? variant.variant_name || ('product_name' in variant ? variant.product_name : variant.full_sku)
      : variant.full_sku

  const variantId = 'id' in variant ? variant.id : (variant as ProductNode).variant_id

  const handleQtyChange = (idx: number, delta: number) => {
    setComponents((prev) => {
      const next = [...prev]
      next[idx].quantity_required = Math.max(1, next[idx].quantity_required + delta)
      return next
    })
  }

  const handleRoleChange = (idx: number, newRole: string) => {
    setComponents((prev) => {
      const next = [...prev]
      next[idx].role = newRole
      return next
    })
  }

  const handleRemove = (idx: number) => {
    setComponents((prev) => prev.filter((_, i) => i !== idx))
  }

  const handleAddFromSearch = (result: VariantSearchResult | null) => {
    if (!result) return
    if (result.id === variantId) {
      setError('Cannot add the product itself as a child component.')
      setSearchedVariant(null)
      return
    }
    if (components.some((c) => c.child_variant_id === result.id)) {
      setError(`Component ${result.full_sku} already added.`)
      setSearchedVariant(null)
      return
    }

    setComponentMetaMap((prev) => ({
      ...prev,
      [result.id]: { sku: result.full_sku, name: result.variant_name || result.product_name || result.full_sku },
    }))

    setComponents((prev) => [
      ...prev,
      {
        child_variant_id: result.id,
        quantity_required: 1,
        role: targetType === 'K' ? 'SATELLITE_SPEAKER' : 'ACCESSORY',
      },
    ])
    setSearchedVariant(null)
    setError(null)
  }

  const handleSubmit = async () => {
    setLoading(true)
    setError(null)
    try {
      const resp = await axiosClient.post<ProductNode>(ORBIT.CONVERT_TYPE, {
        variant_id: variantId,
        target_type: targetType,
        components: targetType !== 'Product' ? components : [],
      })
      onSuccess(resp.data)
      onClose()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to convert product type')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="md"
      fullWidth
      PaperProps={{
        sx: {
          bgcolor: isDarkMode ? '#0f172a' : '#ffffff',
          color: isDarkMode ? '#f8fafc' : '#0f172a',
          border: isDarkMode ? '1px solid rgba(255, 255, 255, 0.12)' : '1px solid #cbd5e1',
          borderRadius: 3,
        },
      }}
    >
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Stack direction="row" alignItems="center" spacing={1}>
          <ChangeCircle sx={{ color: '#38bdf8' }} />
          <Typography variant="h6" sx={{ fontWeight: 600 }}>
            Convert Product Classification
          </Typography>
        </Stack>
        <IconButton onClick={onClose} sx={{ color: isDarkMode ? '#94a3b8' : '#64748b' }}>
          <Close />
        </IconButton>
      </DialogTitle>

      <DialogContent dividers sx={{ borderColor: isDarkMode ? 'rgba(255, 255, 255, 0.08)' : '#e2e8f0' }}>
        {error && (
          <Alert severity="error" sx={{ mb: 2, bgcolor: 'rgba(127, 29, 29, 0.85)', color: '#ffffff' }}>
            {error}
          </Alert>
        )}

        {/* Current Product Info Banner */}
        <Box
          sx={{
            p: 2,
            mb: 2.5,
            bgcolor: isDarkMode ? 'rgba(255, 255, 255, 0.03)' : '#f8fafc',
            borderRadius: 2,
            border: isDarkMode ? '1px solid rgba(255, 255, 255, 0.08)' : '1px solid #e2e8f0',
          }}
        >
          <Typography variant="caption" sx={{ color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.8 }}>
            Selected Product for Conversion
          </Typography>
          <Typography variant="body1" sx={{ fontWeight: 700, color: isDarkMode ? '#f8fafc' : '#0f172a' }}>
            {variantName}
          </Typography>
          <Typography variant="caption" sx={{ color: '#38bdf8', fontFamily: 'monospace', fontWeight: 600 }}>
            SKU: {variant.full_sku}
          </Typography>
        </Box>

        {/* Target Classification Selection */}
        <Box sx={{ mb: 3 }}>
          <Typography variant="subtitle2" sx={{ color: '#38bdf8', fontWeight: 600, mb: 1 }}>
            Select Target Classification (UPIS System)
          </Typography>
          <RadioGroup value={targetType} onChange={(e) => setTargetType(e.target.value as any)}>
            <FormControlLabel
              value="K"
              control={<Radio sx={{ color: '#818cf8', '&.Mui-checked': { color: '#818cf8' } }} />}
              label={
                <Box sx={{ py: 0.5 }}>
                  <Typography variant="body2" sx={{ fontWeight: 600, color: '#818cf8' }}>
                    🧰 Predefined Kit (Type K) — e.g. <code>{variant.full_sku.split('-')[0]}-K</code>
                  </Typography>
                  <Typography variant="caption" sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', display: 'block' }}>
                    Single sellable manufacturer kit or internally pre-assembled fixed unit (e.g. Companion 3 System).
                    Warehouse picks 1 Kit SKU.
                  </Typography>
                </Box>
              }
            />
            <FormControlLabel
              value="B"
              control={<Radio sx={{ color: '#f59e0b', '&.Mui-checked': { color: '#f59e0b' } }} />}
              label={
                <Box sx={{ py: 0.5 }}>
                  <Typography variant="body2" sx={{ fontWeight: 600, color: '#f59e0b' }}>
                    📦 USAV Bundle (Type B) — e.g. <code>{variant.full_sku.split('-')[0]}-B</code>
                  </Typography>
                  <Typography variant="caption" sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', display: 'block' }}>
                    Logical grouping assembled dynamically at order time. Stock derived from component inventory.
                  </Typography>
                </Box>
              }
            />
            <FormControlLabel
              value="Product"
              control={<Radio sx={{ color: '#38bdf8', '&.Mui-checked': { color: '#38bdf8' } }} />}
              label={
                <Box sx={{ py: 0.5 }}>
                  <Typography variant="body2" sx={{ fontWeight: 600, color: '#38bdf8' }}>
                    🏷️ Base Product (Standard Unit) — e.g. <code>{variant.full_sku.split('-')[0]}</code>
                  </Typography>
                  <Typography variant="caption" sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', display: 'block' }}>
                    Standard standalone physical product.
                  </Typography>
                </Box>
              }
            />
          </RadioGroup>
        </Box>

        {/* Component assignment if converting to Kit or Bundle */}
        {targetType !== 'Product' && (
          <Box>
            <Box
              sx={{
                p: 2,
                mb: 2,
                bgcolor: isDarkMode ? 'rgba(56, 189, 248, 0.05)' : '#f0f9ff',
                borderRadius: 2,
                border: isDarkMode ? '1px solid rgba(56, 189, 248, 0.2)' : '1px solid #bae6fd',
              }}
            >
              <Typography variant="subtitle2" sx={{ color: '#0284c7', fontWeight: 600, mb: 1, display: 'flex', alignItems: 'center', gap: 1 }}>
                <Search fontSize="small" /> Add Child Components for this {targetType === 'K' ? 'Kit' : 'Bundle'}
              </Typography>
              <VariantSearchAutocomplete
                value={searchedVariant}
                onChange={handleAddFromSearch}
                placeholder="Search child components (e.g. speakers, subwoofer, power supply)..."
                width="100%"
                isDarkMode={isDarkMode}
              />
            </Box>

            {components.length > 0 && (
              <TableContainer
                component={Paper}
                sx={{
                  bgcolor: isDarkMode ? 'rgba(255, 255, 255, 0.02)' : '#ffffff',
                  border: isDarkMode ? '1px solid rgba(255, 255, 255, 0.06)' : '1px solid #e2e8f0',
                }}
              >
                <Table size="small">
                  <TableHead>
                    <TableRow sx={{ borderBottom: isDarkMode ? '1px solid rgba(255, 255, 255, 0.1)' : '1px solid #cbd5e1' }}>
                      <TableCell sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', fontWeight: 600 }}>Component SKU</TableCell>
                      <TableCell sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', fontWeight: 600 }}>Quantity</TableCell>
                      <TableCell sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', fontWeight: 600 }}>Role</TableCell>
                      <TableCell sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', width: 40 }}></TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {components.map((comp, idx) => {
                      const meta = componentMetaMap[comp.child_variant_id] || { sku: `#${comp.child_variant_id}`, name: 'Product' }
                      return (
                        <TableRow key={comp.child_variant_id}>
                          <TableCell sx={{ color: isDarkMode ? '#f8fafc' : '#0f172a' }}>
                            <Typography variant="body2" sx={{ fontWeight: 600, fontSize: 12 }}>
                              {meta.name}
                            </Typography>
                            <Typography variant="caption" sx={{ color: '#38bdf8', fontFamily: 'monospace' }}>
                              {meta.sku}
                            </Typography>
                          </TableCell>

                          <TableCell>
                            <Stack direction="row" alignItems="center" spacing={1}>
                              <IconButton size="small" onClick={() => handleQtyChange(idx, -1)} sx={{ color: isDarkMode ? '#94a3b8' : '#64748b' }}>
                                <Remove fontSize="small" />
                              </IconButton>
                              <Typography variant="body2" sx={{ fontWeight: 600, minWidth: 20, textAlign: 'center' }}>
                                {comp.quantity_required}
                              </Typography>
                              <IconButton size="small" onClick={() => handleQtyChange(idx, 1)} sx={{ color: isDarkMode ? '#94a3b8' : '#64748b' }}>
                                <Add fontSize="small" />
                              </IconButton>
                            </Stack>
                          </TableCell>

                          <TableCell>
                            <Select
                              size="small"
                              value={comp.role}
                              onChange={(e) => handleRoleChange(idx, e.target.value)}
                              sx={{
                                color: isDarkMode ? '#ffffff' : '#0f172a',
                                bgcolor: isDarkMode ? 'rgba(255, 255, 255, 0.05)' : '#f8fafc',
                                fontSize: 12,
                                '& .MuiSelect-select': { py: 0.5 },
                              }}
                            >
                              {(targetType === 'K' ? KIT_ROLES : BUNDLE_ROLES).map((role) => (
                                <MenuItem key={role} value={role} sx={{ fontSize: 12 }}>
                                  {role}
                                </MenuItem>
                              ))}
                            </Select>
                          </TableCell>

                          <TableCell>
                            <IconButton size="small" onClick={() => handleRemove(idx)} sx={{ color: '#ef4444' }}>
                              <Delete fontSize="small" />
                            </IconButton>
                          </TableCell>
                        </TableRow>
                      )
                    })}
                  </TableBody>
                </Table>
              </TableContainer>
            )}
          </Box>
        )}
      </DialogContent>

      <DialogActions sx={{ p: 2, px: 3 }}>
        <Button onClick={onClose} sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', textTransform: 'none' }}>
          Cancel
        </Button>
        <Button
          variant="contained"
          onClick={handleSubmit}
          disabled={loading}
          startIcon={<CheckCircle />}
          sx={{
            bgcolor: targetType === 'K' ? '#6366f1' : targetType === 'B' ? '#d97706' : '#0284c7',
            color: '#ffffff',
            textTransform: 'none',
            fontWeight: 600,
            '&:hover': {
              bgcolor: targetType === 'K' ? '#4f46e5' : targetType === 'B' ? '#b45309' : '#0369a1',
            },
          }}
        >
          {loading ? 'Converting...' : `Convert to ${targetType === 'K' ? 'Kit (K)' : targetType === 'B' ? 'Bundle (B)' : 'Base Product'}`}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

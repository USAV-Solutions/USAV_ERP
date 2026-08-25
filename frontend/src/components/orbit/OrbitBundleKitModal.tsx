import React, { useState } from 'react'
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Typography,
  Stack,
  Box,
  RadioGroup,
  FormControlLabel,
  Radio,
  Chip,
  IconButton,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  MenuItem,
  Select,
  Alert,
  Tooltip,
} from '@mui/material'
import {
  Inventory2,
  Handyman,
  Add,
  Remove,
  Delete,
  Close,
  CheckCircle,
  Search,
} from '@mui/icons-material'
import axiosClient from '../../api/axiosClient'
import { ORBIT } from '../../api/endpoints'
import VariantSearchAutocomplete from '../common/VariantSearchAutocomplete'
import type { BundleComponentInput, OrbitCreateBundleKitRequest, ProductNode } from '../../types/inventory'
import type { VariantSearchResult } from '../../types/orders'

interface OrbitBundleKitModalProps {
  open: boolean
  onClose: () => void
  selectedNodes: Array<{ variant_id: number; full_sku: string; variant_name?: string | null }>
  isDarkMode?: boolean
  onSuccess: (createdNode: ProductNode) => void
}

const KIT_ROLES = ['MAIN_UNIT', 'SATELLITE_SPEAKER', 'SUBWOOFER', 'ACCESSORY', 'CABLE_HARNESS']
const BUNDLE_ROLES = ['PRIMARY', 'ACCESSORY', 'SECONDARY', 'BONUS_ITEM']

export default function OrbitBundleKitModal({
  open,
  onClose,
  selectedNodes,
  isDarkMode = true,
  onSuccess,
}: OrbitBundleKitModalProps) {
  const [creationType, setCreationType] = useState<'K' | 'B'>('B')
  const [name, setName] = useState('')
  const [targetPrice, setTargetPrice] = useState<string>('')
  const [productId, setProductId] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Track component item metadata (name & SKU) for display
  const [componentMetaMap, setComponentMetaMap] = useState<Record<number, { sku: string; name: string }>>(() => {
    const map: Record<number, { sku: string; name: string }> = {}
    selectedNodes.forEach((n) => {
      map[n.variant_id] = { sku: n.full_sku, name: n.variant_name || n.full_sku }
    })
    return map
  })

  const [components, setComponents] = useState<BundleComponentInput[]>(() =>
    selectedNodes.map((n, idx) => ({
      child_variant_id: n.variant_id,
      quantity_required: 1,
      role: idx === 0 ? (creationType === 'K' ? 'MAIN_UNIT' : 'PRIMARY') : 'ACCESSORY',
    }))
  )

  // Autocomplete search state for adding new items from catalog
  const [searchedVariant, setSearchedVariant] = useState<VariantSearchResult | null>(null)

  // Auto-fill default title when opening or changing type
  React.useEffect(() => {
    if (selectedNodes.length > 0 && !name) {
      const mainName = selectedNodes[0].variant_name || selectedNodes[0].full_sku
      const typeLabel = creationType === 'K' ? 'System Kit' : 'Bundle with Accessories'
      setName(`${mainName} - ${typeLabel}`)
    }
  }, [selectedNodes, creationType, name])

  // Update roles when switching type
  const handleTypeChange = (newType: 'K' | 'B') => {
    setCreationType(newType)
    setComponents((prev) =>
      prev.map((c, idx) => ({
        ...c,
        role: idx === 0 ? (newType === 'K' ? 'MAIN_UNIT' : 'PRIMARY') : 'ACCESSORY',
      }))
    )
  }

  const handleQtyChange = (idx: number, delta: number) => {
    setComponents((prev) => {
      const next = [...prev]
      const current = next[idx].quantity_required
      next[idx].quantity_required = Math.max(1, current + delta)
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

  // Handle adding an item from catalog search
  const handleAddFromSearch = (result: VariantSearchResult | null) => {
    if (!result) return
    // Check if already in components
    if (components.some((c) => c.child_variant_id === result.id)) {
      setError(`Variant ${result.full_sku} is already added. Increase its quantity instead.`)
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
        role: creationType === 'K' ? 'ACCESSORY' : 'ACCESSORY',
      },
    ])
    setSearchedVariant(null)
    setError(null)
  }

  const handleSubmit = async () => {
    if (!name.trim()) {
      setError('Please provide a bundle/kit name.')
      return
    }
    if (components.length === 0) {
      setError('At least one component must be included.')
      return
    }

    setLoading(true)
    setError(null)
    try {
      const payload: OrbitCreateBundleKitRequest = {
        type: creationType,
        name: name.trim(),
        product_id: productId.trim() ? parseInt(productId.trim(), 10) : null,
        components,
        target_price: targetPrice.trim() ? parseFloat(targetPrice.trim()) : null,
      }
      const resp = await axiosClient.post<ProductNode>(ORBIT.CREATE_BUNDLE_KIT, payload)
      onSuccess(resp.data)
      onClose()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to create bundle/kit')
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
          {creationType === 'K' ? <Handyman sx={{ color: '#818cf8' }} /> : <Inventory2 sx={{ color: '#f59e0b' }} />}
          <Typography variant="h6" sx={{ fontWeight: 600 }}>
            {creationType === 'K' ? 'Form Predefined Kit (Type K)' : 'Form USAV Bundle (Type B)'}
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

        {/* Formation Type Selector */}
        <Box
          sx={{
            p: 2,
            mb: 3,
            bgcolor: isDarkMode ? 'rgba(255, 255, 255, 0.03)' : '#f8fafc',
            borderRadius: 2,
            border: isDarkMode ? '1px solid rgba(255, 255, 255, 0.08)' : '1px solid #e2e8f0',
          }}
        >
          <Typography variant="subtitle2" sx={{ color: '#38bdf8', fontWeight: 600, mb: 1 }}>
            Select Classification (USAV Product Identification Specification)
          </Typography>
          <RadioGroup row value={creationType} onChange={(e) => handleTypeChange(e.target.value as 'K' | 'B')}>
            <FormControlLabel
              value="B"
              control={<Radio sx={{ color: '#f59e0b', '&.Mui-checked': { color: '#f59e0b' } }} />}
              label={
                <Box>
                  <Typography variant="body2" sx={{ fontWeight: 600, color: '#f59e0b' }}>
                    📦 USAV Bundle (Type B)
                  </Typography>
                  <Typography variant="caption" sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', display: 'block' }}>
                    Logical grouping assembled dynamically at order time. Stock derived from components.
                  </Typography>
                </Box>
              }
              sx={{ flex: 1, mr: 2 }}
            />
            <FormControlLabel
              value="K"
              control={<Radio sx={{ color: '#818cf8', '&.Mui-checked': { color: '#818cf8' } }} />}
              label={
                <Box>
                  <Typography variant="body2" sx={{ fontWeight: 600, color: '#818cf8' }}>
                    🧰 Predefined Kit (Type K)
                  </Typography>
                  <Typography variant="caption" sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', display: 'block' }}>
                    Single sellable manufacturer kit or internally pre-assembled fixed unit. Warehouse picks 1 SKU.
                  </Typography>
                </Box>
              }
              sx={{ flex: 1 }}
            />
          </RadioGroup>
        </Box>

        {/* Inputs */}
        <Stack spacing={2} sx={{ mb: 3 }}>
          <TextField
            fullWidth
            label="Bundle / Kit Display Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            size="small"
            InputLabelProps={{ sx: { color: isDarkMode ? '#94a3b8' : '#64748b' } }}
            InputProps={{
              sx: {
                color: isDarkMode ? '#ffffff' : '#0f172a',
                bgcolor: isDarkMode ? 'rgba(255, 255, 255, 0.04)' : '#f8fafc',
              },
            }}
          />

          <Stack direction="row" spacing={2}>
            <TextField
              label="ECWID Product ID Namespace (Optional)"
              placeholder="e.g. 02391"
              value={productId}
              onChange={(e) => setProductId(e.target.value)}
              size="small"
              sx={{ flex: 1 }}
              InputLabelProps={{ sx: { color: isDarkMode ? '#94a3b8' : '#64748b' } }}
              InputProps={{
                sx: {
                  color: isDarkMode ? '#ffffff' : '#0f172a',
                  bgcolor: isDarkMode ? 'rgba(255, 255, 255, 0.04)' : '#f8fafc',
                },
              }}
              helperText="Auto-generates next available 5-digit ID if empty"
            />
            <TextField
              label="Target Selling Price ($)"
              placeholder="e.g. 349.99"
              value={targetPrice}
              onChange={(e) => setTargetPrice(e.target.value)}
              size="small"
              sx={{ flex: 1 }}
              InputLabelProps={{ sx: { color: isDarkMode ? '#94a3b8' : '#64748b' } }}
              InputProps={{
                sx: {
                  color: isDarkMode ? '#ffffff' : '#0f172a',
                  bgcolor: isDarkMode ? 'rgba(255, 255, 255, 0.04)' : '#f8fafc',
                },
              }}
            />
          </Stack>
        </Stack>

        {/* ➕ Add Component Search Bar */}
        <Box
          sx={{
            p: 2,
            mb: 2.5,
            bgcolor: isDarkMode ? 'rgba(56, 189, 248, 0.05)' : '#f0f9ff',
            borderRadius: 2,
            border: isDarkMode ? '1px solid rgba(56, 189, 248, 0.2)' : '1px solid #bae6fd',
          }}
        >
          <Typography variant="subtitle2" sx={{ color: '#0284c7', fontWeight: 600, mb: 1, display: 'flex', alignItems: 'center', gap: 1 }}>
            <Search fontSize="small" /> Add Additional Components from Catalog
          </Typography>
          <VariantSearchAutocomplete
            value={searchedVariant}
            onChange={handleAddFromSearch}
            placeholder="Search by SKU, product name, or UPIS to add component..."
            width="100%"
            isDarkMode={isDarkMode}
          />
        </Box>

        {/* Component Recipes Table */}
        <Typography variant="subtitle2" sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', fontWeight: 600, mb: 1 }}>
          Included Components & Roles ({components.length})
        </Typography>

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
                <TableCell sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', fontWeight: 600 }}>Product / SKU</TableCell>
                <TableCell sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', fontWeight: 600 }}>Quantity</TableCell>
                <TableCell sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', fontWeight: 600 }}>
                  Role in {creationType === 'K' ? 'Kit' : 'Bundle'}
                </TableCell>
                <TableCell sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', width: 40 }}></TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {components.map((comp, idx) => {
                const meta = componentMetaMap[comp.child_variant_id] || { sku: `#${comp.child_variant_id}`, name: 'Product' }
                return (
                  <TableRow
                    key={comp.child_variant_id}
                    sx={{ borderBottom: isDarkMode ? '1px solid rgba(255, 255, 255, 0.04)' : '1px solid #f1f5f9' }}
                  >
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
                        <IconButton
                          size="small"
                          onClick={() => handleQtyChange(idx, -1)}
                          sx={{ color: isDarkMode ? '#94a3b8' : '#64748b' }}
                        >
                          <Remove fontSize="small" />
                        </IconButton>
                        <Typography
                          variant="body2"
                          sx={{
                            fontWeight: 600,
                            color: isDarkMode ? '#f8fafc' : '#0f172a',
                            minWidth: 20,
                            textAlign: 'center',
                          }}
                        >
                          {comp.quantity_required}
                        </Typography>
                        <IconButton
                          size="small"
                          onClick={() => handleQtyChange(idx, 1)}
                          sx={{ color: isDarkMode ? '#94a3b8' : '#64748b' }}
                        >
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
                        {(creationType === 'K' ? KIT_ROLES : BUNDLE_ROLES).map((role) => (
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
      </DialogContent>

      <DialogActions sx={{ p: 2, px: 3 }}>
        <Button onClick={onClose} sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', textTransform: 'none' }}>
          Cancel
        </Button>
        <Button
          variant="contained"
          onClick={handleSubmit}
          disabled={loading || components.length === 0}
          startIcon={<CheckCircle />}
          sx={{
            bgcolor: creationType === 'K' ? '#6366f1' : '#d97706',
            color: '#ffffff',
            textTransform: 'none',
            fontWeight: 600,
            '&:hover': { bgcolor: creationType === 'K' ? '#4f46e5' : '#b45309' },
          }}
        >
          {loading ? 'Creating...' : `Create ${creationType === 'K' ? 'Kit (K)' : 'Bundle (B)'}`}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

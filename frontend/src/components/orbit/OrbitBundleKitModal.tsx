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
} from '@mui/material'
import {
  Inventory2,
  Handyman,
  Add,
  Remove,
  Delete,
  Close,
  CheckCircle,
} from '@mui/icons-material'
import axiosClient from '../../api/axiosClient'
import { ORBIT } from '../../api/endpoints'
import type { BundleComponentInput, OrbitCreateBundleKitRequest, ProductNode } from '../../types/inventory'

interface OrbitBundleKitModalProps {
  open: boolean
  onClose: () => void
  selectedNodes: Array<{ variant_id: number; full_sku: string; variant_name?: string | null }>
  onSuccess: (createdNode: ProductNode) => void
}

const KIT_ROLES = ['MAIN_UNIT', 'SATELLITE_SPEAKER', 'SUBWOOFER', 'ACCESSORY', 'CABLE_HARNESS']
const BUNDLE_ROLES = ['PRIMARY', 'ACCESSORY', 'SECONDARY', 'BONUS_ITEM']

export default function OrbitBundleKitModal({
  open,
  onClose,
  selectedNodes,
  onSuccess,
}: OrbitBundleKitModalProps) {
  const [creationType, setCreationType] = useState<'K' | 'B'>('B')
  const [name, setName] = useState('')
  const [targetPrice, setTargetPrice] = useState<string>('')
  const [productId, setProductId] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [components, setComponents] = useState<BundleComponentInput[]>(() =>
    selectedNodes.map((n, idx) => ({
      child_variant_id: n.variant_id,
      quantity_required: 1,
      role: idx === 0 ? (creationType === 'K' ? 'MAIN_UNIT' : 'PRIMARY') : 'ACCESSORY',
    }))
  )

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
          bgcolor: '#0f172a',
          color: '#f8fafc',
          border: '1px solid rgba(255, 255, 255, 0.12)',
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
        <IconButton onClick={onClose} sx={{ color: '#94a3b8' }}>
          <Close />
        </IconButton>
      </DialogTitle>

      <DialogContent dividers sx={{ borderColor: 'rgba(255, 255, 255, 0.08)' }}>
        {error && (
          <Alert severity="error" sx={{ mb: 2, bgcolor: 'rgba(127, 29, 29, 0.85)', color: '#ffffff' }}>
            {error}
          </Alert>
        )}

        {/* Formation Type Selector */}
        <Box sx={{ p: 2, mb: 3, bgcolor: 'rgba(255, 255, 255, 0.03)', borderRadius: 2, border: '1px solid rgba(255, 255, 255, 0.08)' }}>
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
                  <Typography variant="caption" sx={{ color: '#94a3b8', display: 'block' }}>
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
                  <Typography variant="caption" sx={{ color: '#94a3b8', display: 'block' }}>
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
            InputLabelProps={{ sx: { color: '#94a3b8' } }}
            InputProps={{ sx: { color: '#ffffff', bgcolor: 'rgba(255, 255, 255, 0.04)' } }}
          />

          <Stack direction="row" spacing={2}>
            <TextField
              label="ECWID Product ID Namespace (Optional)"
              placeholder="e.g. 02391"
              value={productId}
              onChange={(e) => setProductId(e.target.value)}
              size="small"
              sx={{ flex: 1 }}
              InputLabelProps={{ sx: { color: '#94a3b8' } }}
              InputProps={{ sx: { color: '#ffffff', bgcolor: 'rgba(255, 255, 255, 0.04)' } }}
              helperText="Auto-generates next available 5-digit ID if empty"
            />
            <TextField
              label="Target Selling Price ($)"
              placeholder="e.g. 349.99"
              value={targetPrice}
              onChange={(e) => setTargetPrice(e.target.value)}
              size="small"
              sx={{ flex: 1 }}
              InputLabelProps={{ sx: { color: '#94a3b8' } }}
              InputProps={{ sx: { color: '#ffffff', bgcolor: 'rgba(255, 255, 255, 0.04)' } }}
            />
          </Stack>
        </Stack>

        {/* Component Recipes Table */}
        <Typography variant="subtitle2" sx={{ color: '#94a3b8', fontWeight: 600, mb: 1 }}>
          Selected Components & Roles ({components.length})
        </Typography>

        <TableContainer component={Paper} sx={{ bgcolor: 'rgba(255, 255, 255, 0.02)', border: '1px solid rgba(255, 255, 255, 0.06)' }}>
          <Table size="small">
            <TableHead>
              <TableRow sx={{ borderBottom: '1px solid rgba(255, 255, 255, 0.1)' }}>
                <TableCell sx={{ color: '#94a3b8', fontWeight: 600 }}>Product / SKU</TableCell>
                <TableCell sx={{ color: '#94a3b8', fontWeight: 600 }}>Quantity</TableCell>
                <TableCell sx={{ color: '#94a3b8', fontWeight: 600 }}>Role in {creationType === 'K' ? 'Kit' : 'Bundle'}</TableCell>
                <TableCell sx={{ color: '#94a3b8', width: 40 }}></TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {components.map((comp, idx) => {
                const nodeInfo = selectedNodes.find((n) => n.variant_id === comp.child_variant_id)
                return (
                  <TableRow key={comp.child_variant_id} sx={{ borderBottom: '1px solid rgba(255, 255, 255, 0.04)' }}>
                    <TableCell sx={{ color: '#f8fafc' }}>
                      <Typography variant="body2" sx={{ fontWeight: 600, fontSize: 12 }}>
                        {nodeInfo?.variant_name || nodeInfo?.full_sku}
                      </Typography>
                      <Typography variant="caption" sx={{ color: '#38bdf8', fontFamily: 'monospace' }}>
                        {nodeInfo?.full_sku}
                      </Typography>
                    </TableCell>

                    <TableCell>
                      <Stack direction="row" alignItems="center" spacing={1}>
                        <IconButton size="small" onClick={() => handleQtyChange(idx, -1)} sx={{ color: '#94a3b8' }}>
                          <Remove fontSize="small" />
                        </IconButton>
                        <Typography variant="body2" sx={{ fontWeight: 600, color: '#f8fafc', minWidth: 20, textAlign: 'center' }}>
                          {comp.quantity_required}
                        </Typography>
                        <IconButton size="small" onClick={() => handleQtyChange(idx, 1)} sx={{ color: '#94a3b8' }}>
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
                          color: '#ffffff',
                          bgcolor: 'rgba(255, 255, 255, 0.05)',
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
        <Button onClick={onClose} sx={{ color: '#94a3b8', textTransform: 'none' }}>
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

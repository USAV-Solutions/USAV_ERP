import React, { useState, useMemo } from 'react'
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
  MenuItem,
  Select,
  FormControl,
  InputLabel,
  Chip,
  IconButton,
  Alert,
} from '@mui/material'
import { Palette, Close, CheckCircle } from '@mui/icons-material'
import axiosClient from '../../api/axiosClient'
import { ORBIT } from '../../api/endpoints'
import type { OrbitCreateVariantRequest, ProductNode } from '../../types/inventory'

interface OrbitVariantModalProps {
  open: boolean
  onClose: () => void
  sourceVariant: {
    id: number
    full_sku: string
    variant_name?: string | null
    generated_upis_h?: string | null
  }
  onSuccess: (newVariant: ProductNode) => void
}

const COLOR_OPTIONS = [
  { code: 'BK', name: 'Black', hex: '#000000' },
  { code: 'WY', name: 'White', hex: '#f8fafc' },
  { code: 'SV', name: 'Silver', hex: '#94a3b8' },
  { code: 'GY', name: 'Gray', hex: '#64748b' },
  { code: 'BL', name: 'Blue', hex: '#3b82f6' },
  { code: 'RD', name: 'Red', hex: '#ef4444' },
  { code: 'BG', name: 'Beige', hex: '#d4b996' },
  { code: 'GD', name: 'Gold', hex: '#eab308' },
]

const CONDITION_OPTIONS = [
  { code: 'U', name: 'Used (Default)', desc: 'Standard pre-owned condition' },
  { code: 'N', name: 'New', desc: 'Brand new, sealed in original box' },
  { code: 'R', name: 'Refurbished / Repair', desc: 'USAV tested & restored' },
]

export default function OrbitVariantModal({
  open,
  onClose,
  sourceVariant,
  onSuccess,
}: OrbitVariantModalProps) {
  const [colorCode, setColorCode] = useState('SV')
  const [conditionCode, setConditionCode] = useState('U')
  const [variantName, setVariantName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Extract base UPIS-H
  const baseUpisH = useMemo(() => {
    if (sourceVariant.generated_upis_h) return sourceVariant.generated_upis_h
    const parts = sourceVariant.full_sku.split('-')
    if (parts.length >= 3) {
      return parts.slice(0, 3).join('-')
    }
    return parts[0]
  }, [sourceVariant])

  // Computed Full SKU preview (UPIS Layer 2)
  const computedSku = useMemo(() => {
    return `${baseUpisH}-${colorCode}-${conditionCode}`
  }, [baseUpisH, colorCode, conditionCode])

  const handleSubmit = async () => {
    setLoading(true)
    setError(null)
    try {
      const payload: OrbitCreateVariantRequest = {
        source_variant_id: sourceVariant.id,
        color_code: colorCode,
        condition_code: conditionCode,
        variant_name: variantName.trim() || undefined,
      }
      const resp = await axiosClient.post<ProductNode>(ORBIT.CREATE_VARIANT, payload)
      onSuccess(resp.data)
      onClose()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to create product variant')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="sm"
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
          <Palette sx={{ color: '#38bdf8' }} />
          <Typography variant="h6" sx={{ fontWeight: 600 }}>
            Create Product Variant (UML Layer 2)
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

        {/* Base Identity Card */}
        <Box sx={{ p: 2, mb: 2.5, bgcolor: 'rgba(255, 255, 255, 0.03)', borderRadius: 2, border: '1px solid rgba(255, 255, 255, 0.06)' }}>
          <Typography variant="caption" sx={{ color: '#94a3b8', display: 'block' }}>
            Parent Product Identity (Immutable UPIS-H):
          </Typography>
          <Typography variant="body2" sx={{ fontWeight: 600, color: '#38bdf8', fontFamily: 'monospace' }}>
            {baseUpisH}
          </Typography>
          <Typography variant="body2" sx={{ color: '#cbd5e1', mt: 0.5, fontSize: 12 }}>
            {sourceVariant.variant_name || sourceVariant.full_sku}
          </Typography>
        </Box>

        {/* Color & Condition Selection */}
        <Stack spacing={2.5}>
          <FormControl fullWidth size="small">
            <InputLabel sx={{ color: '#94a3b8' }}>Color Code (2-char)</InputLabel>
            <Select
              value={colorCode}
              label="Color Code (2-char)"
              onChange={(e) => setColorCode(e.target.value)}
              sx={{
                color: '#ffffff',
                bgcolor: 'rgba(255, 255, 255, 0.04)',
                '& .MuiSvgIcon-root': { color: '#94a3b8' },
              }}
            >
              {COLOR_OPTIONS.map((c) => (
                <MenuItem key={c.code} value={c.code}>
                  <Stack direction="row" alignItems="center" spacing={1.5}>
                    <Box sx={{ width: 14, height: 14, borderRadius: '50%', bgcolor: c.hex, border: '1px solid #64748b' }} />
                    <Typography variant="body2">
                      {c.name} (<code>{c.code}</code>)
                    </Typography>
                  </Stack>
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <FormControl fullWidth size="small">
            <InputLabel sx={{ color: '#94a3b8' }}>Condition Code</InputLabel>
            <Select
              value={conditionCode}
              label="Condition Code"
              onChange={(e) => setConditionCode(e.target.value)}
              sx={{
                color: '#ffffff',
                bgcolor: 'rgba(255, 255, 255, 0.04)',
                '& .MuiSvgIcon-root': { color: '#94a3b8' },
              }}
            >
              {CONDITION_OPTIONS.map((cond) => (
                <MenuItem key={cond.code} value={cond.code}>
                  <Box>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                      {cond.name} (<code>{cond.code}</code>)
                    </Typography>
                    <Typography variant="caption" sx={{ color: '#94a3b8' }}>
                      {cond.desc}
                    </Typography>
                  </Box>
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <TextField
            fullWidth
            label="Variant Display Name (Optional)"
            placeholder="Auto-generated from identity & color if empty"
            value={variantName}
            onChange={(e) => setVariantName(e.target.value)}
            size="small"
            InputLabelProps={{ sx: { color: '#94a3b8' } }}
            InputProps={{ sx: { color: '#ffffff', bgcolor: 'rgba(255, 255, 255, 0.04)' } }}
          />

          {/* Computed SKU Live Preview */}
          <Box sx={{ p: 2, bgcolor: 'rgba(56, 189, 248, 0.06)', borderRadius: 2, border: '1px solid rgba(56, 189, 248, 0.2)' }}>
            <Typography variant="caption" sx={{ color: '#94a3b8', display: 'block', mb: 0.5 }}>
              Deterministic Full SKU Preview (UPIS + UML):
            </Typography>
            <Typography variant="h6" sx={{ color: '#38bdf8', fontWeight: 700, fontFamily: 'monospace' }}>
              {computedSku}
            </Typography>
          </Box>
        </Stack>
      </DialogContent>

      <DialogActions sx={{ p: 2, px: 3 }}>
        <Button onClick={onClose} sx={{ color: '#94a3b8', textTransform: 'none' }}>
          Cancel
        </Button>
        <Button
          variant="contained"
          onClick={handleSubmit}
          disabled={loading}
          startIcon={<CheckCircle />}
          sx={{
            bgcolor: '#0284c7',
            color: '#ffffff',
            textTransform: 'none',
            fontWeight: 600,
            '&:hover': { bgcolor: '#0369a1' },
          }}
        >
          {loading ? 'Creating...' : 'Create Variant'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

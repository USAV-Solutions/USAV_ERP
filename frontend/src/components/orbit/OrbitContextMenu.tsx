import React from 'react'
import {
  Menu,
  MenuItem,
  ListItemIcon,
  ListItemText,
  Divider,
  Typography,
  Box,
  Chip,
} from '@mui/material'
import {
  Palette,
  Inventory2,
  Handyman,
  Extension,
  Settings,
  LinkOff,
  AutoAwesome,
  CompareArrows,
  CheckCircle,
  TrendingUp,
  Warning,
  CenterFocusStrong,
  ChangeCircle,
} from '@mui/icons-material'
import type { RelationshipType, Platform } from '../../types/inventory'

export interface ContextMenuTarget {
  type: 'node' | 'edge'
  nodeType?: 'product' | 'listing' | 'related_product' | 'ai_candidate'
  id: string
  numericId?: number
  title: string
  subtitle?: string
  relationshipType?: RelationshipType
  platform?: Platform
  hasPriceMismatch?: boolean
  mismatchDiff?: number
  price?: number | null
}

interface OrbitContextMenuProps {
  anchorPos: { mouseX: number; mouseY: number } | null
  target: ContextMenuTarget | null
  isDarkMode?: boolean
  onClose: () => void
  onChangeRelationship: (relType: RelationshipType) => void
  onUnlink: () => void
  onCreateVariant: () => void
  onFormBundleKit: () => void
  onConvertType?: () => void
  onScanAI: () => void
  onViewAnalytics: () => void
  onFocusProduct?: (variantId: number) => void
}

const RELATIONSHIP_OPTIONS: Array<{ type: RelationshipType; label: string; icon: string; color: string }> = [
  { type: 'EXACT', label: 'EXACT (1:1 Listing)', icon: '🎯', color: '#38bdf8' },
  { type: 'ACCESSORY', label: 'ACCESSORY (Compatible Attachment)', icon: '🔌', color: '#10b981' },
  { type: 'BUNDLE_COMPONENT', label: 'BUNDLE_COMPONENT (USAV Bundle B)', icon: '📦', color: '#f59e0b' },
  { type: 'KIT_COMPONENT', label: 'KIT_COMPONENT (Manufacturer Kit K)', icon: '🧰', color: '#818cf8' },
  { type: 'PART_LCI', label: 'PART_LCI (Internal LCI Component P)', icon: '⚙️', color: '#f97316' },
  { type: 'SIBLING_VARIANT', label: 'SIBLING_VARIANT (Color/Condition)', icon: '🔗', color: '#a855f7' },
]

export default function OrbitContextMenu({
  anchorPos,
  target,
  isDarkMode = true,
  onClose,
  onChangeRelationship,
  onUnlink,
  onCreateVariant,
  onFormBundleKit,
  onConvertType,
  onScanAI,
  onViewAnalytics,
  onFocusProduct,
}: OrbitContextMenuProps) {
  if (!anchorPos || !target) return null

  return (
    <Menu
      open={!!anchorPos}
      onClose={onClose}
      anchorReference="anchorPosition"
      anchorPosition={
        anchorPos !== null
          ? { top: anchorPos.mouseY, left: anchorPos.mouseX }
          : undefined
      }
      PaperProps={{
        sx: {
          bgcolor: isDarkMode ? 'rgba(15, 23, 42, 0.98)' : '#ffffff',
          backdropFilter: 'blur(16px)',
          color: isDarkMode ? '#f8fafc' : '#0f172a',
          border: isDarkMode ? '1px solid rgba(255, 255, 255, 0.15)' : '1px solid #cbd5e1',
          borderRadius: 2.5,
          boxShadow: isDarkMode ? '0 16px 48px rgba(0, 0, 0, 0.8)' : '0 16px 48px rgba(0, 0, 0, 0.15)',
          minWidth: 270,
          py: 0.5,
        },
      }}
    >
      {/* Header */}
      <Box sx={{ px: 2, py: 1, borderBottom: isDarkMode ? '1px solid rgba(255, 255, 255, 0.08)' : '1px solid #e2e8f0' }}>
        <Typography variant="caption" sx={{ color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.8, fontSize: 9.5 }}>
          {target.type === 'edge' ? 'Relationship Tether' : `${target.nodeType || 'Node'}`}
        </Typography>
        <Typography variant="body2" sx={{ fontWeight: 600, color: isDarkMode ? '#f8fafc' : '#0f172a', fontSize: 12.5 }} noWrap>
          {target.title}
        </Typography>
        {target.hasPriceMismatch && (
          <Chip
            size="small"
            icon={<Warning sx={{ fontSize: '13px !important', color: '#fbbf24 !important' }} />}
            label={`Price Mismatch: $${Math.abs(target.mismatchDiff || 0).toFixed(2)}`}
            sx={{ mt: 0.5, bgcolor: 'rgba(245, 158, 11, 0.15)', color: '#fbbf24', fontSize: 10, fontWeight: 600 }}
          />
        )}
      </Box>

      {/* Master Core Actions */}
      {target.nodeType === 'product' && [
        <MenuItem
          key="convert-type"
          onClick={() => {
            onClose()
            if (onConvertType) onConvertType()
          }}
          sx={{ fontSize: 12.5, py: 1 }}
        >
          <ListItemIcon sx={{ color: '#38bdf8', minWidth: 30 }}>
            <ChangeCircle fontSize="small" />
          </ListItemIcon>
          <ListItemText primary="🔄 Convert Product Type (Kit / Bundle / Base)" primaryTypographyProps={{ fontSize: 12.5, fontWeight: 600, color: '#38bdf8' }} />
        </MenuItem>,

        <MenuItem
          key="create-variant"
          onClick={() => {
            onClose()
            onCreateVariant()
          }}
          sx={{ fontSize: 12.5, py: 1 }}
        >
          <ListItemIcon sx={{ color: '#38bdf8', minWidth: 30 }}>
            <Palette fontSize="small" />
          </ListItemIcon>
          <ListItemText primary="Create Color / Condition Variant" primaryTypographyProps={{ fontSize: 12.5 }} />
        </MenuItem>,

        <MenuItem
          key="form-bundle"
          onClick={() => {
            onClose()
            onFormBundleKit()
          }}
          sx={{ fontSize: 12.5, py: 1 }}
        >
          <ListItemIcon sx={{ color: '#f59e0b', minWidth: 30 }}>
            <Inventory2 fontSize="small" />
          </ListItemIcon>
          <ListItemText primary="Form Bundle (B) / Kit (K)..." primaryTypographyProps={{ fontSize: 12.5 }} />
        </MenuItem>,

        <MenuItem
          key="view-analytics"
          onClick={() => {
            onClose()
            onViewAnalytics()
          }}
          sx={{ fontSize: 12.5, py: 1 }}
        >
          <ListItemIcon sx={{ color: '#10b981', minWidth: 30 }}>
            <TrendingUp fontSize="small" />
          </ListItemIcon>
          <ListItemText primary="View Order Velocity & Stock Runway" primaryTypographyProps={{ fontSize: 12.5 }} />
        </MenuItem>,

        <Divider key="div-prod" sx={{ borderColor: isDarkMode ? 'rgba(255, 255, 255, 0.08)' : '#e2e8f0' }} />,

        <MenuItem
          key="scan-ai"
          onClick={() => {
            onClose()
            onScanAI()
          }}
          sx={{ fontSize: 12.5, py: 1 }}
        >
          <ListItemIcon sx={{ color: '#c084fc', minWidth: 30 }}>
            <AutoAwesome fontSize="small" />
          </ListItemIcon>
          <ListItemText primary="Scan AI Matches (Priority Queue)" primaryTypographyProps={{ fontSize: 12.5, color: '#c084fc', fontWeight: 600 }} />
        </MenuItem>,
      ]}

      {/* Related Product Actions (Ring 2, 3, 4) */}
      {target.nodeType === 'related_product' && [
        <MenuItem
          key="focus-prod"
          onClick={() => {
            onClose()
            if (target.numericId && onFocusProduct) {
              onFocusProduct(target.numericId)
            }
          }}
          sx={{ fontSize: 12.5, py: 1 }}
        >
          <ListItemIcon sx={{ color: '#38bdf8', minWidth: 30 }}>
            <CenterFocusStrong fontSize="small" />
          </ListItemIcon>
          <ListItemText primary="🪐 Focus as Master Product" primaryTypographyProps={{ fontSize: 12.5, fontWeight: 600, color: '#38bdf8' }} />
        </MenuItem>,

        <MenuItem
          key="add-to-bundle"
          onClick={() => {
            onClose()
            onFormBundleKit()
          }}
          sx={{ fontSize: 12.5, py: 1 }}
        >
          <ListItemIcon sx={{ color: '#f59e0b', minWidth: 30 }}>
            <Inventory2 fontSize="small" />
          </ListItemIcon>
          <ListItemText primary="Form Bundle / Kit with this item" primaryTypographyProps={{ fontSize: 12.5 }} />
        </MenuItem>,

        <Divider key="div-rel" sx={{ borderColor: isDarkMode ? 'rgba(255, 255, 255, 0.08)' : '#e2e8f0' }} />,
      ]}

      {/* Listing, Related Product, or Edge: Switch Relationship */}
      {(target.nodeType === 'listing' ||
        target.nodeType === 'ai_candidate' ||
        target.nodeType === 'related_product' ||
        target.type === 'edge') && (
        <Box>
          <Box sx={{ px: 2, pt: 1, pb: 0.5 }}>
            <Typography variant="caption" sx={{ color: '#94a3b8', fontSize: 10, fontWeight: 600 }}>
              CHANGE RELATIONSHIP TYPE:
            </Typography>
          </Box>
          {RELATIONSHIP_OPTIONS.map((opt) => (
            <MenuItem
              key={opt.type}
              onClick={() => {
                onClose()
                onChangeRelationship(opt.type)
              }}
              selected={target.relationshipType === opt.type}
              sx={{ fontSize: 12, py: 0.75 }}
            >
              <ListItemIcon sx={{ color: opt.color, minWidth: 26, fontSize: 14 }}>
                {opt.icon}
              </ListItemIcon>
              <ListItemText
                primary={opt.label}
                primaryTypographyProps={{
                  fontSize: 12,
                  fontWeight: target.relationshipType === opt.type ? 700 : 400,
                  color: target.relationshipType === opt.type ? opt.color : isDarkMode ? '#f8fafc' : '#0f172a',
                }}
              />
            </MenuItem>
          ))}

          <Divider sx={{ borderColor: isDarkMode ? 'rgba(255, 255, 255, 0.08)' : '#e2e8f0', my: 0.5 }} />

          <MenuItem
            onClick={() => {
              onClose()
              onUnlink()
            }}
            sx={{ fontSize: 12, color: '#ef4444', py: 1 }}
          >
            <ListItemIcon sx={{ color: '#ef4444', minWidth: 30 }}>
              <LinkOff fontSize="small" />
            </ListItemIcon>
            <ListItemText primary="Unlink / Sever Tether" primaryTypographyProps={{ fontSize: 12, color: '#ef4444', fontWeight: 600 }} />
          </MenuItem>
        </Box>
      )}
    </Menu>
  )
}

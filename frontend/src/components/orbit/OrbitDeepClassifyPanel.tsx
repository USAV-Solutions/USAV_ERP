import React, { useState } from 'react'
import {
  Box,
  Paper,
  Typography,
  Chip,
  Button,
  LinearProgress,
  Collapse,
  IconButton,
  Table,
  TableBody,
  TableRow,
  TableCell,
  Tooltip,
  Stack,
  Alert,
} from '@mui/material'
import {
  ExpandMore,
  ExpandLess,
  ChangeCircle,
  CheckCircle,
  Warning,
  Science,
  Category,
} from '@mui/icons-material'

// ============================================================================
// Types
// ============================================================================

export interface AIClassifiedComponent {
  component_name: string
  suggested_quantity: number
  suggested_role: string
  matched_variant_id: number | null
  matched_sku: string | null
  matched_name: string | null
  match_confidence: number
}

export interface AIClassifiedParent {
  parent_name: string
  matched_variant_id: number | null
  matched_sku: string | null
  matched_name: string | null
  match_confidence: number
}

export interface AIDeepClassifyResponse {
  variant_id: number
  full_sku: string
  current_type: string
  suggested_type: string
  type_confidence: number
  type_reasoning: string
  suggested_components: AIClassifiedComponent[]
  suggested_parents: AIClassifiedParent[]
  warnings: string[]
}

// ============================================================================
// Helpers
// ============================================================================

const TYPE_LABELS: Record<string, string> = {
  Product: 'Standalone Item',
  K: 'Kit',
  B: 'Bundle',
  P: 'Part / Component',
}

const TYPE_COLORS: Record<string, string> = {
  Product: '#64748b',
  K: '#8b5cf6',
  B: '#f59e0b',
  P: '#3b82f6',
}

// ============================================================================
// Component
// ============================================================================

interface OrbitDeepClassifyPanelProps {
  result: AIDeepClassifyResponse | null
  loading: boolean
  isDarkMode: boolean
  onConvertType: (suggestedType: string, components: AIClassifiedComponent[]) => void
  onFocusProduct: (variantId: number) => void
}

const OrbitDeepClassifyPanel: React.FC<OrbitDeepClassifyPanelProps> = ({
  result,
  loading,
  isDarkMode,
  onConvertType,
  onFocusProduct,
}) => {
  const [expanded, setExpanded] = useState(true)

  if (!result && !loading) return null

  const bg = isDarkMode ? 'rgba(15, 23, 42, 0.95)' : 'rgba(255, 255, 255, 0.97)'
  const text = isDarkMode ? '#f8fafc' : '#0f172a'
  const subText = isDarkMode ? '#94a3b8' : '#64748b'
  const border = isDarkMode ? 'rgba(255, 255, 255, 0.1)' : '#cbd5e1'

  return (
    <Paper
      elevation={8}
      sx={{
        position: 'fixed',
        bottom: 16,
        right: 16,
        width: 420,
        maxHeight: expanded ? 520 : 48,
        overflow: 'hidden',
        bgcolor: bg,
        color: text,
        border: `1px solid ${border}`,
        borderRadius: 3,
        backdropFilter: 'blur(12px)',
        transition: 'max-height 0.3s ease',
        zIndex: 1300,
      }}
    >
      {/* Header */}
      <Box
        onClick={() => setExpanded((p) => !p)}
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          px: 2,
          py: 1,
          cursor: 'pointer',
          borderBottom: expanded ? `1px solid ${border}` : 'none',
          bgcolor: isDarkMode ? 'rgba(139, 92, 246, 0.08)' : 'rgba(139, 92, 246, 0.04)',
        }}
      >
        <Stack direction="row" alignItems="center" spacing={1}>
          <Science sx={{ fontSize: 18, color: '#8b5cf6' }} />
          <Typography variant="subtitle2" sx={{ fontWeight: 700, fontSize: 13 }}>
            AI Deep Classification
          </Typography>
          {loading && (
            <Chip label="Scanning..." size="small" sx={{ bgcolor: '#8b5cf6', color: '#fff', fontSize: 10, height: 20 }} />
          )}
        </Stack>
        <IconButton size="small" sx={{ color: subText }}>
          {expanded ? <ExpandLess fontSize="small" /> : <ExpandMore fontSize="small" />}
        </IconButton>
      </Box>

      {/* Body */}
      <Collapse in={expanded}>
        <Box sx={{ p: 2, maxHeight: 460, overflowY: 'auto' }}>
          {loading && (
            <Box sx={{ py: 3 }}>
              <Typography variant="body2" sx={{ color: subText, mb: 1, textAlign: 'center' }}>
                Analyzing product with Gemini AI...
              </Typography>
              <LinearProgress sx={{ borderRadius: 2, bgcolor: isDarkMode ? '#1e293b' : '#e2e8f0' }} />
            </Box>
          )}

          {result && (
            <Stack spacing={2}>
              {/* Type Classification Card */}
              <Box
                sx={{
                  p: 1.5,
                  borderRadius: 2,
                  border: `1px solid ${border}`,
                  bgcolor: isDarkMode ? 'rgba(30, 41, 59, 0.5)' : 'rgba(241, 245, 249, 0.5)',
                }}
              >
                <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
                  <Category sx={{ fontSize: 16, color: '#8b5cf6' }} />
                  <Typography variant="subtitle2" sx={{ fontWeight: 700, fontSize: 12 }}>
                    Product Classification
                  </Typography>
                </Stack>

                <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
                  <Chip
                    label={TYPE_LABELS[result.current_type] || result.current_type}
                    size="small"
                    sx={{
                      bgcolor: TYPE_COLORS[result.current_type] || '#64748b',
                      color: '#fff',
                      fontWeight: 600,
                      fontSize: 11,
                    }}
                  />
                  <Typography sx={{ fontSize: 14, color: subText }}>→</Typography>
                  <Chip
                    label={TYPE_LABELS[result.suggested_type] || result.suggested_type}
                    size="small"
                    sx={{
                      bgcolor: TYPE_COLORS[result.suggested_type] || '#64748b',
                      color: '#fff',
                      fontWeight: 700,
                      fontSize: 11,
                      border: result.suggested_type !== result.current_type ? '2px solid #facc15' : 'none',
                    }}
                  />
                  <Typography variant="caption" sx={{ color: subText, fontWeight: 600 }}>
                    {(result.type_confidence * 100).toFixed(0)}%
                  </Typography>
                </Stack>

                <LinearProgress
                  variant="determinate"
                  value={result.type_confidence * 100}
                  sx={{
                    height: 6,
                    borderRadius: 3,
                    mb: 1,
                    bgcolor: isDarkMode ? '#1e293b' : '#e2e8f0',
                    '& .MuiLinearProgress-bar': {
                      bgcolor: TYPE_COLORS[result.suggested_type] || '#8b5cf6',
                      borderRadius: 3,
                    },
                  }}
                />

                <Typography variant="caption" sx={{ color: subText, lineHeight: 1.4, display: 'block', mb: 1 }}>
                  {result.type_reasoning}
                </Typography>

                {result.suggested_type !== result.current_type && (
                  <Button
                    variant="contained"
                    size="small"
                    startIcon={<ChangeCircle />}
                    onClick={() =>
                      onConvertType(
                        result.suggested_type,
                        result.suggested_components.filter((c) => c.matched_variant_id),
                      )
                    }
                    sx={{
                      bgcolor: TYPE_COLORS[result.suggested_type] || '#8b5cf6',
                      textTransform: 'none',
                      fontWeight: 700,
                      fontSize: 11,
                      '&:hover': { bgcolor: TYPE_COLORS[result.suggested_type] || '#7c3aed', filter: 'brightness(0.9)' },
                    }}
                  >
                    Convert to {TYPE_LABELS[result.suggested_type] || result.suggested_type}
                  </Button>
                )}
              </Box>

              {/* Warnings */}
              {result.warnings.map((w, i) => (
                <Alert key={i} severity="warning" sx={{ fontSize: 11, py: 0, '& .MuiAlert-message': { py: 0.5 } }}>
                  {w}
                </Alert>
              ))}

              {/* Suggested Components */}
              {result.suggested_components.length > 0 && (
                <Box>
                  <Typography variant="subtitle2" sx={{ fontWeight: 700, fontSize: 12, mb: 0.5 }}>
                    Expected Components
                  </Typography>
                  <Table size="small" sx={{ '& td, & th': { border: 'none', py: 0.5, px: 1, fontSize: 11, color: text } }}>
                    <TableBody>
                      {result.suggested_components.map((comp, idx) => (
                        <TableRow key={idx}>
                          <TableCell sx={{ fontWeight: 600, maxWidth: 140 }}>{comp.component_name}</TableCell>
                          <TableCell align="center">{'\u00D7'}{comp.suggested_quantity}</TableCell>
                          <TableCell>
                            <Chip
                              label={comp.suggested_role}
                              size="small"
                              sx={{ fontSize: 9, height: 18, bgcolor: isDarkMode ? '#1e293b' : '#f1f5f9', color: subText }}
                            />
                          </TableCell>
                          <TableCell align="right">
                            {comp.matched_variant_id ? (
                              <Tooltip title={`${comp.matched_name} \u2014 Click to focus`}>
                                <Chip
                                  icon={<CheckCircle sx={{ fontSize: 12 }} />}
                                  label={comp.matched_sku}
                                  size="small"
                                  clickable
                                  onClick={() => onFocusProduct(comp.matched_variant_id!)}
                                  sx={{
                                    fontSize: 9,
                                    height: 20,
                                    bgcolor: 'rgba(16, 185, 129, 0.15)',
                                    color: '#10b981',
                                    fontWeight: 600,
                                  }}
                                />
                              </Tooltip>
                            ) : (
                              <Chip
                                icon={<Warning sx={{ fontSize: 12 }} />}
                                label="Not in catalog"
                                size="small"
                                sx={{
                                  fontSize: 9,
                                  height: 20,
                                  bgcolor: 'rgba(245, 158, 11, 0.15)',
                                  color: '#f59e0b',
                                }}
                              />
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </Box>
              )}

              {/* Suggested Parents */}
              {result.suggested_parents.length > 0 && (
                <Box>
                  <Typography variant="subtitle2" sx={{ fontWeight: 700, fontSize: 12, mb: 0.5 }}>
                    Parent Products
                  </Typography>
                  <Table size="small" sx={{ '& td, & th': { border: 'none', py: 0.5, px: 1, fontSize: 11, color: text } }}>
                    <TableBody>
                      {result.suggested_parents.map((parent, idx) => (
                        <TableRow key={idx}>
                          <TableCell sx={{ fontWeight: 600 }}>{parent.parent_name}</TableCell>
                          <TableCell align="right">
                            {parent.matched_variant_id ? (
                              <Tooltip title={`${parent.matched_name} \u2014 Click to focus`}>
                                <Chip
                                  icon={<CheckCircle sx={{ fontSize: 12 }} />}
                                  label={parent.matched_sku}
                                  size="small"
                                  clickable
                                  onClick={() => onFocusProduct(parent.matched_variant_id!)}
                                  sx={{
                                    fontSize: 9,
                                    height: 20,
                                    bgcolor: 'rgba(16, 185, 129, 0.15)',
                                    color: '#10b981',
                                    fontWeight: 600,
                                  }}
                                />
                              </Tooltip>
                            ) : (
                              <Chip
                                icon={<Warning sx={{ fontSize: 12 }} />}
                                label="Not in catalog"
                                size="small"
                                sx={{
                                  fontSize: 9,
                                  height: 20,
                                  bgcolor: 'rgba(245, 158, 11, 0.15)',
                                  color: '#f59e0b',
                                }}
                              />
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </Box>
              )}
            </Stack>
          )}
        </Box>
      </Collapse>
    </Paper>
  )
}

export default OrbitDeepClassifyPanel

import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Box,
  Typography,
  Button,
  IconButton,
  Chip,
  Paper,
  CircularProgress,
  Alert,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Avatar,
  Stack,
  Card,
  CardContent,
  Autocomplete,
  TextField,
} from '@mui/material'
import {
  Close,
  Hub,
  AutoAwesome,
  Lock,
  CompareArrows,
  ZoomIn,
  ZoomOut,
  RestartAlt,
} from '@mui/icons-material'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axiosClient from '../../api/axiosClient'
import { CATALOG, LISTINGS } from '../../api/endpoints'
import {
  GraphTopologyResponse,
  ListingNode,
  ProductNode,
  AISuggestResponse,
  AISuggestion,
  LockRelationshipResponse,
  CompareResponse,
  Platform,
  Variant,
} from '../../types/inventory'

const PLATFORM_META: Record<string, { label: string; color: string; bgColor: string; icon: string }> = {
  ECWID: { label: 'Ecwid', color: '#0064d2', bgColor: '#e8f0fe', icon: '🛒' },
  SHOPIFY: { label: 'Shopify', color: '#96bf48', bgColor: '#f0f7e8', icon: '🛍️' },
  EBAY_USAV: { label: 'eBay USAV', color: '#e53238', bgColor: '#fde8e8', icon: '🏷️' },
  EBAY_MEKONG: { label: 'eBay Mekong', color: '#0064d2', bgColor: '#e8f4fd', icon: '🏷️' },
  EBAY_DRAGON: { label: 'eBay Dragon', color: '#f5af02', bgColor: '#fef7e6', icon: '🏷️' },
  EBAY_PURCHASING: { label: 'eBay Purchasing', color: '#86b817', bgColor: '#f3f8e6', icon: '🏷️' },
  AMAZON: { label: 'Amazon', color: '#ff9900', bgColor: '#fff4e5', icon: '📦' },
  WALMART: { label: 'Walmart', color: '#0071dc', bgColor: '#e6f1fc', icon: '🏬' },
}

interface CanvasNode {
  id: string
  type: 'product' | 'listing' | 'ai_candidate'
  x: number
  y: number
  vx: number
  vy: number
  radius: number
  data: ProductNode | ListingNode | (AISuggestion & { platform: Platform })
  confidence?: number
  reasons?: string[]
}

interface CanvasEdge {
  source: string
  target: string
  type: 'locked' | 'suggested'
  confidence?: number
}

export interface ListingGraphModalProps {
  open: boolean
  onClose: () => void
  variantId: number | null
  variantSku?: string
  onListingLocked?: () => void
}

export const ListingGraphModal: React.FC<ListingGraphModalProps> = ({
  open,
  onClose,
  variantId,
  variantSku,
  onListingLocked,
}) => {
  const queryClient = useQueryClient()
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  const [activeVariantId, setActiveVariantId] = useState<number | null>(variantId)

  useEffect(() => {
    if (variantId) setActiveVariantId(variantId)
  }, [variantId])

  const { data: variantsList } = useQuery({
    queryKey: ['variants-lookup'],
    queryFn: async () => {
      const resp = await axiosClient.get(CATALOG.VARIANTS, { params: { limit: 1000 } })
      return (resp.data.items || []) as Variant[]
    },
    enabled: open,
  })

  const [nodes, setNodes] = useState<CanvasNode[]>([])
  const [edges, setEdges] = useState<CanvasEdge[]>([])
  const [hoveredNode, setHoveredNode] = useState<CanvasNode | null>(null)
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([])
  const [hoverPos, setHoverPos] = useState<{ x: number; y: number } | null>(null)
  const [draggedNode, setDraggedNode] = useState<CanvasNode | null>(null)
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [isPanning, setIsPanning] = useState(false)
  const [panStart, setPanStart] = useState({ x: 0, y: 0 })

  const [compareOpen, setCompareOpen] = useState(false)
  const [aiScanning, setAiScanning] = useState(false)
  const [aiSuggestions, setAiSuggestions] = useState<AISuggestion[]>([])
  const [actionMessage, setActionMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  const {
    data: graphData,
    isLoading: isGraphLoading,
    refetch: refetchGraph,
  } = useQuery<GraphTopologyResponse>({
    queryKey: ['listing-graph', activeVariantId],
    queryFn: async () => {
      const resp = await axiosClient.get(LISTINGS.GRAPH(activeVariantId!))
      return resp.data
    },
    enabled: open && !!activeVariantId,
  })

  const lockMutation = useMutation({
    mutationFn: async ({ listingId, targetVariantId }: { listingId: number; targetVariantId: number }) => {
      const resp = await axiosClient.post(LISTINGS.LOCK_RELATIONSHIP, {
        listing_id: listingId,
        variant_id: targetVariantId,
        enrich_metadata: true,
      })
      return resp.data as LockRelationshipResponse
    },
    onSuccess: (data) => {
      setActionMessage({
        type: 'success',
        text: `Successfully locked ${data.platform} listing to variant!`,
      })
      refetchGraph()
      queryClient.invalidateQueries({ queryKey: ['platform-listings'] })
      setAiSuggestions((prev) => prev.filter((s) => s.listing_id !== data.listing_id))
      if (onListingLocked) onListingLocked()
    },
    onError: (err: any) => {
      setActionMessage({
        type: 'error',
        text: err?.response?.data?.detail || 'Failed to lock listing relationship.',
      })
    },
  })

  const selectedListingIds = useMemo(() => {
    return selectedNodeIds
      .filter((id) => id.startsWith('listing-') || id.startsWith('ai-'))
      .map((id) => parseInt(id.replace('listing-', '').replace('ai-', ''), 10))
      .filter((id) => !isNaN(id))
  }, [selectedNodeIds])

  const { data: compareData, isLoading: isCompareLoading } = useQuery<CompareResponse>({
    queryKey: ['listing-compare', selectedListingIds],
    queryFn: async () => {
      const resp = await axiosClient.post(LISTINGS.COMPARE, { listing_ids: selectedListingIds })
      return resp.data
    },
    enabled: compareOpen && selectedListingIds.length >= 2,
  })

  const handleScanAI = async () => {
    if (!activeVariantId) return
    setAiScanning(true)
    setActionMessage(null)
    try {
      const resp = await axiosClient.post(LISTINGS.SUGGEST, {
        variant_id: activeVariantId,
        limit: 8,
        include_linked: false,
      })
      const result = resp.data as AISuggestResponse
      setAiSuggestions(result.suggestions)
      if (result.suggestions.length === 0) {
        setActionMessage({ type: 'success', text: 'No unlinked candidate listings found for this product.' })
      } else {
        setActionMessage({
          type: 'success',
          text: `Found ${result.suggestions.length} AI-suggested candidate listings!`,
        })
      }
    } catch (err: any) {
      setActionMessage({
        type: 'error',
        text: err?.response?.data?.detail || 'Failed to run AI match engine.',
      })
    } finally {
      setAiScanning(false)
    }
  }

  useEffect(() => {
    if (!graphData) return

    const canvasWidth = 850
    const canvasHeight = 520
    const centerX = canvasWidth / 2
    const centerY = canvasHeight / 2

    const newNodes: CanvasNode[] = []
    const newEdges: CanvasEdge[] = []

    newNodes.push({
      id: 'product-center',
      type: 'product',
      x: centerX,
      y: centerY,
      vx: 0,
      vy: 0,
      radius: 46,
      data: graphData.product,
    })

    const lockedCount = graphData.listings.length
    const lockedRadius = 180

    graphData.listings.forEach((listing, index) => {
      const angle = (index / Math.max(lockedCount, 1)) * 2 * Math.PI - Math.PI / 2
      const x = centerX + lockedRadius * Math.cos(angle)
      const y = centerY + lockedRadius * Math.sin(angle)
      const nodeId = `listing-${listing.listing_id}`

      newNodes.push({
        id: nodeId,
        type: 'listing',
        x,
        y,
        vx: 0,
        vy: 0,
        radius: 36,
        data: listing,
      })

      newEdges.push({
        source: 'product-center',
        target: nodeId,
        type: 'locked',
      })
    })

    const aiCount = aiSuggestions.length
    const aiRadius = 260

    aiSuggestions.forEach((candidate, index) => {
      const angle = ((index + 0.5) / Math.max(aiCount, 1)) * 2 * Math.PI - Math.PI / 2
      const x = centerX + aiRadius * Math.cos(angle)
      const y = centerY + aiRadius * Math.sin(angle)
      const nodeId = `ai-${candidate.listing_id}`

      newNodes.push({
        id: nodeId,
        type: 'ai_candidate',
        x,
        y,
        vx: 0,
        vy: 0,
        radius: 38,
        data: candidate,
        confidence: candidate.confidence,
        reasons: candidate.reasons,
      })

      newEdges.push({
        source: 'product-center',
        target: nodeId,
        type: 'suggested',
        confidence: candidate.confidence,
      })
    })

    setNodes(newNodes)
    setEdges(newEdges)
  }, [graphData, aiSuggestions])

  const drawCanvas = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    const width = canvas.clientWidth
    const height = canvas.clientHeight

    canvas.width = width * dpr
    canvas.height = height * dpr
    ctx.scale(dpr, dpr)

    ctx.fillStyle = '#0f172a'
    ctx.fillRect(0, 0, width, height)

    ctx.save()
    ctx.translate(pan.x, pan.y)
    ctx.scale(zoom, zoom)

    ctx.strokeStyle = '#1e293b'
    ctx.lineWidth = 1
    const gridSize = 40
    for (let x = -width * 2; x < width * 3; x += gridSize) {
      ctx.beginPath()
      ctx.moveTo(x, -height * 2)
      ctx.lineTo(x, height * 3)
      ctx.stroke()
    }
    for (let y = -height * 2; y < height * 3; y += gridSize) {
      ctx.beginPath()
      ctx.moveTo(-width * 2, y)
      ctx.lineTo(width * 3, y)
      ctx.stroke()
    }

    const nodeMap = new Map<string, CanvasNode>()
    nodes.forEach((n) => nodeMap.set(n.id, n))

    edges.forEach((edge) => {
      const src = nodeMap.get(edge.source)
      const tgt = nodeMap.get(edge.target)
      if (!src || !tgt) return

      ctx.beginPath()
      ctx.moveTo(src.x, src.y)
      ctx.lineTo(tgt.x, tgt.y)

      if (edge.type === 'locked') {
        ctx.strokeStyle = '#38bdf8'
        ctx.lineWidth = 2.5
        ctx.setLineDash([])
      } else {
        ctx.strokeStyle = '#a855f7'
        ctx.lineWidth = 2
        ctx.setLineDash([6, 6])
      }
      ctx.stroke()
      ctx.setLineDash([])

      if (edge.type === 'suggested' && edge.confidence !== undefined) {
        const midX = (src.x + tgt.x) / 2
        const midY = (src.y + tgt.y) / 2
        const pct = Math.round(edge.confidence * 100)

        ctx.fillStyle = '#6b21a8'
        ctx.beginPath()
        ctx.roundRect(midX - 22, midY - 10, 44, 20, 10)
        ctx.fill()
        ctx.strokeStyle = '#c084fc'
        ctx.lineWidth = 1
        ctx.stroke()

        ctx.fillStyle = '#ffffff'
        ctx.font = 'bold 10px sans-serif'
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillText(`✨${pct}%`, midX, midY)
      }
    })

    nodes.forEach((node) => {
      const isSelected = selectedNodeIds.includes(node.id)
      const isHovered = hoveredNode?.id === node.id

      if (isSelected) {
        ctx.beginPath()
        ctx.arc(node.x, node.y, node.radius + 7, 0, Math.PI * 2)
        ctx.strokeStyle = '#38bdf8'
        ctx.lineWidth = 3
        ctx.setLineDash([4, 2])
        ctx.stroke()
        ctx.setLineDash([])
      }

      if (isHovered) {
        ctx.beginPath()
        ctx.arc(node.x, node.y, node.radius + 5, 0, Math.PI * 2)
        ctx.strokeStyle = '#facc15'
        ctx.lineWidth = 2.5
        ctx.stroke()
      }

      ctx.beginPath()
      ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2)

      if (node.type === 'product') {
        const grad = ctx.createRadialGradient(node.x, node.y, 5, node.x, node.y, node.radius)
        grad.addColorStop(0, '#3b82f6')
        grad.addColorStop(1, '#1d4ed8')
        ctx.fillStyle = grad
        ctx.fill()
        ctx.strokeStyle = '#93c5fd'
        ctx.lineWidth = 3
        ctx.stroke()

        ctx.fillStyle = '#ffffff'
        ctx.font = 'bold 12px sans-serif'
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        const prod = node.data as ProductNode
        ctx.fillText('ERP MASTER', node.x, node.y - 8)
        ctx.font = '10px sans-serif'
        ctx.fillStyle = '#bfdbfe'
        ctx.fillText(prod.full_sku || 'SKU', node.x, node.y + 8)
      } else if (node.type === 'listing') {
        const listing = node.data as ListingNode
        const meta = PLATFORM_META[listing.platform] || { label: listing.platform, color: '#64748b' }

        ctx.fillStyle = '#1e293b'
        ctx.fill()
        ctx.strokeStyle = meta.color
        ctx.lineWidth = 2.5
        ctx.stroke()

        ctx.fillStyle = meta.color
        ctx.font = 'bold 11px sans-serif'
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillText(meta.label.substring(0, 8), node.x, node.y - 8)

        ctx.font = 'bold 10px sans-serif'
        ctx.fillStyle = '#4ade80'
        const priceStr = listing.listing_price ? `$${listing.listing_price}` : 'No price'
        ctx.fillText(priceStr, node.x, node.y + 8)

        const pipColor = listing.sync_status === 'SYNCED' ? '#22c55e' : listing.sync_status === 'PENDING' ? '#f59e0b' : '#ef4444'
        ctx.beginPath()
        ctx.arc(node.x + node.radius - 8, node.y - node.radius + 8, 5, 0, Math.PI * 2)
        ctx.fillStyle = pipColor
        ctx.fill()
        ctx.strokeStyle = '#0f172a'
        ctx.lineWidth = 1.5
        ctx.stroke()
      } else {
        const candidate = node.data as AISuggestion
        const meta = PLATFORM_META[candidate.platform] || { label: candidate.platform, color: '#a855f7' }

        const grad = ctx.createRadialGradient(node.x, node.y, 5, node.x, node.y, node.radius)
        grad.addColorStop(0, '#581c87')
        grad.addColorStop(1, '#3b0764')
        ctx.fillStyle = grad
        ctx.fill()
        ctx.strokeStyle = '#c084fc'
        ctx.lineWidth = 2
        ctx.setLineDash([4, 3])
        ctx.stroke()
        ctx.setLineDash([])

        ctx.fillStyle = '#f3e8ff'
        ctx.font = 'bold 10px sans-serif'
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillText(meta.label.substring(0, 8), node.x, node.y - 9)

        ctx.font = 'bold 10px sans-serif'
        ctx.fillStyle = '#facc15'
        ctx.fillText(`✨AI ${Math.round((node.confidence || 0) * 100)}%`, node.x, node.y + 7)
      }
    })

    ctx.restore()
  }, [nodes, edges, selectedNodeIds, hoveredNode, zoom, pan])

  useEffect(() => {
    drawCanvas()
  }, [drawCanvas])

  const getCanvasCoords = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    if (!canvas) return { x: 0, y: 0, screenX: e.clientX, screenY: e.clientY }
    const rect = canvas.getBoundingClientRect()
    const clientX = e.clientX - rect.left
    const clientY = e.clientY - rect.top
    const x = (clientX - pan.x) / zoom
    const y = (clientY - pan.y) / zoom
    return { x, y, screenX: e.clientX, screenY: e.clientY }
  }

  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const { x, y } = getCanvasCoords(e)
    const clicked = nodes.find((n) => Math.hypot(n.x - x, n.y - y) <= n.radius)

    if (clicked) {
      setDraggedNode(clicked)
    } else {
      setIsPanning(true)
      setPanStart({ x: e.clientX - pan.x, y: e.clientY - pan.y })
    }
  }

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const { x, y, screenX, screenY } = getCanvasCoords(e)

    if (draggedNode) {
      setNodes((prev) =>
        prev.map((n) => (n.id === draggedNode.id ? { ...n, x, y } : n))
      )
    } else if (isPanning) {
      setPan({ x: e.clientX - panStart.x, y: e.clientY - panStart.y })
    } else {
      const hovered = nodes.find((n) => Math.hypot(n.x - x, n.y - y) <= n.radius)
      if (hovered) {
        setHoveredNode(hovered)
        setHoverPos({ x: screenX + 15, y: screenY + 15 })
      } else {
        setHoveredNode(null)
        setHoverPos(null)
      }
    }
  }

  const handleMouseUp = () => {
    setDraggedNode(null)
    setIsPanning(false)
  }

  const handleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const { x, y } = getCanvasCoords(e)
    const clicked = nodes.find((n) => Math.hypot(n.x - x, n.y - y) <= n.radius)

    if (clicked && clicked.type !== 'product') {
      setSelectedNodeIds((prev) =>
        prev.includes(clicked.id) ? prev.filter((id) => id !== clicked.id) : [...prev, clicked.id]
      )
    }
  }

  const handleZoom = (delta: number) => {
    setZoom((prev) => Math.max(0.5, Math.min(2.5, prev + delta)))
  }

  const handleResetView = () => {
    setZoom(1)
    setPan({ x: 0, y: 0 })
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="lg" fullWidth PaperProps={{ sx: { bgcolor: '#0b1329', color: '#fff', borderRadius: 3 } }}>
      <DialogTitle sx={{ m: 0, p: 2, display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid #1e293b', flexWrap: 'wrap', gap: 1 }}>
        <Stack direction="row" spacing={1.5} alignItems="center">
          <Avatar sx={{ bgcolor: '#3b82f6', width: 36, height: 36 }}>
            <Hub />
          </Avatar>
          <Box>
            <Typography variant="h6" fontWeight="bold" sx={{ color: '#f8fafc' }}>
              Multi-Channel Listing Knowledge Graph
            </Typography>
            <Typography variant="caption" sx={{ color: '#94a3b8' }}>
              Target SKU: <strong style={{ color: '#38bdf8' }}>{graphData?.product?.full_sku || variantSku || 'Select a SKU'}</strong> • {graphData?.product?.variant_name || graphData?.product?.family_name || 'Master Product'}
            </Typography>
          </Box>
        </Stack>

        <Stack direction="row" spacing={1.5} alignItems="center">
          {variantsList && variantsList.length > 0 && (
            <Autocomplete
              size="small"
              options={variantsList}
              getOptionLabel={(v: any) => `${v.full_sku} - ${v.variant_name || v.identity?.family?.base_name || ''}`}
              value={variantsList.find((v) => v.id === activeVariantId) || null}
              onChange={(_, val) => {
                if (val) {
                  setActiveVariantId(val.id)
                  setAiSuggestions([])
                  setSelectedNodeIds([])
                }
              }}
              renderInput={(params) => (
                <TextField
                  {...params}
                  placeholder="Switch SKU..."
                  sx={{
                    width: 260,
                    bgcolor: '#1e293b',
                    borderRadius: 1,
                    '& .MuiInputBase-input': { color: '#fff', fontSize: '0.85rem' },
                    '& .MuiOutlinedInput-notchedOutline': { borderColor: '#334155' },
                    '&:hover .MuiOutlinedInput-notchedOutline': { borderColor: '#3b82f6' },
                  }}
                />
              )}
            />
          )}

          <Button
            variant="contained"
            size="small"
            startIcon={aiScanning ? <CircularProgress size={16} color="inherit" /> : <AutoAwesome />}
            onClick={handleScanAI}
            disabled={aiScanning}
            sx={{
              background: 'linear-gradient(135deg, #a855f7 0%, #6366f1 100%)',
              color: '#fff',
              fontWeight: 'bold',
              '&:hover': { background: 'linear-gradient(135deg, #9333ea 0%, #4f46e5 100%)' },
            }}
          >
            {aiScanning ? 'Scanning...' : 'Scan AI Matches'}
          </Button>
          <IconButton onClick={onClose} sx={{ color: '#94a3b8' }}>
            <Close />
          </IconButton>
        </Stack>
      </DialogTitle>

      <DialogContent sx={{ p: 0, position: 'relative', overflow: 'hidden', height: 560 }}>
        {actionMessage && (
          <Alert
            severity={actionMessage.type}
            onClose={() => setActionMessage(null)}
            sx={{ position: 'absolute', top: 12, left: 16, zIndex: 10, bgcolor: actionMessage.type === 'success' ? '#064e3b' : '#7f1d1d', color: '#fff', '& .MuiAlert-icon': { color: '#fff' } }}
          >
            {actionMessage.text}
          </Alert>
        )}

        {isGraphLoading && (
          <Box sx={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', bgcolor: 'rgba(15, 23, 42, 0.8)', zIndex: 5 }}>
            <CircularProgress color="primary" />
          </Box>
        )}

        {/* Canvas Surface */}
        <canvas
          ref={canvasRef}
          style={{ width: '100%', height: '100%', cursor: isPanning ? 'grabbing' : draggedNode ? 'move' : 'grab' }}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onClick={handleClick}
        />

        {/* Zoom Controls Overlay */}
        <Paper
          elevation={4}
          sx={{
            position: 'absolute',
            bottom: 16,
            left: 16,
            display: 'flex',
            bgcolor: '#1e293b',
            border: '1px solid #334155',
            borderRadius: 2,
            p: 0.5,
          }}
        >
          <IconButton size="small" onClick={() => handleZoom(0.15)} sx={{ color: '#94a3b8' }}>
            <ZoomIn fontSize="small" />
          </IconButton>
          <IconButton size="small" onClick={() => handleZoom(-0.15)} sx={{ color: '#94a3b8' }}>
            <ZoomOut fontSize="small" />
          </IconButton>
          <IconButton size="small" onClick={handleResetView} sx={{ color: '#94a3b8' }}>
            <RestartAlt fontSize="small" />
          </IconButton>
        </Paper>

        {/* Legend Overlay */}
        <Paper
          elevation={4}
          sx={{
            position: 'absolute',
            top: 16,
            right: 16,
            bgcolor: 'rgba(30, 41, 59, 0.9)',
            border: '1px solid #334155',
            borderRadius: 2,
            p: 1.5,
            minWidth: 160,
          }}
        >
          <Typography variant="caption" fontWeight="bold" sx={{ color: '#94a3b8', display: 'block', mb: 1 }}>
            GRAPH LEGEND
          </Typography>
          <Stack spacing={0.75}>
            <Stack direction="row" spacing={1} alignItems="center">
              <Box sx={{ width: 12, height: 12, borderRadius: '50%', bgcolor: '#3b82f6' }} />
              <Typography variant="caption" sx={{ color: '#cbd5e1' }}>ERP Master SKU</Typography>
            </Stack>
            <Stack direction="row" spacing={1} alignItems="center">
              <Box sx={{ width: 12, height: 12, borderRadius: '50%', bgcolor: '#96bf48', border: '1px solid #fff' }} />
              <Typography variant="caption" sx={{ color: '#cbd5e1' }}>Locked Listing</Typography>
            </Stack>
            <Stack direction="row" spacing={1} alignItems="center">
              <Box sx={{ width: 12, height: 12, borderRadius: '50%', bgcolor: '#a855f7', border: '1px dashed #c084fc' }} />
              <Typography variant="caption" sx={{ color: '#cbd5e1' }}>AI Suggestion</Typography>
            </Stack>
          </Stack>
        </Paper>

        {/* Hover Tooltip Card */}
        {hoveredNode && hoverPos && (
          <Card
            sx={{
              position: 'fixed',
              left: hoverPos.x,
              top: hoverPos.y,
              zIndex: 1300,
              maxWidth: 320,
              bgcolor: '#1e293b',
              color: '#f8fafc',
              border: '1px solid #475569',
              boxShadow: '0 10px 25px rgba(0,0,0,0.5)',
              pointerEvents: 'none',
            }}
          >
            <CardContent sx={{ p: 1.5, '&:last-child': { pb: 1.5 } }}>
              {hoveredNode.type === 'product' ? (
                <Box>
                  <Typography variant="caption" sx={{ color: '#38bdf8', fontWeight: 'bold' }}>
                    ERP MASTER VARIANT
                  </Typography>
                  <Typography variant="subtitle2" fontWeight="bold">
                    {(hoveredNode.data as ProductNode).full_sku}
                  </Typography>
                  <Typography variant="body2" sx={{ color: '#cbd5e1' }}>
                    {(hoveredNode.data as ProductNode).variant_name || (hoveredNode.data as ProductNode).family_name}
                  </Typography>
                </Box>
              ) : (
                <Box>
                  <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 0.5 }}>
                    <Chip
                      size="small"
                      label={(hoveredNode.data as any).platform}
                      sx={{
                        bgcolor: PLATFORM_META[(hoveredNode.data as any).platform]?.bgColor || '#334155',
                        color: PLATFORM_META[(hoveredNode.data as any).platform]?.color || '#fff',
                        fontWeight: 'bold',
                      }}
                    />
                    {hoveredNode.type === 'ai_candidate' ? (
                      <Chip
                        size="small"
                        icon={<AutoAwesome fontSize="small" />}
                        label={`${Math.round((hoveredNode.confidence || 0) * 100)}% Match`}
                        color="secondary"
                      />
                    ) : (
                      <Chip
                        size="small"
                        label={(hoveredNode.data as ListingNode).sync_status}
                        color={(hoveredNode.data as ListingNode).sync_status === 'SYNCED' ? 'success' : 'warning'}
                      />
                    )}
                  </Stack>

                  <Typography variant="body2" fontWeight="bold" noWrap sx={{ mt: 0.5 }}>
                    {(hoveredNode.data as any).listed_name || 'Untitled Listing'}
                  </Typography>
                  <Typography variant="caption" sx={{ color: '#94a3b8', display: 'block' }}>
                    SKU: {(hoveredNode.data as any).merchant_sku || 'N/A'} • Price: <strong style={{ color: '#4ade80' }}>${(hoveredNode.data as any).listing_price || '0.00'}</strong>
                  </Typography>

                  {hoveredNode.type === 'ai_candidate' && hoveredNode.reasons && (
                    <Box sx={{ mt: 1, pt: 1, borderTop: '1px solid #334155' }}>
                      <Typography variant="caption" sx={{ color: '#c084fc', fontWeight: 'bold' }}>
                        Match Factors:
                      </Typography>
                      <ul style={{ margin: '2px 0 0 16px', padding: 0 }}>
                        {hoveredNode.reasons.map((r, i) => (
                          <li key={i}><Typography variant="caption" sx={{ color: '#e2e8f0' }}>{r}</Typography></li>
                        ))}
                      </ul>
                    </Box>
                  )}
                </Box>
              )}
            </CardContent>
          </Card>
        )}

        {/* Floating Selection Bar */}
        {selectedNodeIds.length > 0 && (
          <Paper
            elevation={6}
            sx={{
              position: 'absolute',
              bottom: 16,
              left: '50%',
              transform: 'translateX(-50%)',
              bgcolor: '#1e293b',
              border: '1px solid #38bdf8',
              borderRadius: 3,
              px: 2,
              py: 1,
              display: 'flex',
              alignItems: 'center',
              gap: 2,
              boxShadow: '0 8px 30px rgba(56, 189, 248, 0.25)',
              zIndex: 20,
            }}
          >
            <Typography variant="body2" sx={{ color: '#f8fafc', fontWeight: 'bold' }}>
              {selectedNodeIds.length} Listing Node{selectedNodeIds.length > 1 ? 's' : ''} Selected
            </Typography>

            {selectedNodeIds.length >= 2 && (
              <Button
                variant="contained"
                size="small"
                startIcon={<CompareArrows />}
                onClick={() => setCompareOpen(true)}
                sx={{ bgcolor: '#38bdf8', color: '#0f172a', fontWeight: 'bold', '&:hover': { bgcolor: '#0ea5e9' } }}
              >
                Compare {selectedNodeIds.length} Listings
              </Button>
            )}

            {selectedNodeIds.length === 1 && selectedNodeIds[0].startsWith('ai-') && (
              <Button
                variant="contained"
                size="small"
                color="secondary"
                startIcon={<Lock />}
                onClick={() => {
                  const listingId = parseInt(selectedNodeIds[0].replace('ai-', ''), 10)
                  if (variantId) {
                    lockMutation.mutate({ listingId, targetVariantId: variantId })
                    setSelectedNodeIds([])
                  }
                }}
              >
                Lock Relationship
              </Button>
            )}

            <Button size="small" onClick={() => setSelectedNodeIds([])} sx={{ color: '#94a3b8' }}>
              Clear
            </Button>
          </Paper>
        )}
      </DialogContent>

      <DialogActions sx={{ p: 2, borderTop: '1px solid #1e293b', justifyContent: 'space-between' }}>
        <Typography variant="caption" sx={{ color: '#64748b' }}>
          💡 Click 2 or more nodes to perform side-by-side comparison • Hover for details • Drag nodes to organize
        </Typography>
        <Button onClick={onClose} variant="outlined" sx={{ color: '#cbd5e1', borderColor: '#475569' }}>
          Done
        </Button>
      </DialogActions>

      {/* Side-by-Side Comparison Modal */}
      <Dialog open={compareOpen} onClose={() => setCompareOpen(false)} maxWidth="md" fullWidth PaperProps={{ sx: { bgcolor: '#0f172a', color: '#fff', borderRadius: 3 } }}>
        <DialogTitle sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #1e293b' }}>
          <Stack direction="row" spacing={1.5} alignItems="center">
            <CompareArrows sx={{ color: '#38bdf8' }} />
            <Typography variant="h6" fontWeight="bold">
              Listing Comparison Matrix ({selectedListingIds.length} Nodes)
            </Typography>
          </Stack>
          <IconButton onClick={() => setCompareOpen(false)} sx={{ color: '#94a3b8' }}>
            <Close />
          </IconButton>
        </DialogTitle>

        <DialogContent sx={{ p: 2 }}>
          {isCompareLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
              <CircularProgress color="primary" />
            </Box>
          ) : compareData ? (
            <TableContainer component={Paper} sx={{ bgcolor: '#1e293b', border: '1px solid #334155' }}>
              <Table size="small">
                <TableHead>
                  <TableRow sx={{ bgcolor: '#0f172a' }}>
                    <TableCell sx={{ color: '#94a3b8', fontWeight: 'bold', width: '25%' }}>Metric / Attribute</TableCell>
                    {compareData.listings.map((l) => (
                      <TableCell key={l.listing_id} sx={{ color: '#38bdf8', fontWeight: 'bold' }}>
                        <Stack direction="row" spacing={1} alignItems="center">
                          <Chip
                            size="small"
                            label={l.platform}
                            sx={{
                              bgcolor: PLATFORM_META[l.platform]?.bgColor || '#334155',
                              color: PLATFORM_META[l.platform]?.color || '#fff',
                              fontWeight: 'bold',
                            }}
                          />
                          <span>#{l.listing_id}</span>
                        </Stack>
                      </TableCell>
                    ))}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {compareData.comparison_fields.map((field) => (
                    <TableRow key={field.key} sx={{ '&:nth-of-type(odd)': { bgcolor: 'rgba(255,255,255,0.02)' } }}>
                      <TableCell sx={{ color: '#cbd5e1', fontWeight: 'bold' }}>{field.label}</TableCell>
                      {compareData.listings.map((l) => {
                        const val = field.values[String(l.listing_id)]
                        return (
                          <TableCell key={l.listing_id} sx={{ color: '#f8fafc' }}>
                            {field.key === 'listing_price' && val !== null ? (
                              <strong style={{ color: '#4ade80' }}>${val}</strong>
                            ) : field.key === 'sync_status' ? (
                              <Chip size="small" label={val || 'PENDING'} color={val === 'SYNCED' ? 'success' : 'warning'} />
                            ) : (
                              val ?? <span style={{ color: '#64748b' }}>—</span>
                            )}
                          </TableCell>
                        )
                      })}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          ) : (
            <Alert severity="info">No comparison data returned.</Alert>
          )}
        </DialogContent>

        <DialogActions sx={{ p: 2, borderTop: '1px solid #1e293b' }}>
          <Button onClick={() => setCompareOpen(false)} variant="contained" sx={{ bgcolor: '#38bdf8', color: '#0f172a', fontWeight: 'bold' }}>
            Close Comparison
          </Button>
        </DialogActions>
      </Dialog>
    </Dialog>
  )
}

export default ListingGraphModal


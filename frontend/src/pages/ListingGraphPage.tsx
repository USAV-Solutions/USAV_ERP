import React, { useState, useEffect, useRef, useMemo } from 'react'
import {
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
  Stack,
  Card,
  CardContent,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Tooltip,
} from '@mui/material'
import {
  Hub,
  AutoAwesome,
  CompareArrows,
  ZoomIn,
  ZoomOut,
  RestartAlt,
  Search,
  Close,
  Extension,
  Inventory2,
  CheckCircle,
} from '@mui/icons-material'
import { useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axiosClient from '../api/axiosClient'
import { CATALOG, LISTINGS } from '../api/endpoints'
import VariantSearchAutocomplete from '../components/common/VariantSearchAutocomplete'
import type { VariantSearchResult } from '../types/orders'
import type {
  GraphTopologyResponse,
  ListingNode,
  ProductNode,
  AISuggestResponse,
  AISuggestion,
  LockRelationshipResponse,
  CompareResponse,
  Platform,
  RelationshipType,
} from '../types/inventory'

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

const RELATIONSHIP_META: Record<string, { label: string; color: string; icon: string; borderStyle: string }> = {
  EXACT: { label: 'Exact Listing', color: '#38bdf8', icon: '🎯', borderStyle: 'solid' },
  ACCESSORY: { label: 'Accessory', color: '#10b981', icon: '🔌', borderStyle: 'dashed' },
  BUNDLE: { label: 'Bundle', color: '#f59e0b', icon: '📦', borderStyle: 'dashed' },
  PART: { label: 'Part / Component', color: '#f97316', icon: '⚙️', borderStyle: 'dashed' },
  RELATED_PRODUCT: { label: 'Sibling Variant', color: '#818cf8', icon: '🔗', borderStyle: 'solid' },
}

interface CanvasNode {
  id: string
  type: 'product' | 'listing' | 'related_product' | 'ai_candidate'
  x: number
  y: number
  baseX: number
  baseY: number
  radius: number
  relationship_type: RelationshipType
  data: ProductNode | ListingNode | (AISuggestion & { platform: Platform })
  confidence?: number
  reasons?: string[]
  phase: number
}

interface CanvasEdge {
  source: string
  target: string
  type: 'locked' | 'suggested' | 'related'
  relationship_type: RelationshipType
  confidence?: number
}

export default function ListingGraphPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()

  const containerRef = useRef<HTMLDivElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const animFrameRef = useRef<number | null>(null)

  // Selected variant state
  const variantIdParam = searchParams.get('variantId')
  const initialVariantId = variantIdParam ? parseInt(variantIdParam, 10) : null
  const [selectedVariant, setSelectedVariant] = useState<VariantSearchResult | null>(null)
  const activeVariantId = selectedVariant?.id || initialVariantId

  // Fetch variant details if navigated with variantId param but selectedVariant is null
  const { data: initialVariantData } = useQuery({
    queryKey: ['variant-by-id', initialVariantId],
    queryFn: async () => {
      const resp = await axiosClient.get(CATALOG.VARIANT(initialVariantId!))
      const v = resp.data
      return {
        id: v.id,
        full_sku: v.full_sku,
        product_name: v.variant_name || v.identity?.family?.base_name || v.full_sku,
        variant_name: v.variant_name,
        color_code: v.color_code,
        condition_code: v.condition_code,
        generated_upis_h: v.identity?.generated_upis_h,
      } as VariantSearchResult
    },
    enabled: !!initialVariantId && !selectedVariant,
  })

  useEffect(() => {
    if (initialVariantData && !selectedVariant) {
      setSelectedVariant(initialVariantData)
    }
  }, [initialVariantData, selectedVariant])

  // Canvas visualizer state
  const nodesRef = useRef<CanvasNode[]>([])
  const edgesRef = useRef<CanvasEdge[]>([])
  const [hoveredNode, setHoveredNode] = useState<CanvasNode | null>(null)
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([])
  const [hoverPos, setHoverPos] = useState<{ x: number; y: number } | null>(null)
  const [draggedNode, setDraggedNode] = useState<CanvasNode | null>(null)
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [isPanning, setIsPanning] = useState(false)
  const [panStart, setPanStart] = useState({ x: 0, y: 0 })

  // Feature states
  const [compareOpen, setCompareOpen] = useState(false)
  const [aiScanning, setAiScanning] = useState(false)
  const [aiSuggestions, setAiSuggestions] = useState<AISuggestion[]>([])
  const [actionMessage, setActionMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  // 1. Fetch graph topology
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
    enabled: !!activeVariantId,
  })

  // 2. Lock relationship mutation
  const lockMutation = useMutation({
    mutationFn: async ({
      listingId,
      variantId,
      relationshipType = 'EXACT',
    }: {
      listingId: number
      variantId: number
      relationshipType?: RelationshipType
    }) => {
      const resp = await axiosClient.post(LISTINGS.LOCK_RELATIONSHIP, {
        listing_id: listingId,
        variant_id: variantId,
        relationship_type: relationshipType,
        enrich_metadata: true,
      })
      return resp.data as LockRelationshipResponse
    },
    onSuccess: (data) => {
      setActionMessage({
        type: 'success',
        text: `Successfully locked listing as ${data.relationship_type}!`,
      })
      queryClient.invalidateQueries({ queryKey: ['listing-graph', activeVariantId] })
      queryClient.invalidateQueries({ queryKey: ['listings'] })
      setAiSuggestions((prev) => prev.filter((s) => s.listing_id !== data.listing_id))
      setSelectedNodeIds([])
    },
    onError: (err: any) => {
      setActionMessage({
        type: 'error',
        text: err?.response?.data?.detail || 'Failed to lock relationship',
      })
    },
  })

  // 3. Compare listings query
  const { data: compareData, isLoading: isCompareLoading } = useQuery<CompareResponse>({
    queryKey: ['compare-listings', selectedNodeIds],
    queryFn: async () => {
      const numericIds = selectedNodeIds
        .filter((id) => id.startsWith('listing-') || id.startsWith('ai-'))
        .map((id) => parseInt(id.replace('listing-', '').replace('ai-', ''), 10))
      const resp = await axiosClient.post(LISTINGS.COMPARE, { listing_ids: numericIds })
      return resp.data
    },
    enabled: compareOpen && selectedNodeIds.length >= 2,
  })

  // 4. Scan AI Matches function (Prioritized Scan)
  const handleScanAI = async () => {
    if (!activeVariantId) return
    setAiScanning(true)
    setActionMessage(null)
    try {
      const resp = await axiosClient.post<AISuggestResponse>(LISTINGS.SUGGEST, {
        variant_id: activeVariantId,
        limit: 8,
        include_linked: false,
      })
      const suggestions = resp.data.suggestions || []
      setAiSuggestions(suggestions)
      if (suggestions.length === 0) {
        setActionMessage({
          type: 'success',
          text: 'AI Scan complete: No unlinked candidate listings found for this product.',
        })
      } else {
        setActionMessage({
          type: 'success',
          text: `AI Scan complete: Found ${suggestions.length} candidate listings with relationship classifications!`,
        })
      }
    } catch (err: any) {
      setActionMessage({
        type: 'error',
        text: err?.response?.data?.detail || 'AI suggestion scan failed',
      })
    } finally {
      setAiScanning(false)
    }
  }

  // 5. Layout calculation
  useEffect(() => {
    if (!graphData && !selectedVariant) {
      nodesRef.current = []
      edgesRef.current = []
      return
    }

    const canvas = canvasRef.current
    const width = canvas ? canvas.clientWidth : 1000
    const height = canvas ? canvas.clientHeight : 700
    const cx = width / 2
    const cy = height / 2

    const newNodes: CanvasNode[] = []
    const newEdges: CanvasEdge[] = []

    // Center Master Product Node
    const centerProduct = graphData?.product || {
      variant_id: selectedVariant!.id,
      full_sku: selectedVariant!.full_sku,
      variant_name: selectedVariant!.product_name,
      color_code: selectedVariant!.color_code,
      condition_code: selectedVariant!.condition_code,
    }

    newNodes.push({
      id: 'product',
      type: 'product',
      x: cx,
      y: cy,
      baseX: cx,
      baseY: cy,
      radius: 46,
      relationship_type: 'EXACT',
      data: centerProduct,
      phase: 0,
    })

    // Locked Listings
    const listings = graphData?.listings || []
    const totalOrbiters = listings.length + aiSuggestions.length + (graphData?.related_products?.length || 0)
    let orbitIndex = 0

    listings.forEach((listing) => {
      const angle = (orbitIndex / (totalOrbiters || 1)) * Math.PI * 2 - Math.PI / 2
      const radiusDist = 200 + (orbitIndex % 2) * 45
      const lx = cx + Math.cos(angle) * radiusDist
      const ly = cy + Math.sin(angle) * radiusDist
      const relType = listing.relationship_type || 'EXACT'

      newNodes.push({
        id: `listing-${listing.listing_id}`,
        type: 'listing',
        x: lx,
        y: ly,
        baseX: lx,
        baseY: ly,
        radius: 34,
        relationship_type: relType,
        data: listing,
        phase: orbitIndex * 0.9,
      })

      newEdges.push({
        source: 'product',
        target: `listing-${listing.listing_id}`,
        type: 'locked',
        relationship_type: relType,
      })

      orbitIndex++
    })

    // Related Products (Accessories / Bundles / Siblings)
    const relatedProducts = graphData?.related_products || []
    relatedProducts.forEach((relProd) => {
      const angle = (orbitIndex / (totalOrbiters || 1)) * Math.PI * 2 - Math.PI / 2
      const radiusDist = 260 + (orbitIndex % 2) * 35
      const rx = cx + Math.cos(angle) * radiusDist
      const ry = cy + Math.sin(angle) * radiusDist
      const isAcc = relProd.identity_type === 'P' || relProd.identity_type === 'A'
      const isBun = relProd.identity_type === 'B' || relProd.identity_type === 'K'
      const relType: RelationshipType = isAcc ? 'ACCESSORY' : isBun ? 'BUNDLE' : 'RELATED_PRODUCT'

      newNodes.push({
        id: `related-product-${relProd.variant_id}`,
        type: 'related_product',
        x: rx,
        y: ry,
        baseX: rx,
        baseY: ry,
        radius: 30,
        relationship_type: relType,
        data: relProd,
        phase: orbitIndex * 0.9,
      })

      newEdges.push({
        source: 'product',
        target: `related-product-${relProd.variant_id}`,
        type: 'related',
        relationship_type: relType,
      })

      orbitIndex++
    })

    // AI Suggestions (Purple Candidate Nodes)
    aiSuggestions.forEach((sug) => {
      const angle = (orbitIndex / (totalOrbiters || 1)) * Math.PI * 2 - Math.PI / 2
      const radiusDist = 220 + (orbitIndex % 2) * 50
      const sx = cx + Math.cos(angle) * radiusDist
      const sy = cy + Math.sin(angle) * radiusDist
      const relType = sug.relationship_type || 'EXACT'

      newNodes.push({
        id: `ai-${sug.listing_id}`,
        type: 'ai_candidate',
        x: sx,
        y: sy,
        baseX: sx,
        baseY: sy,
        radius: 34,
        relationship_type: relType,
        confidence: sug.confidence,
        reasons: sug.reasons,
        data: sug,
        phase: orbitIndex * 0.9,
      })

      newEdges.push({
        source: 'product',
        target: `ai-${sug.listing_id}`,
        type: 'suggested',
        relationship_type: relType,
        confidence: sug.confidence,
      })

      orbitIndex++
    })

    nodesRef.current = newNodes
    edgesRef.current = newEdges
  }, [graphData, selectedVariant, aiSuggestions])

  // 6. Smooth Animation & Canvas Drawing Loop (requestAnimationFrame)
  useEffect(() => {
    let isRunning = true

    const render = (time: number) => {
      if (!isRunning) return
      const canvas = canvasRef.current
      if (!canvas) return
      const ctx = canvas.getContext('2d')
      if (!ctx) return

      // Handle retina displays
      const dpr = window.devicePixelRatio || 1
      if (canvas.width !== canvas.clientWidth * dpr || canvas.height !== canvas.clientHeight * dpr) {
        canvas.width = canvas.clientWidth * dpr
        canvas.height = canvas.clientHeight * dpr
      }

      ctx.save()
      ctx.scale(dpr, dpr)
      ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight)

      // Apply Pan & Zoom
      ctx.save()
      ctx.translate(pan.x, pan.y)
      ctx.scale(zoom, zoom)

      // Ambient Space Radial Glow (Soft illumination)
      const cx = canvas.clientWidth / 2
      const cy = canvas.clientHeight / 2
      const bgGrad = ctx.createRadialGradient(cx, cy, 50, cx, cy, 600)
      bgGrad.addColorStop(0, 'rgba(30, 58, 138, 0.12)')
      bgGrad.addColorStop(0.6, 'rgba(15, 23, 42, 0.04)')
      bgGrad.addColorStop(1, 'rgba(0, 0, 0, 0)')
      ctx.fillStyle = bgGrad
      ctx.fillRect(-1000, -1000, canvas.clientWidth + 2000, canvas.clientHeight + 2000)

      // Update gentle organic floating physics for nodes
      const t = time * 0.001
      const currentNodes = nodesRef.current
      currentNodes.forEach((node) => {
        if (draggedNode && draggedNode.id === node.id) {
          // Keep dragged position
        } else if (node.type === 'product') {
          // Central breathing
          const breathe = Math.sin(t * 1.5) * 1.5
          node.x = node.baseX
          node.y = node.baseY + breathe
        } else {
          // Orbiting sinusoidal floating in space
          const floatX = Math.sin(t * 1.2 + node.phase) * 5.5
          const floatY = Math.cos(t * 0.9 + node.phase * 1.3) * 5.5
          node.x = node.baseX + floatX
          node.y = node.baseY + floatY
        }
      })

      const nodeMap = new Map<string, CanvasNode>()
      currentNodes.forEach((n) => nodeMap.set(n.id, n))

      // --- Draw Edges ---
      const currentEdges = edgesRef.current
      currentEdges.forEach((edge) => {
        const sourceNode = nodeMap.get(edge.source)
        const targetNode = nodeMap.get(edge.target)
        if (!sourceNode || !targetNode) return

        const relMeta = RELATIONSHIP_META[edge.relationship_type] || RELATIONSHIP_META.EXACT
        ctx.beginPath()
        ctx.moveTo(sourceNode.x, sourceNode.y)
        ctx.lineTo(targetNode.x, targetNode.y)

        if (edge.type === 'suggested') {
          // AI Candidate Edge: Violet dashed with pulse
          ctx.setLineDash([6, 6])
          ctx.lineDashOffset = -t * 15
          ctx.strokeStyle = 'rgba(192, 132, 252, 0.85)'
          ctx.lineWidth = 2
          ctx.shadowColor = '#c084fc'
          ctx.shadowBlur = 10
        } else if (edge.type === 'related') {
          // Related Product / Accessory / Sibling Edge
          ctx.setLineDash([4, 4])
          ctx.lineDashOffset = 0
          ctx.strokeStyle = relMeta.color
          ctx.lineWidth = 2
          ctx.shadowColor = relMeta.color
          ctx.shadowBlur = 8
        } else {
          // Locked Platform Listing Edge
          ctx.setLineDash([])
          ctx.strokeStyle = relMeta.color
          ctx.lineWidth = 2.5
          ctx.shadowColor = relMeta.color
          ctx.shadowBlur = 10
        }
        ctx.stroke()
        ctx.setLineDash([])
        ctx.shadowBlur = 0

        // Midpoint Badges on Edge
        const midX = (sourceNode.x + targetNode.x) / 2
        const midY = (sourceNode.y + targetNode.y) / 2

        if (edge.type === 'suggested' && edge.confidence !== undefined) {
          // AI Confidence & Relationship Pill
          const confText = `✨ ${(edge.confidence * 100).toFixed(0)}% ${edge.relationship_type}`
          ctx.font = 'bold 10px Inter, sans-serif'
          const tw = ctx.measureText(confText).width + 14
          ctx.fillStyle = 'rgba(24, 15, 45, 0.92)'
          ctx.strokeStyle = '#c084fc'
          ctx.lineWidth = 1.2
          ctx.beginPath()
          ctx.roundRect(midX - tw / 2, midY - 10, tw, 20, 10)
          ctx.fill()
          ctx.stroke()

          ctx.fillStyle = '#f3e8ff'
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText(confText, midX, midY)
        } else if (edge.relationship_type !== 'EXACT') {
          // Relationship Type Pill (ACCESSORY, BUNDLE, PART)
          const badgeText = `${relMeta.icon} ${relMeta.label}`
          ctx.font = 'bold 9px Inter, sans-serif'
          const tw = ctx.measureText(badgeText).width + 12
          ctx.fillStyle = 'rgba(15, 23, 42, 0.92)'
          ctx.strokeStyle = relMeta.color
          ctx.lineWidth = 1.2
          ctx.beginPath()
          ctx.roundRect(midX - tw / 2, midY - 9, tw, 18, 9)
          ctx.fill()
          ctx.stroke()

          ctx.fillStyle = relMeta.color
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText(badgeText, midX, midY)
        }
      })

      // --- Draw Nodes ---
      currentNodes.forEach((node) => {
        const isHovered = hoveredNode?.id === node.id
        const isSelected = selectedNodeIds.includes(node.id)
        const relMeta = RELATIONSHIP_META[node.relationship_type] || RELATIONSHIP_META.EXACT

        // Selection / Hover Ring
        if (isSelected || isHovered) {
          ctx.beginPath()
          ctx.arc(node.x, node.y, node.radius + (isSelected ? 8 : 5), 0, Math.PI * 2)
          ctx.strokeStyle = isSelected ? '#38bdf8' : '#fbbf24'
          ctx.lineWidth = isSelected ? 3 : 2
          ctx.shadowColor = isSelected ? '#38bdf8' : '#fbbf24'
          ctx.shadowBlur = 16
          ctx.stroke()
          ctx.shadowBlur = 0
        }

        ctx.beginPath()
        ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2)

        if (node.type === 'product') {
          // Central ERP Master Node
          const grad = ctx.createRadialGradient(node.x, node.y, 4, node.x, node.y, node.radius)
          grad.addColorStop(0, '#1e3a8a')
          grad.addColorStop(1, '#0f172a')
          ctx.fillStyle = grad
          ctx.shadowColor = '#38bdf8'
          ctx.shadowBlur = 24
          ctx.fill()
          ctx.strokeStyle = '#38bdf8'
          ctx.lineWidth = 3
          ctx.stroke()
          ctx.shadowBlur = 0

          // Central Label
          ctx.fillStyle = '#ffffff'
          ctx.font = 'bold 12px Inter, sans-serif'
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText('ERP MASTER', node.x, node.y - 7)

          ctx.fillStyle = '#94a3b8'
          ctx.font = '10px monospace'
          const sku = (node.data as ProductNode).full_sku || ''
          ctx.fillText(sku.length > 13 ? sku.substring(0, 11) + '..' : sku, node.x, node.y + 9)
        } else if (node.type === 'related_product') {
          // Sibling / Accessory / Bundle Product Node
          const pData = node.data as ProductNode
          const grad = ctx.createRadialGradient(node.x, node.y, 2, node.x, node.y, node.radius)
          grad.addColorStop(0, '#1e293b')
          grad.addColorStop(1, '#0f172a')
          ctx.fillStyle = grad
          ctx.fill()

          ctx.strokeStyle = relMeta.color
          ctx.lineWidth = 2
          ctx.setLineDash([3, 3])
          ctx.stroke()
          ctx.setLineDash([])

          ctx.fillStyle = '#f8fafc'
          ctx.font = 'bold 9px Inter, sans-serif'
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText(relMeta.icon, node.x, node.y - 6)

          ctx.fillStyle = '#cbd5e1'
          ctx.font = '8px monospace'
          const rSku = pData.full_sku || ''
          ctx.fillText(rSku.length > 10 ? rSku.substring(0, 8) + '..' : rSku, node.x, node.y + 7)
        } else if (node.type === 'ai_candidate') {
          // AI Candidate Node
          const aiData = node.data as AISuggestion
          const pMeta = PLATFORM_META[aiData.platform] || { label: aiData.platform, color: '#c084fc', icon: '✨' }

          const grad = ctx.createRadialGradient(node.x, node.y, 2, node.x, node.y, node.radius)
          grad.addColorStop(0, '#3b0764')
          grad.addColorStop(1, '#1e1b4b')
          ctx.fillStyle = grad
          ctx.fill()

          ctx.setLineDash([4, 4])
          ctx.lineDashOffset = -t * 10
          ctx.strokeStyle = '#c084fc'
          ctx.lineWidth = 2.5
          ctx.shadowColor = '#c084fc'
          ctx.shadowBlur = 12
          ctx.stroke()
          ctx.setLineDash([])
          ctx.shadowBlur = 0

          ctx.fillStyle = '#ffffff'
          ctx.font = 'bold 10px Inter, sans-serif'
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText(pMeta.label, node.x, node.y - 7)

          ctx.fillStyle = '#e9d5ff'
          ctx.font = 'bold 10px Inter, sans-serif'
          const confPct = `${((node.confidence || 0) * 100).toFixed(0)}%`
          ctx.fillText(`✨ ${confPct}`, node.x, node.y + 8)
        } else {
          // Locked Platform Listing Node
          const lData = node.data as ListingNode
          const pMeta = PLATFORM_META[lData.platform] || { label: lData.platform, color: '#38bdf8', icon: '🛒' }

          const grad = ctx.createRadialGradient(node.x, node.y, 2, node.x, node.y, node.radius)
          grad.addColorStop(0, '#1e293b')
          grad.addColorStop(1, '#0f172a')
          ctx.fillStyle = grad
          ctx.fill()

          ctx.strokeStyle = pMeta.color
          ctx.lineWidth = 2.5
          ctx.shadowColor = pMeta.color
          ctx.shadowBlur = 10
          ctx.stroke()
          ctx.shadowBlur = 0

          // Platform Label
          ctx.fillStyle = '#f8fafc'
          ctx.font = 'bold 10px Inter, sans-serif'
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText(pMeta.label, node.x, node.y - 7)

          // Price Tag
          ctx.fillStyle = '#4ade80'
          ctx.font = 'bold 10px Inter, sans-serif'
          const price = lData.listing_price !== null && lData.listing_price !== undefined ? `$${lData.listing_price.toFixed(0)}` : '--'
          ctx.fillText(price, node.x, node.y + 8)

          // Sync status indicator pip
          ctx.beginPath()
          ctx.arc(node.x + node.radius - 6, node.y - node.radius + 6, 4.5, 0, Math.PI * 2)
          ctx.fillStyle = lData.sync_status === 'SYNCED' ? '#22c55e' : lData.sync_status === 'ERROR' ? '#ef4444' : '#f59e0b'
          ctx.fill()
          ctx.strokeStyle = '#0f172a'
          ctx.lineWidth = 1.5
          ctx.stroke()
        }
      })

      ctx.restore()
      ctx.restore()

      animFrameRef.current = requestAnimationFrame(render)
    }

    animFrameRef.current = requestAnimationFrame(render)

    return () => {
      isRunning = false
      if (animFrameRef.current) {
        cancelAnimationFrame(animFrameRef.current)
      }
    }
  }, [pan, zoom, draggedNode, hoveredNode, selectedNodeIds])

  // Mouse Handlers for Pan, Zoom, Drag, Hover
  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const mouseX = (e.clientX - rect.left - pan.x) / zoom
    const mouseY = (e.clientY - rect.top - pan.y) / zoom

    // Check if clicking a node
    const clickedNode = nodesRef.current.find((n) => {
      const dx = n.x - mouseX
      const dy = n.y - mouseY
      return Math.sqrt(dx * dx + dy * dy) <= n.radius
    })

    if (clickedNode) {
      setDraggedNode(clickedNode)
      if (clickedNode.type !== 'product') {
        if (e.shiftKey) {
          setSelectedNodeIds((prev) =>
            prev.includes(clickedNode.id) ? prev.filter((id) => id !== clickedNode.id) : [...prev, clickedNode.id]
          )
        } else {
          setSelectedNodeIds([clickedNode.id])
        }
      }
    } else {
      setIsPanning(true)
      setPanStart({ x: e.clientX - pan.x, y: e.clientY - pan.y })
    }
  }

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()

    if (isPanning) {
      setPan({ x: e.clientX - panStart.x, y: e.clientY - panStart.y })
      return
    }

    const mouseX = (e.clientX - rect.left - pan.x) / zoom
    const mouseY = (e.clientY - rect.top - pan.y) / zoom

    if (draggedNode) {
      draggedNode.baseX = mouseX
      draggedNode.baseY = mouseY
      draggedNode.x = mouseX
      draggedNode.y = mouseY
      return
    }

    // Hover inspection
    const hovered = nodesRef.current.find((n) => {
      const dx = n.x - mouseX
      const dy = n.y - mouseY
      return Math.sqrt(dx * dx + dy * dy) <= n.radius
    })

    if (hovered) {
      setHoveredNode(hovered)
      setHoverPos({ x: e.clientX - rect.left + 15, y: e.clientY - rect.top + 15 })
    } else {
      setHoveredNode(null)
      setHoverPos(null)
    }
  }

  const handleMouseUp = () => {
    setDraggedNode(null)
    setIsPanning(false)
  }

  const handleWheel = (e: React.WheelEvent<HTMLCanvasElement>) => {
    e.preventDefault()
    const zoomFactor = e.deltaY < 0 ? 1.08 : 0.92
    setZoom((prev) => Math.min(2.5, Math.max(0.4, prev * zoomFactor)))
  }

  const handleResetView = () => {
    setZoom(1)
    setPan({ x: 0, y: 0 })
  }

  // Active selected candidate node for bottom action bar
  const selectedNode = useMemo(() => {
    if (selectedNodeIds.length !== 1) return null
    return nodesRef.current.find((n) => n.id === selectedNodeIds[0]) || null
  }, [selectedNodeIds])

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        height: 'calc(100vh - 70px)',
        bgcolor: '#080c14',
        color: '#f8fafc',
        overflow: 'hidden',
      }}
    >
      {/* Top Query & Search Header */}
      <Paper
        elevation={3}
        sx={{
          p: 1.5,
          px: 3,
          bgcolor: 'rgba(15, 23, 42, 0.95)',
          backdropFilter: 'blur(12px)',
          borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 2,
          zIndex: 10,
        }}
      >
        <Stack direction="row" alignItems="center" spacing={2} sx={{ flex: 1, maxWidth: 650 }}>
          <Hub sx={{ color: '#38bdf8', fontSize: 28 }} />
          <Box sx={{ flex: 1 }}>
            <VariantSearchAutocomplete
              value={selectedVariant}
              onChange={(result) => {
                setSelectedVariant(result)
                if (result) {
                  setSearchParams({ variantId: result.id.toString() })
                  setAiSuggestions([])
                  setSelectedNodeIds([])
                } else {
                  setSearchParams({})
                }
              }}
              placeholder="Query product by SKU, Name, or UPIS..."
            />
          </Box>
        </Stack>

        {/* Action Controls */}
        <Stack direction="row" alignItems="center" spacing={1.5}>
          {selectedNodeIds.length >= 2 && (
            <Button
              variant="outlined"
              color="primary"
              size="small"
              startIcon={<CompareArrows />}
              onClick={() => setCompareOpen(true)}
              sx={{ borderColor: '#38bdf8', color: '#38bdf8', textTransform: 'none', fontWeight: 600 }}
            >
              Compare ({selectedNodeIds.length}) Listings
            </Button>
          )}

          <Button
            variant="contained"
            size="small"
            startIcon={aiScanning ? <CircularProgress size={16} color="inherit" /> : <AutoAwesome />}
            disabled={aiScanning || !activeVariantId}
            onClick={handleScanAI}
            sx={{
              background: 'linear-gradient(135deg, #a855f7 0%, #ec4899 100%)',
              color: '#ffffff',
              textTransform: 'none',
              fontWeight: 600,
              boxShadow: '0 4px 14px rgba(168, 85, 247, 0.4)',
              '&:hover': {
                background: 'linear-gradient(135deg, #9333ea 0%, #db2777 100%)',
              },
            }}
          >
            {aiScanning ? 'Scanning Gemini AI...' : 'Scan AI Matches'}
          </Button>

          <Stack direction="row" sx={{ bgcolor: 'rgba(255, 255, 255, 0.05)', borderRadius: 1 }}>
            <IconButton size="small" onClick={() => setZoom((z) => Math.min(2.5, z * 1.15))} sx={{ color: '#94a3b8' }}>
              <ZoomIn fontSize="small" />
            </IconButton>
            <IconButton size="small" onClick={() => setZoom((z) => Math.max(0.4, z * 0.85))} sx={{ color: '#94a3b8' }}>
              <ZoomOut fontSize="small" />
            </IconButton>
            <IconButton size="small" onClick={handleResetView} sx={{ color: '#94a3b8' }}>
              <RestartAlt fontSize="small" />
            </IconButton>
          </Stack>
        </Stack>
      </Paper>

      {/* Alert Notifications */}
      {actionMessage && (
        <Box sx={{ px: 3, pt: 1, zIndex: 10 }}>
          <Alert
            severity={actionMessage.type}
            onClose={() => setActionMessage(null)}
            sx={{
              bgcolor: actionMessage.type === 'success' ? 'rgba(6, 78, 59, 0.85)' : 'rgba(127, 29, 29, 0.85)',
              color: '#ffffff',
              border: `1px solid ${actionMessage.type === 'success' ? '#10b981' : '#ef4444'}`,
            }}
          >
            {actionMessage.text}
          </Alert>
        </Box>
      )}

      {/* Main Canvas Area */}
      <Box
        ref={containerRef}
        sx={{
          flex: 1,
          position: 'relative',
          overflow: 'hidden',
          cursor: isPanning ? 'grabbing' : 'grab',
          background: 'radial-gradient(ellipse at center, #0f172a 0%, #080c14 100%)',
        }}
      >
        {isGraphLoading && (
          <Box
            sx={{
              position: 'absolute',
              top: '50%',
              left: '50%',
              transform: 'translate(-50%, -50%)',
              zIndex: 5,
              textAlign: 'center',
            }}
          >
            <CircularProgress size={40} sx={{ color: '#38bdf8' }} />
            <Typography variant="body2" sx={{ color: '#94a3b8', mt: 1.5 }}>
              Loading Knowledge Graph...
            </Typography>
          </Box>
        )}

        {!activeVariantId && !isGraphLoading && (
          <Box
            sx={{
              position: 'absolute',
              top: '50%',
              left: '50%',
              transform: 'translate(-50%, -50%)',
              textAlign: 'center',
              maxWidth: 420,
              p: 4,
              bgcolor: 'rgba(15, 23, 42, 0.8)',
              backdropFilter: 'blur(8px)',
              borderRadius: 3,
              border: '1px solid rgba(255, 255, 255, 0.08)',
            }}
          >
            <Search sx={{ fontSize: 48, color: '#38bdf8', mb: 1 }} />
            <Typography variant="h6" sx={{ fontWeight: 600, color: '#f8fafc' }}>
              Search for an ERP Product
            </Typography>
            <Typography variant="body2" sx={{ color: '#94a3b8', mt: 1 }}>
              Type any SKU (e.g. <code>00005-BK</code>, <code>00738</code>) or product name above to visualize its live multi-channel listings, bundles, and accessories.
            </Typography>
          </Box>
        )}

        <canvas
          ref={canvasRef}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onWheel={handleWheel}
          style={{ width: '100%', height: '100%', display: 'block' }}
        />

        {/* Hover Tooltip Card */}
        {hoveredNode && hoverPos && (
          <Card
            sx={{
              position: 'absolute',
              left: hoverPos.x,
              top: hoverPos.y,
              maxWidth: 320,
              bgcolor: 'rgba(15, 23, 42, 0.95)',
              backdropFilter: 'blur(12px)',
              border: '1px solid rgba(255, 255, 255, 0.15)',
              borderRadius: 2,
              boxShadow: '0 8px 32px rgba(0, 0, 0, 0.6)',
              pointerEvents: 'none',
              zIndex: 20,
            }}
          >
            <CardContent sx={{ p: 1.5, '&:last-child': { pb: 1.5 } }}>
              <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
                {hoveredNode.type === 'ai_candidate' ? (
                  <Chip
                    size="small"
                    label={`✨ ${((hoveredNode.confidence || 0) * 100).toFixed(0)}% Match`}
                    sx={{ bgcolor: '#7e22ce', color: '#f3e8ff', fontWeight: 600, fontSize: 11 }}
                  />
                ) : null}
                <Chip
                  size="small"
                  label={hoveredNode.relationship_type}
                  sx={{
                    bgcolor: 'rgba(255, 255, 255, 0.08)',
                    color: RELATIONSHIP_META[hoveredNode.relationship_type]?.color || '#38bdf8',
                    fontWeight: 600,
                    fontSize: 10,
                  }}
                />
              </Stack>

              <Typography variant="body2" sx={{ fontWeight: 600, color: '#f8fafc', fontSize: 12 }}>
                {'listed_name' in hoveredNode.data
                  ? (hoveredNode.data as ListingNode).listed_name || (hoveredNode.data as ListingNode).merchant_sku
                  : (hoveredNode.data as ProductNode).variant_name || (hoveredNode.data as ProductNode).full_sku}
              </Typography>

              {hoveredNode.reasons && hoveredNode.reasons.length > 0 && (
                <Box sx={{ mt: 1, pt: 1, borderTop: '1px solid rgba(255, 255, 255, 0.08)' }}>
                  <Typography variant="caption" sx={{ color: '#94a3b8', display: 'block', mb: 0.5 }}>
                    Match Reasoning:
                  </Typography>
                  {hoveredNode.reasons.map((r, i) => (
                    <Typography key={i} variant="caption" sx={{ color: '#cbd5e1', display: 'block', fontSize: 10.5 }}>
                      • {r}
                    </Typography>
                  ))}
                </Box>
              )}

              <Typography variant="caption" sx={{ color: '#38bdf8', display: 'block', mt: 1, fontStyle: 'italic' }}>
                Click node to select & lock relationship
              </Typography>
            </CardContent>
          </Card>
        )}

        {/* Floating Bottom Action Bar with Multi-Relationship Lock */}
        {selectedNode && (selectedNode.type === 'ai_candidate' || selectedNode.type === 'listing') && (
          <Paper
            elevation={6}
            sx={{
              position: 'absolute',
              bottom: 24,
              left: '50%',
              transform: 'translateX(-50%)',
              bgcolor: 'rgba(15, 23, 42, 0.95)',
              backdropFilter: 'blur(16px)',
              border: '1px solid rgba(255, 255, 255, 0.15)',
              borderRadius: 3,
              p: 2,
              px: 3,
              display: 'flex',
              alignItems: 'center',
              gap: 2.5,
              zIndex: 30,
              boxShadow: '0 12px 40px rgba(0, 0, 0, 0.7)',
              maxWidth: '90%',
            }}
          >
            <Box sx={{ maxWidth: 380 }}>
              <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 0.5 }}>
                <Chip
                  size="small"
                  label={
                    'platform' in selectedNode.data
                      ? (selectedNode.data as ListingNode).platform
                      : 'Listing'
                  }
                  sx={{ bgcolor: '#1e3a8a', color: '#93c5fd', fontWeight: 600, fontSize: 10.5 }}
                />
                {selectedNode.confidence !== undefined && (
                  <Chip
                    size="small"
                    label={`✨ ${(selectedNode.confidence * 100).toFixed(0)}% Match`}
                    sx={{ bgcolor: '#7e22ce', color: '#f3e8ff', fontWeight: 600, fontSize: 10.5 }}
                  />
                )}
              </Stack>
              <Typography variant="body2" sx={{ fontWeight: 600, color: '#f8fafc', fontSize: 12 }} noWrap>
                {'listed_name' in selectedNode.data ? (selectedNode.data as ListingNode).listed_name : ''}
              </Typography>
            </Box>

            {/* Lock with chosen relationship */}
            <Stack direction="row" spacing={1}>
              <Tooltip title="Lock as direct 1:1 physical item listing">
                <Button
                  variant="contained"
                  size="small"
                  startIcon={<CheckCircle />}
                  onClick={() => {
                    const lid = parseInt(selectedNode.id.replace('ai-', '').replace('listing-', ''), 10)
                    lockMutation.mutate({
                      listingId: lid,
                      variantId: activeVariantId!,
                      relationshipType: 'EXACT',
                    })
                  }}
                  sx={{
                    bgcolor: '#0284c7',
                    textTransform: 'none',
                    fontWeight: 600,
                    fontSize: 11,
                    '&:hover': { bgcolor: '#0369a1' },
                  }}
                >
                  Lock Exact
                </Button>
              </Tooltip>

              <Tooltip title="Lock as bundle variation containing this product">
                <Button
                  variant="contained"
                  size="small"
                  startIcon={<Inventory2 />}
                  onClick={() => {
                    const lid = parseInt(selectedNode.id.replace('ai-', '').replace('listing-', ''), 10)
                    lockMutation.mutate({
                      listingId: lid,
                      variantId: activeVariantId!,
                      relationshipType: 'BUNDLE',
                    })
                  }}
                  sx={{
                    bgcolor: '#d97706',
                    textTransform: 'none',
                    fontWeight: 600,
                    fontSize: 11,
                    '&:hover': { bgcolor: '#b45309' },
                  }}
                >
                  Lock Bundle
                </Button>
              </Tooltip>

              <Tooltip title="Lock as compatible accessory (e.g. bluetooth adapter, bracket)">
                <Button
                  variant="contained"
                  size="small"
                  startIcon={<Extension />}
                  onClick={() => {
                    const lid = parseInt(selectedNode.id.replace('ai-', '').replace('listing-', ''), 10)
                    lockMutation.mutate({
                      listingId: lid,
                      variantId: activeVariantId!,
                      relationshipType: 'ACCESSORY',
                    })
                  }}
                  sx={{
                    bgcolor: '#059669',
                    textTransform: 'none',
                    fontWeight: 600,
                    fontSize: 11,
                    '&:hover': { bgcolor: '#047857' },
                  }}
                >
                  Lock Accessory
                </Button>
              </Tooltip>
            </Stack>

            <IconButton size="small" onClick={() => setSelectedNodeIds([])} sx={{ color: '#94a3b8' }}>
              <Close fontSize="small" />
            </IconButton>
          </Paper>
        )}
      </Box>

      {/* Side-by-Side Comparison Dialog */}
      <Dialog
        open={compareOpen}
        onClose={() => setCompareOpen(false)}
        maxWidth="md"
        fullWidth
        PaperProps={{
          sx: {
            bgcolor: '#0f172a',
            color: '#f8fafc',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            borderRadius: 3,
          },
        }}
      >
        <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Stack direction="row" alignItems="center" spacing={1}>
            <CompareArrows sx={{ color: '#38bdf8' }} />
            <Typography variant="h6" sx={{ fontWeight: 600 }}>
              Multi-Listing Side-by-Side Comparison
            </Typography>
          </Stack>
          <IconButton onClick={() => setCompareOpen(false)} sx={{ color: '#94a3b8' }}>
            <Close />
          </IconButton>
        </DialogTitle>

        <DialogContent dividers sx={{ borderColor: 'rgba(255, 255, 255, 0.08)' }}>
          {isCompareLoading ? (
            <Box sx={{ textAlign: 'center', py: 4 }}>
              <CircularProgress size={32} sx={{ color: '#38bdf8' }} />
            </Box>
          ) : compareData ? (
            <TableContainer component={Paper} sx={{ bgcolor: 'transparent', boxShadow: 'none' }}>
              <Table size="small">
                <TableHead>
                  <TableRow sx={{ borderBottom: '1px solid rgba(255, 255, 255, 0.12)' }}>
                    <TableCell sx={{ color: '#94a3b8', fontWeight: 600 }}>Attribute</TableCell>
                    {compareData.listings.map((l) => (
                      <TableCell key={l.listing_id} sx={{ color: '#38bdf8', fontWeight: 600 }}>
                        {l.platform} (#{l.listing_id})
                      </TableCell>
                    ))}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {compareData.comparison_fields.map((field) => (
                    <TableRow key={field.key} sx={{ borderBottom: '1px solid rgba(255, 255, 255, 0.05)' }}>
                      <TableCell sx={{ color: '#94a3b8', fontWeight: 500, fontSize: 12 }}>{field.label}</TableCell>
                      {compareData.listings.map((l) => (
                        <TableCell key={l.listing_id} sx={{ color: '#f8fafc', fontSize: 12 }}>
                          {field.values[l.listing_id.toString()] ?? '--'}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          ) : (
            <Typography variant="body2" sx={{ color: '#94a3b8', textAlign: 'center', py: 2 }}>
              Select 2 or more listing nodes on the canvas to compare.
            </Typography>
          )}
        </DialogContent>

        <DialogActions sx={{ p: 2 }}>
          <Button onClick={() => setCompareOpen(false)} sx={{ color: '#94a3b8', textTransform: 'none' }}>
            Close
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}

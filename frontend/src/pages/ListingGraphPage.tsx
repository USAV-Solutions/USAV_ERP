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
  Handyman,
  Palette,
  TrendingUp,
  Warning,
  DarkMode,
  LightMode,
  CenterFocusStrong,
  ChangeCircle,
  Workspaces,
} from '@mui/icons-material'
import { useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axiosClient from '../api/axiosClient'
import { CATALOG, LISTINGS, ORBIT } from '../api/endpoints'
import VariantSearchAutocomplete from '../components/common/VariantSearchAutocomplete'
import OrbitContextMenu, { type ContextMenuTarget } from '../components/orbit/OrbitContextMenu'
import OrbitBundleKitModal from '../components/orbit/OrbitBundleKitModal'
import OrbitVariantModal from '../components/orbit/OrbitVariantModal'
import OrbitConvertTypeModal from '../components/orbit/OrbitConvertTypeModal'
import OrbitDeepClassifyPanel, {
  type AIDeepClassifyResponse,
  type AIClassifiedComponent,
} from '../components/orbit/OrbitDeepClassifyPanel'
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
  OrbitAnalyticsResponse,
} from '../types/inventory'

export interface BundleParticipation {
  parent_variant_id: number
  parent_sku: string
  parent_name?: string
  parent_type: string
  role: string
  quantity_required: number
  sibling_components: ProductNode[]
}

export interface BundleDiscoveryResponse {
  variant_id: number
  full_sku: string
  participations: BundleParticipation[]
}

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
  BUNDLE_COMPONENT: { label: 'Bundle (B)', color: '#f59e0b', icon: '📦', borderStyle: 'dashed' },
  KIT_COMPONENT: { label: 'Kit (K)', color: '#818cf8', icon: '🧰', borderStyle: 'dashed' },
  PART_LCI: { label: 'Part (P)', color: '#f97316', icon: '⚙️', borderStyle: 'dashed' },
  SIBLING_VARIANT: { label: 'Sibling Variant', color: '#a855f7', icon: '🔗', borderStyle: 'solid' },
  // Backward compatibility
  BUNDLE: { label: 'Bundle (B)', color: '#f59e0b', icon: '📦', borderStyle: 'dashed' },
  PART: { label: 'Part (P)', color: '#f97316', icon: '⚙️', borderStyle: 'dashed' },
  RELATED_PRODUCT: { label: 'Sibling Variant', color: '#a855f7', icon: '🔗', borderStyle: 'solid' },
}

export interface HubData {
  hubId: string
  label: string
  hubType: 'variants' | 'accessory' | 'component' | 'bundle'
  icon: string
  color: string
  count: number
}

interface CanvasNode {
  id: string
  type: 'product' | 'listing' | 'related_product' | 'ai_candidate' | 'hub'
  x: number
  y: number
  baseX: number
  baseY: number
  radius: number
  orbitRing: number
  relationship_type: RelationshipType
  data: ProductNode | ListingNode | (AISuggestion & { platform: Platform }) | HubData | any
  confidence?: number
  reasons?: string[]
  phase: number
}

interface CanvasEdge {
  id: string
  source: string
  target: string
  type: 'locked' | 'suggested' | 'related'
  relationship_type: RelationshipType
  confidence?: number
}

export default function ListingGraphPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()

  // Dark / Light Theme Toggle State
  const [isDarkMode, setIsDarkMode] = useState<boolean>(() => {
    return localStorage.getItem('orbit_theme') !== 'light'
  })

  const toggleTheme = () => {
    setIsDarkMode((prev) => {
      const next = !prev
      localStorage.setItem('orbit_theme', next ? 'dark' : 'light')
      return next
    })
  }

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
  const [bundleKitModalOpen, setBundleKitModalOpen] = useState(false)
  const [variantModalOpen, setVariantModalOpen] = useState(false)
  const [convertTypeModalOpen, setConvertTypeModalOpen] = useState(false)
  const [analyticsModalOpen, setAnalyticsModalOpen] = useState(false)
  const [bundleViewEnabled, setBundleViewEnabled] = useState(false)
  const [deepClassifyResult, setDeepClassifyResult] = useState<AIDeepClassifyResponse | null>(null)
  const [deepClassifyLoading, setDeepClassifyLoading] = useState(false)
  const [aiScanning, setAiScanning] = useState(false)
  const [aiSuggestions, setAiSuggestions] = useState<AISuggestion[]>([])
  const [actionMessage, setActionMessage] = useState<{ type: 'success' | 'error' | 'warning'; text: string } | null>(null)

  // Context Menu State
  const [contextMenuAnchor, setContextMenuAnchor] = useState<{ mouseX: number; mouseY: number } | null>(null)
  const [contextMenuTarget, setContextMenuTarget] = useState<ContextMenuTarget | null>(null)

  // 1. Fetch graph topology
  const {
    data: graphData,
    isLoading: isGraphLoading,
  } = useQuery<GraphTopologyResponse>({
    queryKey: ['listing-graph', activeVariantId],
    queryFn: async () => {
      const resp = await axiosClient.get(LISTINGS.GRAPH(activeVariantId!))
      return resp.data
    },
    enabled: !!activeVariantId,
  })

  // 2. Fetch Orbit Real-time Sales Analytics & Warnings
  const { data: analyticsData } = useQuery<OrbitAnalyticsResponse>({
    queryKey: ['orbit-analytics', activeVariantId],
    queryFn: async () => {
      const resp = await axiosClient.get(ORBIT.ANALYTICS(activeVariantId!))
      return resp.data
    },
    enabled: !!activeVariantId,
    refetchInterval: 60000,
    retry: 1,
  })

  // 2b. Fetch Participating Bundles (when Bundle View is toggled ON)
  const { data: bundleData } = useQuery<BundleDiscoveryResponse>({
    queryKey: ['orbit-bundles', activeVariantId],
    queryFn: async () => {
      const resp = await axiosClient.get(ORBIT.BUNDLES(activeVariantId!))
      return resp.data
    },
    enabled: !!activeVariantId && bundleViewEnabled,
  })

  // 3. Lock relationship mutation
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
      queryClient.invalidateQueries({ queryKey: ['orbit-analytics', activeVariantId] })
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

  // 4. Update relationship type mutation
  const updateRelMutation = useMutation({
    mutationFn: async ({
      targetType,
      targetId,
      relType,
    }: {
      targetType: 'listing' | 'component'
      targetId: number
      relType: RelationshipType
    }) => {
      const resp = await axiosClient.post(ORBIT.UPDATE_RELATIONSHIP, {
        target_type: targetType,
        source_variant_id: activeVariantId!,
        target_id: targetId,
        relationship_type: relType,
      })
      return resp.data
    },
    onSuccess: (data) => {
      setActionMessage({ type: 'success', text: data.message || 'Relationship updated' })
      queryClient.invalidateQueries({ queryKey: ['listing-graph', activeVariantId] })
    },
    onError: (err: any) => {
      setActionMessage({ type: 'error', text: err?.response?.data?.detail || 'Failed to update relationship' })
    },
  })

  // 5. Unlink mutation
  const unlinkMutation = useMutation({
    mutationFn: async ({
      targetType,
      targetId,
    }: {
      targetType: 'listing' | 'component'
      targetId: number
    }) => {
      const resp = await axiosClient.post(ORBIT.UNLINK, {
        target_type: targetType,
        target_id: targetId,
        source_variant_id: activeVariantId!,
      })
      return resp.data
    },
    onSuccess: (data) => {
      setActionMessage({ type: 'success', text: data.message || 'Tether severed' })
      queryClient.invalidateQueries({ queryKey: ['listing-graph', activeVariantId] })
      setSelectedNodeIds([])
    },
    onError: (err: any) => {
      setActionMessage({ type: 'error', text: err?.response?.data?.detail || 'Failed to unlink' })
    },
  })

  // 6. Compare listings query
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

  // 7. Scan AI Matches function (Phase 1 Listing Match + Auto Phase 2 Deep Classification)
  const handleScanAI = async () => {
    if (!activeVariantId) return
    setAiScanning(true)
    setDeepClassifyLoading(true)
    setActionMessage(null)
    try {
      // Phase 1: Listing Match Suggestions
      const resp = await axiosClient.post<AISuggestResponse>(LISTINGS.SUGGEST, {
        variant_id: activeVariantId,
        limit: 8,
        include_linked: false,
      })
      const suggestions = resp.data.suggestions || []
      setAiSuggestions(suggestions)

      // Phase 2: Auto-trigger Deep Product Classification
      try {
        const deepResp = await axiosClient.post<AIDeepClassifyResponse>(ORBIT.DEEP_CLASSIFY, {
          variant_id: activeVariantId,
        })
        setDeepClassifyResult(deepResp.data)
        const typeLabels: Record<string, string> = {
          Product: 'Standalone Item',
          K: 'Kit (K)',
          B: 'Bundle (B)',
          P: 'Part (P)',
        }
        const sType = typeLabels[deepResp.data.suggested_type] || deepResp.data.suggested_type
        const conf = (deepResp.data.type_confidence * 100).toFixed(0)
        setActionMessage({
          type: 'success',
          text: `AI Scan complete: ${suggestions.length} candidate listing(s) found. Classified as ${sType} (${conf}% confidence).`,
        })
      } catch (deepErr: any) {
        console.warn('Deep classification warning:', deepErr)
        setActionMessage({
          type: 'success',
          text: `Phase 1 scan complete: Discovered ${suggestions.length} candidate listings. (Deep classify: ${
            deepErr?.response?.data?.detail || 'unavailable'
          })`,
        })
      }
    } catch (err: any) {
      setActionMessage({
        type: 'error',
        text: err?.response?.data?.detail || 'AI suggestion scan failed',
      })
    } finally {
      setAiScanning(false)
      setDeepClassifyLoading(false)
    }
  }

  // 8. Grouped Hub Orbit Layout Calculation
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

    // 1. Center Master Product Core
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
      orbitRing: 0,
      relationship_type: 'EXACT',
      data: centerProduct,
      phase: 0,
    })

    // 2. Direct Marketplace Listings (Ebay, Amazon, Shopify, etc.)
    const listings = graphData?.listings || []
    const startListingAngle = -Math.PI * 0.75
    const endListingAngle = Math.PI * 0.65
    listings.forEach((listing, idx) => {
      const angle =
        listings.length === 1
          ? Math.PI
          : startListingAngle + (idx / (listings.length - 1)) * (endListingAngle - startListingAngle)
      const radiusDist = 180 + (idx % 2) * 28
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
        radius: 32,
        orbitRing: 1,
        relationship_type: relType,
        data: listing,
        phase: idx * 0.9,
      })

      newEdges.push({
        id: `edge-listing-${listing.listing_id}`,
        source: 'product',
        target: `listing-${listing.listing_id}`,
        type: 'locked',
        relationship_type: relType,
      })
    })

    // 3. Partition Related Products into Groups
    const relatedProducts = graphData?.related_products || []
    const variantItems: ProductNode[] = []
    const accessoryItems: ProductNode[] = []
    const componentItems: ProductNode[] = []

    relatedProducts.forEach((relProd) => {
      const edge = graphData?.edges?.find((e) => e.target === `related-product-${relProd.variant_id}`)
      const relType =
        edge?.relationship_type ||
        (relProd.identity_type === 'P' || relProd.identity_type === 'A' ? 'ACCESSORY' : 'SIBLING_VARIANT')

      if (relType === 'KIT_COMPONENT' || relType === 'BUNDLE_COMPONENT') {
        componentItems.push(relProd)
      } else if (relType === 'ACCESSORY' || relProd.identity_type === 'P' || relProd.identity_type === 'A') {
        accessoryItems.push(relProd)
      } else {
        variantItems.push(relProd)
      }
    })

    // Helper to position Hub + its children with multi-tier collision-free spacing
    const layoutHubGroup = (
      hubId: string,
      hubLabel: string,
      hubType: 'variants' | 'accessory' | 'component',
      hubIcon: string,
      hubColor: string,
      hubAngle: number,
      hubDist: number,
      items: ProductNode[],
      childRelType: RelationshipType,
    ) => {
      if (items.length === 0) return

      const hx = cx + Math.cos(hubAngle) * hubDist
      const hy = cy + Math.sin(hubAngle) * hubDist

      // Add Hub Node
      newNodes.push({
        id: hubId,
        type: 'hub',
        x: hx,
        y: hy,
        baseX: hx,
        baseY: hy,
        radius: 36,
        orbitRing: 2,
        relationship_type: childRelType,
        data: {
          hubId,
          label: hubLabel,
          hubType,
          icon: hubIcon,
          color: hubColor,
          count: items.length,
        } as HubData,
        phase: hubAngle,
      })

      // Tether ERP MASTER -> Hub
      newEdges.push({
        id: `edge-master-${hubId}`,
        source: 'product',
        target: hubId,
        type: 'locked',
        relationship_type: childRelType,
      })

      // Multi-tier fan out for children to ensure zero overlap even for 15+ items
      const tierCapacities = [4, 5, 6, 7]
      const tierDistances = [120, 195, 270, 345]
      const tierSpans = [Math.PI * 0.45, Math.PI * 0.60, Math.PI * 0.75, Math.PI * 0.90]

      let processed = 0
      let tierIdx = 0

      while (processed < items.length) {
        const cap = tierCapacities[Math.min(tierIdx, tierCapacities.length - 1)]
        const tierDist = tierDistances[Math.min(tierIdx, tierDistances.length - 1)]
        const tierSpan = tierSpans[Math.min(tierIdx, tierSpans.length - 1)]
        const countInTier = Math.min(cap, items.length - processed)

        for (let i = 0; i < countInTier; i++) {
          const item = items[processed + i]
          const fraction = countInTier === 1 ? 0.5 : i / (countInTier - 1)
          const angleOffset = (fraction - 0.5) * tierSpan
          const childAngle = hubAngle + angleOffset
          const cx_child = hx + Math.cos(childAngle) * tierDist
          const cy_child = hy + Math.sin(childAngle) * tierDist

          newNodes.push({
            id: `related-product-${item.variant_id}`,
            type: 'related_product',
            x: cx_child,
            y: cy_child,
            baseX: cx_child,
            baseY: cy_child,
            radius: 28,
            orbitRing: 3,
            relationship_type: childRelType,
            data: item,
            phase: (processed + i + 3) * 0.8,
          })

          // Tether Hub -> Child Node
          newEdges.push({
            id: `edge-hub-${hubId}-${item.variant_id}`,
            source: hubId,
            target: `related-product-${item.variant_id}`,
            type: 'related',
            relationship_type: childRelType,
          })
        }

        processed += countInTier
        tierIdx++
      }
    }

    // A. Variants Hub (Lower-Left: 140 deg / ~2.44 rad)
    layoutHubGroup(
      'hub-variants',
      'Variants',
      'variants',
      '🔗',
      '#a855f7',
      Math.PI * 0.78,
      250,
      variantItems,
      'SIBLING_VARIANT',
    )

    // B. Accessory Hub (Upper-Right: -35 deg / ~ -0.61 rad)
    layoutHubGroup(
      'hub-accessory',
      'Accessory',
      'accessory',
      '🔌',
      '#10b981',
      -Math.PI * 0.20,
      260,
      accessoryItems,
      'ACCESSORY',
    )

    // C. Component Hub (Lower-Right: 45 deg / ~ 0.78 rad) - for Kits and Bundles
    layoutHubGroup(
      'hub-component',
      'Component',
      'component',
      '🧰',
      '#818cf8',
      Math.PI * 0.25,
      270,
      componentItems,
      'KIT_COMPONENT',
    )

    // 4. Bundle View Layer (When Toggle is ON)
    if (bundleViewEnabled && bundleData?.participations?.length) {
      bundleData.participations.forEach((part, bIdx) => {
        const bAngle = -Math.PI * 0.72 + bIdx * 0.5
        const bDist = 230
        const bx = cx + Math.cos(bAngle) * bDist
        const by = cy + Math.sin(bAngle) * bDist

        const parentNodeId = `bundle-parent-${part.parent_variant_id}`
        newNodes.push({
          id: parentNodeId,
          type: 'related_product',
          x: bx,
          y: by,
          baseX: bx,
          baseY: by,
          radius: 32,
          orbitRing: 2,
          relationship_type: 'BUNDLE_COMPONENT',
          data: {
            variant_id: part.parent_variant_id,
            full_sku: part.parent_sku,
            variant_name: part.parent_name,
            identity_type: part.parent_type,
          } as ProductNode,
          phase: bIdx * 1.2,
        })

        // Edge: ERP MASTER -> Bundle Parent
        newEdges.push({
          id: `edge-bundle-${part.parent_variant_id}`,
          source: 'product',
          target: parentNodeId,
          type: 'suggested',
          relationship_type: 'BUNDLE_COMPONENT',
        })

        // Sibling components in this bundle
        part.sibling_components.forEach((sib, sIdx) => {
          const sibAngle = bAngle - 0.4 + sIdx * 0.45
          const sx = bx + Math.cos(sibAngle) * 95
          const sy = by + Math.sin(sibAngle) * 95

          const sibNodeId = `bundle-sib-${part.parent_variant_id}-${sib.variant_id}`
          newNodes.push({
            id: sibNodeId,
            type: 'related_product',
            x: sx,
            y: sy,
            baseX: sx,
            baseY: sy,
            radius: 26,
            orbitRing: 3,
            relationship_type: 'BUNDLE_COMPONENT',
            data: sib,
            phase: sIdx * 0.9,
          })

          newEdges.push({
            id: `edge-sib-${part.parent_variant_id}-${sib.variant_id}`,
            source: parentNodeId,
            target: sibNodeId,
            type: 'related',
            relationship_type: 'BUNDLE_COMPONENT',
          })
        })
      })
    }

    // 5. AI Suggestions (Purple Candidate Nodes)
    aiSuggestions.forEach((sug, idx) => {
      const angle = Math.PI * 0.05 + idx * 0.22
      const radiusDist = 205 + (idx % 2) * 35
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
        radius: 32,
        orbitRing: 2,
        relationship_type: relType,
        confidence: sug.confidence,
        reasons: sug.reasons,
        data: sug,
        phase: (idx + 10) * 0.9,
      })

      newEdges.push({
        id: `edge-ai-${sug.listing_id}`,
        source: 'product',
        target: `ai-${sug.listing_id}`,
        type: 'suggested',
        relationship_type: relType,
        confidence: sug.confidence,
      })
    })

    nodesRef.current = newNodes
    edgesRef.current = newEdges
  }, [graphData, selectedVariant, aiSuggestions, bundleViewEnabled, bundleData])

  // 9. Animation & Celestial Orbit Rendering Loop (requestAnimationFrame)
  useEffect(() => {
    let isRunning = true

    const render = (time: number) => {
      if (!isRunning) return
      const canvas = canvasRef.current
      if (!canvas) return
      const ctx = canvas.getContext('2d')
      if (!ctx) return

      const dpr = window.devicePixelRatio || 1
      if (canvas.width !== canvas.clientWidth * dpr || canvas.height !== canvas.clientHeight * dpr) {
        canvas.width = canvas.clientWidth * dpr
        canvas.height = canvas.clientHeight * dpr
      }

      ctx.save()
      ctx.scale(dpr, dpr)
      ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight)

      ctx.save()
      ctx.translate(pan.x, pan.y)
      ctx.scale(zoom, zoom)

      const cx = canvas.clientWidth / 2
      const cy = canvas.clientHeight / 2

      // Draw Celestial Orbit Guide Rings
      const orbitRings = [175, 250, 325, 390]
      orbitRings.forEach((r, idx) => {
        ctx.beginPath()
        ctx.arc(cx, cy, r, 0, Math.PI * 2)
        ctx.strokeStyle = isDarkMode ? 'rgba(255, 255, 255, 0.04)' : 'rgba(0, 0, 0, 0.06)'
        ctx.lineWidth = 1
        ctx.setLineDash([4, 8])
        ctx.stroke()
        ctx.setLineDash([])

        ctx.fillStyle = isDarkMode ? 'rgba(148, 163, 184, 0.3)' : 'rgba(100, 116, 139, 0.5)'
        ctx.font = '8px Inter, sans-serif'
        ctx.fillText(`RING ${idx + 1}`, cx + r - 16, cy - 4)
      })

      // Zero-Gravity Organic Physics
      const t = time * 0.001
      const currentNodes = nodesRef.current
      currentNodes.forEach((node) => {
        if (draggedNode && draggedNode.id === node.id) {
          // Keep dragged pos
        } else if (node.type === 'product') {
          const breathe = Math.sin(t * 1.5) * 1.5
          node.x = node.baseX
          node.y = node.baseY + breathe
        } else {
          const floatX = Math.sin(t * 1.1 + node.phase) * 5.0
          const floatY = Math.cos(t * 0.85 + node.phase * 1.2) * 5.0
          node.x = node.baseX + floatX
          node.y = node.baseY + floatY
        }
      })

      const nodeMap = new Map<string, CanvasNode>()
      currentNodes.forEach((n) => nodeMap.set(n.id, n))

      // --- Draw Edges (Tethers) ---
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
          ctx.setLineDash([6, 6])
          ctx.lineDashOffset = -t * 15
          ctx.strokeStyle = 'rgba(192, 132, 252, 0.85)'
          ctx.lineWidth = 2
          ctx.shadowColor = '#c084fc'
          ctx.shadowBlur = 10
        } else if (edge.type === 'related') {
          ctx.setLineDash([4, 4])
          ctx.lineDashOffset = 0
          ctx.strokeStyle = relMeta.color
          ctx.lineWidth = 2
          ctx.shadowColor = relMeta.color
          ctx.shadowBlur = 8
        } else {
          ctx.setLineDash([])
          ctx.strokeStyle = relMeta.color
          ctx.lineWidth = 2.5
          ctx.shadowColor = relMeta.color
          ctx.shadowBlur = 10
        }
        ctx.stroke()
        ctx.setLineDash([])
        ctx.shadowBlur = 0

        // Edge Midpoint Badge
        const midX = (sourceNode.x + targetNode.x) / 2
        const midY = (sourceNode.y + targetNode.y) / 2

        if (edge.type === 'suggested' && edge.confidence !== undefined) {
          const confText = `✨ ${(edge.confidence * 100).toFixed(0)}% ${relMeta.label}`
          ctx.font = 'bold 9.5px Inter, sans-serif'
          const tw = ctx.measureText(confText).width + 14
          ctx.fillStyle = isDarkMode ? 'rgba(24, 15, 45, 0.94)' : 'rgba(255, 255, 255, 0.95)'
          ctx.strokeStyle = '#c084fc'
          ctx.lineWidth = 1.2
          ctx.beginPath()
          ctx.roundRect(midX - tw / 2, midY - 9, tw, 18, 9)
          ctx.fill()
          ctx.stroke()

          ctx.fillStyle = isDarkMode ? '#f3e8ff' : '#6b21a8'
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText(confText, midX, midY)
        } else if (edge.relationship_type !== 'EXACT' && !edge.id.startsWith('edge-hub-')) {
          const badgeText = `${relMeta.icon} ${relMeta.label}`
          ctx.font = 'bold 8.5px Inter, sans-serif'
          const tw = ctx.measureText(badgeText).width + 12
          ctx.fillStyle = isDarkMode ? 'rgba(15, 23, 42, 0.94)' : 'rgba(255, 255, 255, 0.95)'
          ctx.strokeStyle = relMeta.color
          ctx.lineWidth = 1.2
          ctx.beginPath()
          ctx.roundRect(midX - tw / 2, midY - 8, tw, 16, 8)
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

        // Node Selection / Hover Halo
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
          // Central Master Product Core
          const stockWarning = analyticsData?.stock_warning || 'HEALTHY'
          const warningHaloColor =
            stockWarning === 'OUT_OF_STOCK'
              ? '#ef4444'
              : stockWarning === 'LOW_STOCK'
              ? '#f59e0b'
              : '#38bdf8'

          // Pulsing Warning Halo
          if (stockWarning !== 'HEALTHY') {
            ctx.beginPath()
            const pulseRadius = node.radius + 6 + Math.sin(t * 3) * 3
            ctx.arc(node.x, node.y, pulseRadius, 0, Math.PI * 2)
            ctx.strokeStyle = warningHaloColor
            ctx.lineWidth = 2
            ctx.setLineDash([4, 4])
            ctx.stroke()
            ctx.setLineDash([])
          }

          const grad = ctx.createRadialGradient(node.x, node.y, 4, node.x, node.y, node.radius)
          grad.addColorStop(0, '#1e3a8a')
          grad.addColorStop(1, '#0f172a')
          ctx.fillStyle = grad
          ctx.shadowColor = warningHaloColor
          ctx.shadowBlur = 24
          ctx.fill()
          ctx.strokeStyle = warningHaloColor
          ctx.lineWidth = 3
          ctx.stroke()
          ctx.shadowBlur = 0

          ctx.fillStyle = '#ffffff'
          ctx.font = 'bold 11px Inter, sans-serif'
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText('ERP MASTER', node.x, node.y - 12)

          ctx.fillStyle = '#38bdf8'
          ctx.font = 'bold 10px monospace'
          const sku = (node.data as ProductNode).full_sku || ''
          ctx.fillText(sku.length > 12 ? sku.substring(0, 10) + '..' : sku, node.x, node.y + 2)

          // Stock Badge Pill under core
          if (analyticsData) {
            ctx.fillStyle = analyticsData.available_stock === 0 ? '#ef4444' : '#4ade80'
            ctx.font = 'bold 8.5px Inter, sans-serif'
            ctx.fillText(`${analyticsData.available_stock} in stock`, node.x, node.y + 14)
          }
        } else if (node.type === 'related_product') {
          const pData = node.data as ProductNode
          const grad = ctx.createRadialGradient(node.x, node.y, 2, node.x, node.y, node.radius)
          grad.addColorStop(0, isDarkMode ? '#1e293b' : '#ffffff')
          grad.addColorStop(1, isDarkMode ? '#0f172a' : '#f1f5f9')
          ctx.fillStyle = grad
          ctx.fill()

          ctx.strokeStyle = relMeta.color
          ctx.lineWidth = 2
          ctx.setLineDash([3, 3])
          ctx.stroke()
          ctx.setLineDash([])

          ctx.fillStyle = isDarkMode ? '#f8fafc' : '#0f172a'
          ctx.font = 'bold 9px Inter, sans-serif'
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText(relMeta.icon, node.x, node.y - 6)

          ctx.fillStyle = isDarkMode ? '#cbd5e1' : '#334155'
          ctx.font = '8px monospace'
          const rSku = pData.full_sku || ''
          ctx.fillText(rSku.length > 10 ? rSku.substring(0, 8) + '..' : rSku, node.x, node.y + 7)
        } else if (node.type === 'hub') {
          const hData = node.data as HubData
          const grad = ctx.createRadialGradient(node.x, node.y, 4, node.x, node.y, node.radius)
          grad.addColorStop(0, isDarkMode ? '#1e293b' : '#ffffff')
          grad.addColorStop(1, isDarkMode ? '#0f172a' : '#f1f5f9')
          ctx.fillStyle = grad
          ctx.fill()

          ctx.strokeStyle = hData.color || '#8b5cf6'
          ctx.lineWidth = 3
          ctx.shadowColor = hData.color || '#8b5cf6'
          ctx.shadowBlur = 12
          ctx.stroke()
          ctx.shadowBlur = 0

          ctx.fillStyle = hData.color || '#8b5cf6'
          ctx.font = 'bold 11px Inter, sans-serif'
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText(`${hData.icon || '🪐'} ${hData.label}`, node.x, node.y - 6)

          ctx.fillStyle = isDarkMode ? '#cbd5e1' : '#64748b'
          ctx.font = 'bold 9px Inter, sans-serif'
          ctx.fillText(`${hData.count} item${hData.count === 1 ? '' : 's'}`, node.x, node.y + 8)
        } else if (node.type === 'ai_candidate') {
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
          ctx.fill()
          ctx.stroke()
          ctx.setLineDash([])
          ctx.shadowBlur = 0

          ctx.fillStyle = '#ffffff'
          ctx.font = 'bold 9.5px Inter, sans-serif'
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText(pMeta.label, node.x, node.y - 7)

          ctx.fillStyle = '#e9d5ff'
          ctx.font = 'bold 9.5px Inter, sans-serif'
          const confPct = `${((node.confidence || 0) * 100).toFixed(0)}%`
          ctx.fillText(`✨ ${confPct}`, node.x, node.y + 8)
        } else {
          // Locked Platform Listing Node
          const lData = node.data as ListingNode
          const pMeta = PLATFORM_META[lData.platform] || { label: lData.platform, color: '#38bdf8', icon: '🛒' }

          const grad = ctx.createRadialGradient(node.x, node.y, 2, node.x, node.y, node.radius)
          grad.addColorStop(0, isDarkMode ? '#1e293b' : '#ffffff')
          grad.addColorStop(1, isDarkMode ? '#0f172a' : '#f1f5f9')
          ctx.fillStyle = grad
          ctx.fill()

          ctx.strokeStyle = pMeta.color
          ctx.lineWidth = 2.5
          ctx.shadowColor = pMeta.color
          ctx.shadowBlur = 10
          ctx.stroke()
          ctx.shadowBlur = 0

          ctx.fillStyle = isDarkMode ? '#f8fafc' : '#0f172a'
          ctx.font = 'bold 9.5px Inter, sans-serif'
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText(pMeta.label, node.x, node.y - 7)

          ctx.fillStyle = '#10b981'
          ctx.font = 'bold 9.5px Inter, sans-serif'
          const price =
            lData.listing_price !== null && lData.listing_price !== undefined
              ? `$${lData.listing_price.toFixed(0)}`
              : '--'
          ctx.fillText(price, node.x, node.y + 8)

          // Price Mismatch Indicator Warning Pip
          if (
            analyticsData?.price_mismatch.has_mismatch &&
            (lData.platform === 'SHOPIFY' || lData.platform === 'ECWID')
          ) {
            ctx.beginPath()
            ctx.arc(node.x - node.radius + 6, node.y - node.radius + 6, 5, 0, Math.PI * 2)
            ctx.fillStyle = '#f59e0b'
            ctx.fill()
            ctx.strokeStyle = '#0f172a'
            ctx.lineWidth = 1.5
            ctx.stroke()
          }

          // Sync status indicator pip
          ctx.beginPath()
          ctx.arc(node.x + node.radius - 6, node.y - node.radius + 6, 4.5, 0, Math.PI * 2)
          ctx.fillStyle =
            lData.sync_status === 'SYNCED' ? '#22c55e' : lData.sync_status === 'ERROR' ? '#ef4444' : '#f59e0b'
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
  }, [pan, zoom, draggedNode, hoveredNode, selectedNodeIds, analyticsData, isDarkMode])

  // Mouse Handlers: Drag, Pan, Select
  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (e.button === 2) return
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const mouseX = (e.clientX - rect.left - pan.x) / zoom
    const mouseY = (e.clientY - rect.top - pan.y) / zoom

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

  // Right-Click Context Menu Trigger
  const handleContextMenu = (e: React.MouseEvent<HTMLCanvasElement>) => {
    e.preventDefault()
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const mouseX = (e.clientX - rect.left - pan.x) / zoom
    const mouseY = (e.clientY - rect.top - pan.y) / zoom

    // 1. Check Node right-click
    const clickedNode = nodesRef.current.find((n) => {
      const dx = n.x - mouseX
      const dy = n.y - mouseY
      return Math.sqrt(dx * dx + dy * dy) <= n.radius
    })

    if (clickedNode) {
      let title = ''
      let subtitle = ''
      let price: number | null = null
      let platform: Platform | undefined
      let numericId: number | undefined

      if (clickedNode.type === 'product') {
        const p = clickedNode.data as ProductNode
        title = p.variant_name || p.full_sku
        subtitle = p.full_sku
        numericId = p.variant_id
      } else if (clickedNode.type === 'listing') {
        const l = clickedNode.data as ListingNode
        title = l.listed_name || l.merchant_sku || 'Listing'
        subtitle = l.platform
        price = l.listing_price
        platform = l.platform
        numericId = l.listing_id
      } else if (clickedNode.type === 'ai_candidate') {
        const a = clickedNode.data as AISuggestion
        title = a.listed_name || a.merchant_sku || 'AI Candidate'
        subtitle = a.platform
        price = a.listing_price
        platform = a.platform
        numericId = a.listing_id
      } else {
        const rp = clickedNode.data as ProductNode
        title = rp.variant_name || rp.full_sku
        subtitle = rp.full_sku
        numericId = rp.variant_id
      }

      setContextMenuTarget({
        type: 'node',
        nodeType: clickedNode.type,
        id: clickedNode.id,
        numericId,
        title,
        subtitle,
        relationshipType: clickedNode.relationship_type,
        platform,
        price,
        hasPriceMismatch:
          analyticsData?.price_mismatch.has_mismatch && (platform === 'SHOPIFY' || platform === 'ECWID'),
        mismatchDiff: analyticsData?.price_mismatch.price_diff || 0,
      })
      setContextMenuAnchor({ mouseX: e.clientX, mouseY: e.clientY })
      return
    }

    // 2. Check Edge right-click
    const clickedEdge = edgesRef.current.find((edge) => {
      const nodeMap = new Map<string, CanvasNode>()
      nodesRef.current.forEach((n) => nodeMap.set(n.id, n))
      const s = nodeMap.get(edge.source)
      const t = nodeMap.get(edge.target)
      if (!s || !t) return false
      const midX = (s.x + t.x) / 2
      const midY = (s.y + t.y) / 2
      const dx = midX - mouseX
      const dy = midY - mouseY
      return Math.sqrt(dx * dx + dy * dy) <= 25
    })

    if (clickedEdge) {
      setContextMenuTarget({
        type: 'edge',
        id: clickedEdge.id,
        title: `Relationship Tether (${clickedEdge.relationship_type})`,
        relationshipType: clickedEdge.relationship_type,
      })
      setContextMenuAnchor({ mouseX: e.clientX, mouseY: e.clientY })
    }
  }

  // Focus a related product as central master core
  const handleFocusProduct = (variantId: number) => {
    setSearchParams({ variantId: variantId.toString() })
    setSelectedVariant(null)
    setAiSuggestions([])
    setSelectedNodeIds([])
  }

  // Selected node for floating bar
  const selectedNode = useMemo(() => {
    if (selectedNodeIds.length !== 1) return null
    return nodesRef.current.find((n) => n.id === selectedNodeIds[0]) || null
  }, [selectedNodeIds])

  // Multi-selected product nodes for Bundle / Kit modal
  const multiSelectedProducts = useMemo(() => {
    const prods = []
    if (graphData?.product) {
      prods.push(graphData.product)
    }
    selectedNodeIds.forEach((id) => {
      if (id.startsWith('related-product-')) {
        const vid = parseInt(id.replace('related-product-', ''), 10)
        const found = graphData?.related_products?.find((rp) => rp.variant_id === vid)
        if (found) prods.push(found)
      }
    })
    return prods
  }, [selectedNodeIds, graphData])

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        height: 'calc(100vh - 70px)',
        bgcolor: isDarkMode ? '#080c14' : '#f8fafc',
        color: isDarkMode ? '#f8fafc' : '#0f172a',
        overflow: 'hidden',
      }}
    >
      {/* Top Query & Orbit Control Header */}
      <Paper
        elevation={3}
        sx={{
          p: 1.5,
          px: 3,
          bgcolor: isDarkMode ? 'rgba(15, 23, 42, 0.95)' : '#ffffff',
          backdropFilter: 'blur(12px)',
          borderBottom: isDarkMode ? '1px solid rgba(255, 255, 255, 0.08)' : '1px solid #e2e8f0',
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
              isDarkMode={isDarkMode}
            />
          </Box>
        </Stack>

        {/* Orbit Action Controls & Sales Velocity HUD */}
        <Stack direction="row" alignItems="center" spacing={1.5}>
          {analyticsData && (
            <Tooltip title="Real 30-Day Sales Velocity & Stock Runway">
              <Chip
                icon={<TrendingUp sx={{ color: '#10b981 !important', fontSize: '15px !important' }} />}
                label={`🔥 ${analyticsData.units_sold_30d} sold (30d) · ${analyticsData.available_stock} stock (${analyticsData.runway_days ?? '--'}d runway)`}
                onClick={() => setAnalyticsModalOpen(true)}
                sx={{
                  bgcolor: isDarkMode ? 'rgba(16, 185, 129, 0.1)' : 'rgba(16, 185, 129, 0.15)',
                  color: isDarkMode ? '#10b981' : '#047857',
                  border: '1px solid rgba(16, 185, 129, 0.3)',
                  fontWeight: 600,
                  fontSize: 11,
                  cursor: 'pointer',
                }}
              />
            </Tooltip>
          )}

          {/* Convert Product Type Button */}
          <Button
            variant="outlined"
            size="small"
            startIcon={<ChangeCircle />}
            disabled={!activeVariantId}
            onClick={() => setConvertTypeModalOpen(true)}
            sx={{
              borderColor: '#818cf8',
              color: '#818cf8',
              textTransform: 'none',
              fontWeight: 600,
              '&:hover': { bgcolor: 'rgba(129, 140, 248, 0.1)', borderColor: '#6366f1' },
            }}
          >
            Convert Type
          </Button>

          {/* Form Bundle / Kit Button */}
          <Button
            variant="outlined"
            size="small"
            startIcon={<Inventory2 />}
            disabled={!activeVariantId}
            onClick={() => setBundleKitModalOpen(true)}
            sx={{
              borderColor: '#f59e0b',
              color: '#f59e0b',
              textTransform: 'none',
              fontWeight: 600,
              '&:hover': { bgcolor: 'rgba(245, 158, 11, 0.1)', borderColor: '#d97706' },
            }}
          >
            Form Bundle / Kit
          </Button>

          {/* Create Variant Button */}
          <Button
            variant="outlined"
            size="small"
            startIcon={<Palette />}
            disabled={!activeVariantId}
            onClick={() => setVariantModalOpen(true)}
            sx={{
              borderColor: '#38bdf8',
              color: '#38bdf8',
              textTransform: 'none',
              fontWeight: 600,
              '&:hover': { bgcolor: 'rgba(56, 189, 248, 0.1)', borderColor: '#0284c7' },
            }}
          >
            + Add Variant
          </Button>

          {selectedNodeIds.length >= 2 && (
            <Button
              variant="outlined"
              size="small"
              startIcon={<CompareArrows />}
              onClick={() => setCompareOpen(true)}
              sx={{ borderColor: '#38bdf8', color: '#38bdf8', textTransform: 'none', fontWeight: 600 }}
            >
              Compare ({selectedNodeIds.length})
            </Button>
          )}

          {/* Bundle View Toggle */}
          <Button
            variant={bundleViewEnabled ? 'contained' : 'outlined'}
            size="small"
            startIcon={<Workspaces />}
            disabled={!activeVariantId}
            onClick={() => setBundleViewEnabled((prev) => !prev)}
            sx={{
              borderColor: '#f59e0b',
              bgcolor: bundleViewEnabled ? '#f59e0b' : 'transparent',
              color: bundleViewEnabled ? '#ffffff' : '#f59e0b',
              textTransform: 'none',
              fontWeight: 600,
              '&:hover': {
                bgcolor: bundleViewEnabled ? '#d97706' : 'rgba(245, 158, 11, 0.1)',
                borderColor: '#d97706',
              },
            }}
          >
            Bundle View {bundleViewEnabled ? 'ON' : 'OFF'}
          </Button>

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
            {aiScanning ? 'Scanning...' : 'Scan AI'}
          </Button>

          {/* Dark / Light Mode Toggle */}
          <Tooltip title={`Switch to ${isDarkMode ? 'Light' : 'Dark'} Mode`}>
            <IconButton
              size="small"
              onClick={toggleTheme}
              sx={{
                color: isDarkMode ? '#fbbf24' : '#64748b',
                bgcolor: isDarkMode ? 'rgba(255, 255, 255, 0.06)' : '#f1f5f9',
                borderRadius: 1.5,
              }}
            >
              {isDarkMode ? <LightMode fontSize="small" /> : <DarkMode fontSize="small" />}
            </IconButton>
          </Tooltip>

          {/* Pan / Zoom Reset Controls */}
          <Stack direction="row" sx={{ bgcolor: isDarkMode ? 'rgba(255, 255, 255, 0.05)' : '#f1f5f9', borderRadius: 1 }}>
            <IconButton size="small" onClick={() => setZoom((z) => Math.min(2.5, z * 1.15))} sx={{ color: isDarkMode ? '#94a3b8' : '#64748b' }}>
              <ZoomIn fontSize="small" />
            </IconButton>
            <IconButton size="small" onClick={() => setZoom((z) => Math.max(0.4, z * 0.85))} sx={{ color: isDarkMode ? '#94a3b8' : '#64748b' }}>
              <ZoomOut fontSize="small" />
            </IconButton>
            <IconButton
              size="small"
              onClick={() => {
                setZoom(1)
                setPan({ x: 0, y: 0 })
              }}
              sx={{ color: isDarkMode ? '#94a3b8' : '#64748b' }}
            >
              <RestartAlt fontSize="small" />
            </IconButton>
          </Stack>
        </Stack>
      </Paper>

      {/* Ecwid vs. Shopify Price Mismatch Alert Banner */}
      {analyticsData?.price_mismatch.has_mismatch && (
        <Box sx={{ px: 3, pt: 1, zIndex: 10 }}>
          <Alert
            severity="warning"
            icon={<Warning sx={{ color: '#fbbf24' }} />}
            sx={{
              bgcolor: isDarkMode ? 'rgba(120, 53, 15, 0.85)' : '#fffbeb',
              color: isDarkMode ? '#ffffff' : '#92400e',
              border: '1px solid #f59e0b',
              fontSize: 12.5,
              fontWeight: 600,
            }}
          >
            {analyticsData.price_mismatch.message}
          </Alert>
        </Box>
      )}

      {/* Action Notification */}
      {actionMessage && (
        <Box sx={{ px: 3, pt: 1, zIndex: 10 }}>
          <Alert
            severity={actionMessage.type}
            onClose={() => setActionMessage(null)}
            sx={{
              bgcolor:
                actionMessage.type === 'success'
                  ? isDarkMode
                    ? 'rgba(6, 78, 59, 0.85)'
                    : '#ecfdf5'
                  : actionMessage.type === 'warning'
                  ? isDarkMode
                    ? 'rgba(120, 53, 15, 0.85)'
                    : '#fffbeb'
                  : isDarkMode
                  ? 'rgba(127, 29, 29, 0.85)'
                  : '#fef2f2',
              color:
                actionMessage.type === 'success'
                  ? isDarkMode
                    ? '#ffffff'
                    : '#065f46'
                  : actionMessage.type === 'warning'
                  ? isDarkMode
                    ? '#ffffff'
                    : '#92400e'
                  : isDarkMode
                  ? '#ffffff'
                  : '#991b1b',
              border: `1px solid ${
                actionMessage.type === 'success' ? '#10b981' : actionMessage.type === 'warning' ? '#f59e0b' : '#ef4444'
              }`,
            }}
          >
            {actionMessage.text}
          </Alert>
        </Box>
      )}

      {/* Main Orbit Canvas Area */}
      <Box
        ref={containerRef}
        sx={{
          flex: 1,
          position: 'relative',
          overflow: 'hidden',
          cursor: isPanning ? 'grabbing' : 'grab',
          background: isDarkMode
            ? 'radial-gradient(ellipse at center, #0f172a 0%, #080c14 100%)'
            : 'radial-gradient(ellipse at center, #ffffff 0%, #f1f5f9 100%)',
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
            <Typography variant="body2" sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', mt: 1.5 }}>
              Loading Orbit Galaxy...
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
              maxWidth: 440,
              p: 4,
              bgcolor: isDarkMode ? 'rgba(15, 23, 42, 0.85)' : '#ffffff',
              backdropFilter: 'blur(10px)',
              borderRadius: 3,
              border: isDarkMode ? '1px solid rgba(255, 255, 255, 0.08)' : '1px solid #e2e8f0',
              boxShadow: isDarkMode ? 'none' : '0 10px 30px rgba(0,0,0,0.08)',
            }}
          >
            <Search sx={{ fontSize: 48, color: '#38bdf8', mb: 1 }} />
            <Typography variant="h6" sx={{ fontWeight: 600, color: isDarkMode ? '#f8fafc' : '#0f172a' }}>
              Search for an ERP Product
            </Typography>
            <Typography variant="body2" sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', mt: 1 }}>
              Type any SKU (e.g. <code>00005-BK</code>, <code>00738</code>) above to open its full Orbit View with live sales velocity, kits, bundles, and channel sync.
            </Typography>
          </Box>
        )}

        <canvas
          ref={canvasRef}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onWheel={handleWheel}
          onContextMenu={handleContextMenu}
          style={{ width: '100%', height: '100%', display: 'block' }}
        />

        {/* Hover Tooltip Card */}
        {hoveredNode && hoverPos && (
          <Card
            sx={{
              position: 'absolute',
              left: hoverPos.x,
              top: hoverPos.y,
              maxWidth: 340,
              bgcolor: isDarkMode ? 'rgba(15, 23, 42, 0.96)' : 'rgba(255, 255, 255, 0.98)',
              backdropFilter: 'blur(14px)',
              border: isDarkMode ? '1px solid rgba(255, 255, 255, 0.15)' : '1px solid #cbd5e1',
              borderRadius: 2,
              boxShadow: isDarkMode ? '0 8px 32px rgba(0, 0, 0, 0.7)' : '0 8px 32px rgba(0, 0, 0, 0.15)',
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
                  label={RELATIONSHIP_META[hoveredNode.relationship_type]?.label || hoveredNode.relationship_type}
                  sx={{
                    bgcolor: isDarkMode ? 'rgba(255, 255, 255, 0.08)' : '#f1f5f9',
                    color: RELATIONSHIP_META[hoveredNode.relationship_type]?.color || '#38bdf8',
                    fontWeight: 600,
                    fontSize: 10,
                  }}
                />
              </Stack>

              <Typography variant="body2" sx={{ fontWeight: 600, color: isDarkMode ? '#f8fafc' : '#0f172a', fontSize: 12 }}>
                {'listed_name' in hoveredNode.data
                  ? (hoveredNode.data as ListingNode).listed_name || (hoveredNode.data as ListingNode).merchant_sku
                  : (hoveredNode.data as ProductNode).variant_name || (hoveredNode.data as ProductNode).full_sku}
              </Typography>

              {hoveredNode.reasons && hoveredNode.reasons.length > 0 && (
                <Box sx={{ mt: 1, pt: 1, borderTop: isDarkMode ? '1px solid rgba(255, 255, 255, 0.08)' : '1px solid #e2e8f0' }}>
                  <Typography variant="caption" sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', display: 'block', mb: 0.5 }}>
                    Match Reasoning:
                  </Typography>
                  {hoveredNode.reasons.map((r, i) => (
                    <Typography key={i} variant="caption" sx={{ color: isDarkMode ? '#cbd5e1' : '#334155', display: 'block', fontSize: 10.5 }}>
                      • {r}
                    </Typography>
                  ))}
                </Box>
              )}

              <Typography variant="caption" sx={{ color: '#38bdf8', display: 'block', mt: 1, fontStyle: 'italic' }}>
                💡 Right-click node for full action menu
              </Typography>
            </CardContent>
          </Card>
        )}

        {/* Floating Bottom Action Bar for 1-Click Lock */}
        {selectedNode && (selectedNode.type === 'ai_candidate' || selectedNode.type === 'listing') && (
          <Paper
            elevation={6}
            sx={{
              position: 'absolute',
              bottom: 24,
              left: '50%',
              transform: 'translateX(-50%)',
              bgcolor: isDarkMode ? 'rgba(15, 23, 42, 0.95)' : '#ffffff',
              backdropFilter: 'blur(16px)',
              border: isDarkMode ? '1px solid rgba(255, 255, 255, 0.15)' : '1px solid #cbd5e1',
              borderRadius: 3,
              p: 2,
              px: 3,
              display: 'flex',
              alignItems: 'center',
              gap: 2.5,
              zIndex: 30,
              boxShadow: isDarkMode ? '0 12px 40px rgba(0, 0, 0, 0.7)' : '0 12px 40px rgba(0, 0, 0, 0.15)',
              maxWidth: '90%',
            }}
          >
            <Box sx={{ maxWidth: 360 }}>
              <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 0.5 }}>
                <Chip
                  size="small"
                  label={'platform' in selectedNode.data ? (selectedNode.data as ListingNode).platform : 'Listing'}
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
              <Typography variant="body2" sx={{ fontWeight: 600, color: isDarkMode ? '#f8fafc' : '#0f172a', fontSize: 12 }} noWrap>
                {'listed_name' in selectedNode.data ? (selectedNode.data as ListingNode).listed_name : ''}
              </Typography>
            </Box>

            {/* 1-Click Lock Options */}
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

              <Tooltip title="Lock as USAV Bundle component (Type B)">
                <Button
                  variant="contained"
                  size="small"
                  startIcon={<Inventory2 />}
                  onClick={() => {
                    const lid = parseInt(selectedNode.id.replace('ai-', '').replace('listing-', ''), 10)
                    lockMutation.mutate({
                      listingId: lid,
                      variantId: activeVariantId!,
                      relationshipType: 'BUNDLE_COMPONENT',
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

              <Tooltip title="Lock as Predefined Manufacturer Kit component (Type K)">
                <Button
                  variant="contained"
                  size="small"
                  startIcon={<Handyman />}
                  onClick={() => {
                    const lid = parseInt(selectedNode.id.replace('ai-', '').replace('listing-', ''), 10)
                    lockMutation.mutate({
                      listingId: lid,
                      variantId: activeVariantId!,
                      relationshipType: 'KIT_COMPONENT',
                    })
                  }}
                  sx={{
                    bgcolor: '#6366f1',
                    textTransform: 'none',
                    fontWeight: 600,
                    fontSize: 11,
                    '&:hover': { bgcolor: '#4f46e5' },
                  }}
                >
                  Lock Kit
                </Button>
              </Tooltip>

              <Tooltip title="Lock as compatible accessory">
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

            <IconButton size="small" onClick={() => setSelectedNodeIds([])} sx={{ color: isDarkMode ? '#94a3b8' : '#64748b' }}>
              <Close fontSize="small" />
            </IconButton>
          </Paper>
        )}
      </Box>

      {/* Orbit Right-Click Context Menu */}
      <OrbitContextMenu
        anchorPos={contextMenuAnchor}
        target={contextMenuTarget}
        isDarkMode={isDarkMode}
        onClose={() => {
          setContextMenuAnchor(null)
          setContextMenuTarget(null)
        }}
        onChangeRelationship={(relType) => {
          if (!contextMenuTarget) return
          const numericId = contextMenuTarget.numericId || parseInt(
            contextMenuTarget.id.replace('listing-', '').replace('ai-', '').replace('edge-listing-', '').replace('related-product-', ''),
            10
          )
          updateRelMutation.mutate({
            targetType: 'listing',
            targetId: numericId,
            relType,
          })
        }}
        onUnlink={() => {
          if (!contextMenuTarget) return
          const numericId = contextMenuTarget.numericId || parseInt(
            contextMenuTarget.id.replace('listing-', '').replace('ai-', '').replace('edge-listing-', '').replace('related-product-', ''),
            10
          )
          unlinkMutation.mutate({
            targetType: 'listing',
            targetId: numericId,
          })
        }}
        onCreateVariant={() => setVariantModalOpen(true)}
        onFormBundleKit={() => setBundleKitModalOpen(true)}
        onConvertType={() => setConvertTypeModalOpen(true)}
        onScanAI={handleScanAI}
        onViewAnalytics={() => setAnalyticsModalOpen(true)}
        onFocusProduct={handleFocusProduct}
      />

      {/* Convert Product Type Modal */}
      {convertTypeModalOpen && (selectedVariant || graphData?.product) && (
        <OrbitConvertTypeModal
          open={convertTypeModalOpen}
          onClose={() => setConvertTypeModalOpen(false)}
          variant={selectedVariant || graphData!.product}
          isDarkMode={isDarkMode}
          onSuccess={(converted) => {
            setActionMessage({
              type: 'success',
              text: `Successfully converted product to ${converted.full_sku} (${converted.identity_type})!`,
            })
            queryClient.invalidateQueries({ queryKey: ['listing-graph', activeVariantId] })
          }}
        />
      )}

      {/* AI Deep Classification Results Panel */}
      <OrbitDeepClassifyPanel
        result={deepClassifyResult}
        loading={deepClassifyLoading}
        isDarkMode={isDarkMode}
        onConvertType={() => {
          setConvertTypeModalOpen(true)
        }}
        onFocusProduct={handleFocusProduct}
      />

      {/* Bundle / Kit Creator Modal */}
      {bundleKitModalOpen && (
        <OrbitBundleKitModal
          open={bundleKitModalOpen}
          onClose={() => setBundleKitModalOpen(false)}
          selectedNodes={multiSelectedProducts}
          isDarkMode={isDarkMode}
          onSuccess={(created) => {
            setActionMessage({ type: 'success', text: `Created ${created.full_sku} (${created.variant_name})!` })
            queryClient.invalidateQueries({ queryKey: ['listing-graph', activeVariantId] })
          }}
        />
      )}

      {/* Color / Condition Variant Creator Modal */}
      {variantModalOpen && selectedVariant && (
        <OrbitVariantModal
          open={variantModalOpen}
          onClose={() => setVariantModalOpen(false)}
          sourceVariant={selectedVariant}
          onSuccess={(newVar) => {
            setActionMessage({ type: 'success', text: `Created variant ${newVar.full_sku}!` })
            queryClient.invalidateQueries({ queryKey: ['listing-graph', activeVariantId] })
          }}
        />
      )}

      {/* Sales Velocity & Order Analytics Dialog */}
      <Dialog
        open={analyticsModalOpen}
        onClose={() => setAnalyticsModalOpen(false)}
        maxWidth="sm"
        fullWidth
        PaperProps={{
          sx: {
            bgcolor: isDarkMode ? '#0f172a' : '#ffffff',
            color: isDarkMode ? '#f8fafc' : '#0f172a',
            border: isDarkMode ? '1px solid rgba(255, 255, 255, 0.1)' : '1px solid #cbd5e1',
            borderRadius: 3,
          },
        }}
      >
        <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Stack direction="row" alignItems="center" spacing={1}>
            <TrendingUp sx={{ color: '#10b981' }} />
            <Typography variant="h6" sx={{ fontWeight: 600 }}>
              Order Velocity & Inventory Runway
            </Typography>
          </Stack>
          <IconButton onClick={() => setAnalyticsModalOpen(false)} sx={{ color: isDarkMode ? '#94a3b8' : '#64748b' }}>
            <Close />
          </IconButton>
        </DialogTitle>

        <DialogContent dividers sx={{ borderColor: isDarkMode ? 'rgba(255, 255, 255, 0.08)' : '#e2e8f0' }}>
          {analyticsData ? (
            <Stack spacing={2.5}>
              {/* Quick Metrics Grid */}
              <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 1.5 }}>
                <Paper
                  sx={{
                    p: 1.5,
                    bgcolor: isDarkMode ? 'rgba(255, 255, 255, 0.04)' : '#f8fafc',
                    border: isDarkMode ? 'none' : '1px solid #e2e8f0',
                    borderRadius: 2,
                    textAlign: 'center',
                  }}
                >
                  <Typography variant="caption" sx={{ color: isDarkMode ? '#94a3b8' : '#64748b' }}>
                    30-Day Sales
                  </Typography>
                  <Typography variant="h6" sx={{ color: isDarkMode ? '#f8fafc' : '#0f172a', fontWeight: 700 }}>
                    {analyticsData.units_sold_30d} units
                  </Typography>
                  <Typography variant="caption" sx={{ color: '#10b981', fontWeight: 600 }}>
                    ${analyticsData.revenue_30d.toFixed(2)}
                  </Typography>
                </Paper>

                <Paper
                  sx={{
                    p: 1.5,
                    bgcolor: isDarkMode ? 'rgba(255, 255, 255, 0.04)' : '#f8fafc',
                    border: isDarkMode ? 'none' : '1px solid #e2e8f0',
                    borderRadius: 2,
                    textAlign: 'center',
                  }}
                >
                  <Typography variant="caption" sx={{ color: isDarkMode ? '#94a3b8' : '#64748b' }}>
                    Warehouse Stock
                  </Typography>
                  <Typography
                    variant="h6"
                    sx={{
                      fontWeight: 700,
                      color: analyticsData.available_stock === 0 ? '#ef4444' : '#38bdf8',
                    }}
                  >
                    {analyticsData.available_stock} units
                  </Typography>
                  <Typography variant="caption" sx={{ color: isDarkMode ? '#94a3b8' : '#64748b' }}>
                    Available on-hand
                  </Typography>
                </Paper>

                <Paper
                  sx={{
                    p: 1.5,
                    bgcolor: isDarkMode ? 'rgba(255, 255, 255, 0.04)' : '#f8fafc',
                    border: isDarkMode ? 'none' : '1px solid #e2e8f0',
                    borderRadius: 2,
                    textAlign: 'center',
                  }}
                >
                  <Typography variant="caption" sx={{ color: isDarkMode ? '#94a3b8' : '#64748b' }}>
                    Stock Runway
                  </Typography>
                  <Typography
                    variant="h6"
                    sx={{
                      fontWeight: 700,
                      color:
                        analyticsData.stock_warning === 'OUT_OF_STOCK'
                          ? '#ef4444'
                          : analyticsData.stock_warning === 'LOW_STOCK'
                          ? '#f59e0b'
                          : '#10b981',
                    }}
                  >
                    {analyticsData.runway_days !== null ? `${analyticsData.runway_days} days` : '∞'}
                  </Typography>
                  <Typography variant="caption" sx={{ color: isDarkMode ? '#94a3b8' : '#64748b' }}>
                    {analyticsData.stock_warning}
                  </Typography>
                </Paper>
              </Box>

              {/* Price Mismatch Card */}
              {analyticsData.price_mismatch.has_mismatch && (
                <Alert severity="warning" sx={{ bgcolor: 'rgba(245, 158, 11, 0.15)', color: '#fbbf24' }}>
                  {analyticsData.price_mismatch.message}
                </Alert>
              )}

              {/* Channel Sales Table */}
              <Box>
                <Typography variant="subtitle2" sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', fontWeight: 600, mb: 1 }}>
                  Channel Order Breakdown (Last 90 Days)
                </Typography>
                <TableContainer
                  component={Paper}
                  sx={{
                    bgcolor: isDarkMode ? 'transparent' : '#f8fafc',
                    border: isDarkMode ? 'none' : '1px solid #e2e8f0',
                    boxShadow: 'none',
                  }}
                >
                  <Table size="small">
                    <TableHead>
                      <TableRow sx={{ borderBottom: isDarkMode ? '1px solid rgba(255, 255, 255, 0.1)' : '1px solid #cbd5e1' }}>
                        <TableCell sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', fontWeight: 600 }}>Platform</TableCell>
                        <TableCell sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', fontWeight: 600 }}>30d Units</TableCell>
                        <TableCell sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', fontWeight: 600 }}>30d Revenue</TableCell>
                        <TableCell sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', fontWeight: 600 }}>90d Units</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {analyticsData.channel_metrics.map((cm) => (
                        <TableRow key={cm.platform} sx={{ borderBottom: isDarkMode ? '1px solid rgba(255, 255, 255, 0.05)' : '1px solid #f1f5f9' }}>
                          <TableCell sx={{ color: '#0284c7', fontWeight: 600, fontSize: 12 }}>{cm.platform}</TableCell>
                          <TableCell sx={{ color: isDarkMode ? '#f8fafc' : '#0f172a', fontSize: 12 }}>{cm.units_sold_30d}</TableCell>
                          <TableCell sx={{ color: '#10b981', fontSize: 12 }}>${cm.revenue_30d.toFixed(2)}</TableCell>
                          <TableCell sx={{ color: isDarkMode ? '#cbd5e1' : '#334155', fontSize: 12 }}>{cm.units_sold_90d}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              </Box>
            </Stack>
          ) : (
            <CircularProgress size={24} sx={{ color: '#38bdf8' }} />
          )}
        </DialogContent>

        <DialogActions sx={{ p: 2 }}>
          <Button onClick={() => setAnalyticsModalOpen(false)} sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', textTransform: 'none' }}>
            Close
          </Button>
        </DialogActions>
      </Dialog>

      {/* Side-by-Side Comparison Dialog */}
      <Dialog
        open={compareOpen}
        onClose={() => setCompareOpen(false)}
        maxWidth="md"
        fullWidth
        PaperProps={{
          sx: {
            bgcolor: isDarkMode ? '#0f172a' : '#ffffff',
            color: isDarkMode ? '#f8fafc' : '#0f172a',
            border: isDarkMode ? '1px solid rgba(255, 255, 255, 0.1)' : '1px solid #cbd5e1',
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
          <IconButton onClick={() => setCompareOpen(false)} sx={{ color: isDarkMode ? '#94a3b8' : '#64748b' }}>
            <Close />
          </IconButton>
        </DialogTitle>

        <DialogContent dividers sx={{ borderColor: isDarkMode ? 'rgba(255, 255, 255, 0.08)' : '#e2e8f0' }}>
          {isCompareLoading ? (
            <Box sx={{ textAlign: 'center', py: 4 }}>
              <CircularProgress size={32} sx={{ color: '#38bdf8' }} />
            </Box>
          ) : compareData ? (
            <TableContainer component={Paper} sx={{ bgcolor: 'transparent', boxShadow: 'none' }}>
              <Table size="small">
                <TableHead>
                  <TableRow sx={{ borderBottom: isDarkMode ? '1px solid rgba(255, 255, 255, 0.12)' : '1px solid #cbd5e1' }}>
                    <TableCell sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', fontWeight: 600 }}>Attribute</TableCell>
                    {compareData.listings.map((l) => (
                      <TableCell key={l.listing_id} sx={{ color: '#38bdf8', fontWeight: 600 }}>
                        {l.platform} (#{l.listing_id})
                      </TableCell>
                    ))}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {compareData.comparison_fields.map((field) => (
                    <TableRow key={field.key} sx={{ borderBottom: isDarkMode ? '1px solid rgba(255, 255, 255, 0.05)' : '1px solid #f1f5f9' }}>
                      <TableCell sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', fontWeight: 500, fontSize: 12 }}>{field.label}</TableCell>
                      {compareData.listings.map((l) => (
                        <TableCell key={l.listing_id} sx={{ color: isDarkMode ? '#f8fafc' : '#0f172a', fontSize: 12 }}>
                          {field.values[l.listing_id.toString()] ?? '--'}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          ) : (
            <Typography variant="body2" sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', textAlign: 'center', py: 2 }}>
              Select 2 or more listing nodes on the canvas to compare.
            </Typography>
          )}
        </DialogContent>

        <DialogActions sx={{ p: 2 }}>
          <Button onClick={() => setCompareOpen(false)} sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', textTransform: 'none' }}>
            Close
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}

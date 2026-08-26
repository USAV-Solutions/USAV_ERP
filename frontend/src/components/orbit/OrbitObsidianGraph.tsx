import { useEffect, useRef, useState, useMemo, useCallback } from 'react'
import {
  Box,
  Typography,
  Chip,
  IconButton,
  Tooltip,
  Paper,
  Stack,
  CircularProgress,
  Slider,
  Switch,
  FormControlLabel,
  Collapse,
  Button,
} from '@mui/material'
import {
  RestartAlt,
  ZoomIn,
  ZoomOut,
  Tune,
  Hub,
  Inventory2,
  Category,
  AutoAwesome,
  Close,
  Explore,
} from '@mui/icons-material'
import {
  UniverseTopologyResponse,
  UniverseBrandNode,
  UniverseFamilyNode,
  UniverseProductNode,
} from '../../types/inventory'

interface OrbitObsidianGraphProps {
  data: UniverseTopologyResponse | null
  loading: boolean
  isDarkMode: boolean
  onSelectProduct: (variantId: number, sku?: string) => void
  highlightSku?: string | null
}

interface GraphNode {
  id: string
  label: string
  sublabel?: string
  sku?: string
  type: 'brand' | 'family' | 'product'
  identityType?: string
  radius: number
  color: string
  variantId?: number
  familyId?: number
  brandName?: string
  x: number
  y: number
  vx: number
  vy: number
  fx?: number | null
  fy?: number | null
  degree: number
}

interface GraphEdge {
  id: string
  source: string
  target: string
  type?: string
  color?: string
}

export default function OrbitObsidianGraph({
  data,
  loading,
  isDarkMode,
  onSelectProduct,
  highlightSku,
}: OrbitObsidianGraphProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  // Obsidian Graph Physics & Visual Controls
  const [controlsOpen, setControlsOpen] = useState(false)
  const [showLabels, setShowLabels] = useState(true)
  const [nodeScale, setNodeScale] = useState(1.0)
  const [linkDistance, setLinkDistance] = useState(65)
  const [repulsionStrength, setRepulsionStrength] = useState(350)
  const [centerGravity, setCenterGravity] = useState(0.04)
  const [selectedBrandFilter, setSelectedBrandFilter] = useState<string>('ALL')

  // Pan & Zoom
  const [zoom, setZoom] = useState(0.75)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const isPanningRef = useRef(false)
  const panStartRef = useRef({ x: 0, y: 0 })

  // Graph Simulation State Refs
  const nodesRef = useRef<GraphNode[]>([])
  const edgesRef = useRef<GraphEdge[]>([])
  const nodeMapRef = useRef<Map<string, GraphNode>>(new Map())
  const adjacencyRef = useRef<Map<string, Set<string>>>(new Map())
  const animationFrameRef = useRef<number | null>(null)
  const draggedNodeRef = useRef<GraphNode | null>(null)
  const hoveredNodeRef = useRef<GraphNode | null>(null)
  const [hoveredNodeState, setHoveredNodeState] = useState<GraphNode | null>(null)
  const [hoverPos, setHoverPos] = useState<{ x: number; y: number } | null>(null)

  // Camera Animation Ref
  const cameraAnimRef = useRef<{
    targetPan: { x: number; y: number }
    targetZoom: number
    active: boolean
    onDone?: () => void
  }>({
    targetPan: { x: 0, y: 0 },
    targetZoom: 1,
    active: false,
  })

  // 1. Build Graph Nodes & Edges from Universe Data
  useEffect(() => {
    if (!data || !data.brands) return

    const nodes: GraphNode[] = []
    const edges: GraphEdge[] = []
    const nodeMap = new Map<string, GraphNode>()
    const adj = new Map<string, Set<string>>()

    const addEdge = (src: string, tgt: string, color?: string, type?: string) => {
      edges.push({
        id: `e-${src}-${tgt}`,
        source: src,
        target: tgt,
        color,
        type,
      })
      if (!adj.has(src)) adj.set(src, new Set())
      if (!adj.has(tgt)) adj.set(tgt, new Set())
      adj.get(src)!.add(tgt)
      adj.get(tgt)!.add(src)
    }

    const filteredBrands =
      selectedBrandFilter === 'ALL'
        ? data.brands
        : data.brands.filter((b) => b.name === selectedBrandFilter)

    const totalBrands = filteredBrands.length
    const brandSpread = Math.max(400, totalBrands * 75)

    filteredBrands.forEach((brand, bIdx) => {
      const bAngle = (bIdx / Math.max(1, totalBrands)) * Math.PI * 2
      const bDist = (bIdx % 2 === 0 ? 0.7 : 1.0) * brandSpread * 0.7
      const bx = Math.cos(bAngle) * bDist + (Math.random() - 0.5) * 50
      const by = Math.sin(bAngle) * bDist + (Math.random() - 0.5) * 50

      const brandNodeId = `brand-${brand.brand_id}`
      const brandNode: GraphNode = {
        id: brandNodeId,
        label: brand.name,
        sublabel: `${brand.families.length} product lines`,
        type: 'brand',
        radius: 22,
        color: brand.color || '#38bdf8',
        brandName: brand.name,
        x: bx,
        y: by,
        vx: 0,
        vy: 0,
        degree: 0,
      }
      nodes.push(brandNode)
      nodeMap.set(brandNodeId, brandNode)

      // Product Families
      brand.families.forEach((fam, fIdx) => {
        const fAngle = bAngle + (fIdx / Math.max(1, brand.families.length)) * Math.PI * 2
        const fDist = 70 + (fIdx % 3) * 30
        const fx = bx + Math.cos(fAngle) * fDist
        const fy = by + Math.sin(fAngle) * fDist

        const famNodeId = `fam-${fam.product_id}`
        const famNode: GraphNode = {
          id: famNodeId,
          label: fam.base_name,
          sublabel: `Family SKU: ${fam.family_code} · ${fam.products.length} units`,
          sku: fam.family_code,
          type: 'family',
          radius: 12,
          color: brand.color || '#38bdf8',
          familyId: fam.product_id,
          brandName: brand.name,
          x: fx,
          y: fy,
          vx: 0,
          vy: 0,
          degree: 0,
        }
        nodes.push(famNode)
        nodeMap.set(famNodeId, famNode)
        addEdge(brandNodeId, famNodeId, brand.color || 'rgba(56, 189, 248, 0.4)')

        // Products in Family
        fam.products.forEach((prod, pIdx) => {
          const pAngle = fAngle + (pIdx / Math.max(1, fam.products.length)) * Math.PI * 2
          const pDist = 32 + (pIdx % 2) * 16
          const px = fx + Math.cos(pAngle) * pDist
          const py = fy + Math.sin(pAngle) * pDist

          let pColor = '#38bdf8'
          let pRadius = 7
          if (prod.identity_type === 'K') {
            pColor = '#c084fc'
            pRadius = 8.5
          } else if (prod.identity_type === 'B') {
            pColor = '#f59e0b'
            pRadius = 8.5
          } else if (prod.identity_type === 'P') {
            pColor = '#10b981'
            pRadius = 6
          }

          const prodNodeId = `prod-${prod.variant_id}`
          const prodNode: GraphNode = {
            id: prodNodeId,
            label: prod.full_sku,
            sublabel: prod.variant_name || 'Product Unit',
            sku: prod.full_sku,
            type: 'product',
            identityType: prod.identity_type,
            radius: pRadius,
            color: pColor,
            variantId: prod.variant_id,
            familyId: fam.product_id,
            brandName: brand.name,
            x: px,
            y: py,
            vx: 0,
            vy: 0,
            degree: 0,
          }
          nodes.push(prodNode)
          nodeMap.set(prodNodeId, prodNode)
          addEdge(famNodeId, prodNodeId, 'rgba(148, 163, 184, 0.25)')
        })
      })
    })

    // Compute node degrees
    nodes.forEach((n) => {
      n.degree = adj.get(n.id)?.size || 0
    })

    nodesRef.current = nodes
    edgesRef.current = edges
    nodeMapRef.current = nodeMap
    adjacencyRef.current = adj
  }, [data, selectedBrandFilter])

  // Center pan initially
  useEffect(() => {
    if (containerRef.current) {
      const w = containerRef.current.clientWidth
      const h = containerRef.current.clientHeight
      setPan({ x: w / 2, y: h / 2 })
    }
  }, [])

  // Smooth Fly-To Focus Animator
  const flyToNode = useCallback(
    (targetNode: GraphNode, targetZoomLevel = 1.35, onDone?: () => void) => {
      if (!containerRef.current) return
      const w = containerRef.current.clientWidth
      const h = containerRef.current.clientHeight

      const targetPanX = w / 2 - targetNode.x * targetZoomLevel
      const targetPanY = h / 2 - targetNode.y * targetZoomLevel

      cameraAnimRef.current = {
        targetPan: { x: targetPanX, y: targetPanY },
        targetZoom: targetZoomLevel,
        active: true,
        onDone,
      }
    },
    [],
  )

  // Handle Search Highlight Fly-To
  useEffect(() => {
    if (!highlightSku) return
    const target = nodesRef.current.find(
      (n) => n.sku?.toLowerCase() === highlightSku.toLowerCase() || n.label.toLowerCase() === highlightSku.toLowerCase(),
    )
    if (target) {
      flyToNode(target, 1.4, () => {
        if (target.variantId) {
          onSelectProduct(target.variantId, target.sku)
        }
      })
    }
  }, [highlightSku, flyToNode, onSelectProduct])

  // 2. Physics Simulation Loop (Force-Directed Obsidian Graph)
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let isRunning = true

    const render = () => {
      if (!isRunning) return

      // Handle Resize
      if (containerRef.current) {
        const w = containerRef.current.clientWidth
        const h = containerRef.current.clientHeight
        if (canvas.width !== w || canvas.height !== h) {
          canvas.width = w
          canvas.height = h
        }
      }

      const nodes = nodesRef.current
      const edges = edgesRef.current
      const nodeMap = nodeMapRef.current
      const hovered = hoveredNodeRef.current
      const adj = adjacencyRef.current

      // Set of connected active nodes for hover highlight
      const connectedNodeIds = new Set<string>()
      if (hovered) {
        connectedNodeIds.add(hovered.id)
        adj.get(hovered.id)?.forEach((id) => connectedNodeIds.add(id))
      }

      // Physics Calculation Step
      const numNodes = nodes.length
      const kRep = repulsionStrength * 25
      const kDist = linkDistance
      const kSpring = 0.04
      const kGrav = centerGravity * 0.08
      const damping = 0.88

      // 1. Repulsion between nearby nodes
      for (let i = 0; i < numNodes; i++) {
        const n1 = nodes[i]
        for (let j = i + 1; j < numNodes; j++) {
          const n2 = nodes[j]
          const dx = n2.x - n1.x
          const dy = n2.y - n1.y
          const distSq = dx * dx + dy * dy || 1
          const dist = Math.sqrt(distSq)

          if (dist < 400) {
            const force = kRep / (distSq + 100)
            const fx = (dx / dist) * force
            const fy = (dy / dist) * force

            if (draggedNodeRef.current?.id !== n1.id) {
              n1.vx -= fx
              n1.vy -= fy
            }
            if (draggedNodeRef.current?.id !== n2.id) {
              n2.vx += fx
              n2.vy += fy
            }
          }
        }
      }

      // 2. Spring Attraction along Edges
      for (let i = 0; i < edges.length; i++) {
        const edge = edges[i]
        const src = nodeMap.get(edge.source)
        const tgt = nodeMap.get(edge.target)
        if (!src || !tgt) continue

        const dx = tgt.x - src.x
        const dy = tgt.y - src.y
        const dist = Math.sqrt(dx * dx + dy * dy) || 1
        const delta = dist - kDist
        const force = delta * kSpring
        const fx = (dx / dist) * force
        const fy = (dy / dist) * force

        if (draggedNodeRef.current?.id !== src.id) {
          src.vx += fx
          src.vy += fy
        }
        if (draggedNodeRef.current?.id !== tgt.id) {
          tgt.vx -= fx
          tgt.vy -= fy
        }
      }

      // 3. Central Gravity & Position Integration
      for (let i = 0; i < numNodes; i++) {
        const n = nodes[i]
        if (draggedNodeRef.current?.id === n.id) {
          n.vx = 0
          n.vy = 0
          continue
        }

        // Gravity pulling gently toward (0,0)
        n.vx -= n.x * kGrav
        n.vy -= n.y * kGrav

        // Velocity Damping
        n.vx *= damping
        n.vy *= damping

        // Position Step
        n.x += n.vx
        n.y += n.vy
      }

      // Camera Animation Step (Smooth Fly-To)
      if (cameraAnimRef.current.active) {
        const { targetPan, targetZoom, onDone } = cameraAnimRef.current
        setPan((p) => ({
          x: p.x + (targetPan.x - p.x) * 0.08,
          y: p.y + (targetPan.y - p.y) * 0.08,
        }))
        setZoom((z) => {
          const nextZ = z + (targetZoom - z) * 0.08
          return nextZ
        })

        if (
          Math.abs(pan.x - targetPan.x) < 2 &&
          Math.abs(pan.y - targetPan.y) < 2 &&
          Math.abs(zoom - targetZoom) < 0.02
        ) {
          cameraAnimRef.current.active = false
          if (onDone) onDone()
        }
      }

      // 4. Render Canvas Scene
      ctx.clearRect(0, 0, canvas.width, canvas.height)

      // Background Obsidian Dot Matrix Grid
      ctx.save()
      ctx.fillStyle = isDarkMode ? '#090d16' : '#f8fafc'
      ctx.fillRect(0, 0, canvas.width, canvas.height)

      ctx.translate(pan.x, pan.y)
      ctx.scale(zoom, zoom)

      // Subtle Grid Dots
      const gridSize = 60
      const startX = Math.floor((-pan.x / zoom) / gridSize) * gridSize - gridSize
      const endX = Math.floor(((canvas.width - pan.x) / zoom) / gridSize) * gridSize + gridSize
      const startY = Math.floor((-pan.y / zoom) / gridSize) * gridSize - gridSize
      const endY = Math.floor(((canvas.height - pan.y) / zoom) / gridSize) * gridSize + gridSize

      ctx.fillStyle = isDarkMode ? 'rgba(255, 255, 255, 0.04)' : 'rgba(0, 0, 0, 0.04)'
      for (let gx = startX; gx <= endX; gx += gridSize) {
        for (let gy = startY; gy <= endY; gy += gridSize) {
          ctx.beginPath()
          ctx.arc(gx, gy, 1, 0, Math.PI * 2)
          ctx.fill()
        }
      }

      // 5. Draw Edges
      edges.forEach((edge) => {
        const src = nodeMap.get(edge.source)
        const tgt = nodeMap.get(edge.target)
        if (!src || !tgt) return

        const isHighlighted =
          hovered && (hovered.id === src.id || hovered.id === tgt.id)
        const isFaded = hovered && !isHighlighted

        ctx.beginPath()
        ctx.moveTo(src.x, src.y)
        ctx.lineTo(tgt.x, tgt.y)

        if (isHighlighted) {
          ctx.strokeStyle = edge.color || '#38bdf8'
          ctx.lineWidth = 2.2
          ctx.globalAlpha = 0.95
        } else if (isFaded) {
          ctx.strokeStyle = isDarkMode ? 'rgba(255, 255, 255, 0.03)' : 'rgba(0, 0, 0, 0.03)'
          ctx.lineWidth = 0.8
          ctx.globalAlpha = 0.15
        } else {
          ctx.strokeStyle = isDarkMode ? 'rgba(255, 255, 255, 0.12)' : 'rgba(0, 0, 0, 0.12)'
          ctx.lineWidth = 1
          ctx.globalAlpha = 0.7
        }
        ctx.stroke()
      })
      ctx.globalAlpha = 1.0

      // 6. Draw Nodes
      nodes.forEach((node) => {
        const isHovered = hovered?.id === node.id
        const isConnected = hovered && connectedNodeIds.has(node.id)
        const isFaded = hovered && !isConnected

        const r = node.radius * nodeScale

        ctx.save()
        if (isFaded) {
          ctx.globalAlpha = 0.15
        }

        // Node Glow Halo
        if (isHovered || isConnected || node.type === 'brand') {
          ctx.shadowColor = node.color
          ctx.shadowBlur = isHovered ? 20 : node.type === 'brand' ? 14 : 6
        }

        // Base Circle
        ctx.beginPath()
        ctx.arc(node.x, node.y, r, 0, Math.PI * 2)
        ctx.fillStyle = node.color
        ctx.fill()

        // Inner core border
        ctx.strokeStyle = isDarkMode ? '#0f172a' : '#ffffff'
        ctx.lineWidth = node.type === 'brand' ? 3 : 1.5
        ctx.stroke()
        ctx.shadowBlur = 0

        // Labels (Level of Detail based on zoom & node type)
        const shouldShowLabel =
          showLabels &&
          (isHovered ||
            isConnected ||
            node.type === 'brand' ||
            (node.type === 'family' && zoom > 0.6) ||
            (node.type === 'product' && zoom > 1.1))

        if (shouldShowLabel) {
          ctx.font =
            node.type === 'brand'
              ? 'bold 12px Inter, sans-serif'
              : node.type === 'family'
              ? 'bold 10px Inter, sans-serif'
              : '9px monospace'

          ctx.textAlign = 'center'
          ctx.textBaseline = 'top'

          // Text pill background
          const labelText = node.label
          const textWidth = ctx.measureText(labelText).width
          const pillY = node.y + r + 4

          ctx.fillStyle = isDarkMode ? 'rgba(15, 23, 42, 0.85)' : 'rgba(255, 255, 255, 0.9)'
          ctx.fillRect(node.x - textWidth / 2 - 4, pillY - 1, textWidth + 8, 14)

          ctx.fillStyle = isDarkMode ? '#f8fafc' : '#0f172a'
          ctx.fillText(labelText, node.x, pillY)
        }

        ctx.restore()
      })

      ctx.restore()
      animationFrameRef.current = requestAnimationFrame(render)
    }

    render()

    return () => {
      isRunning = false
      if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current)
    }
  }, [
    isDarkMode,
    zoom,
    pan,
    showLabels,
    nodeScale,
    linkDistance,
    repulsionStrength,
    centerGravity,
  ])

  // Mouse / Touch Event Handlers
  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (e.button === 1 || e.button === 2 || e.shiftKey) {
      // Middle or Right click / Shift click: Pan
      isPanningRef.current = true
      panStartRef.current = { x: e.clientX - pan.x, y: e.clientY - pan.y }
      return
    }

    if (e.button === 0) {
      // Left Click: Check Node Drag
      const canvas = canvasRef.current
      if (!canvas) return
      const rect = canvas.getBoundingClientRect()
      const mx = (e.clientX - rect.left - pan.x) / zoom
      const my = (e.clientY - rect.top - pan.y) / zoom

      const clicked = nodesRef.current.find((n) => {
        const dx = n.x - mx
        const dy = n.y - my
        return Math.sqrt(dx * dx + dy * dy) <= (n.radius * nodeScale + 6)
      })

      if (clicked) {
        draggedNodeRef.current = clicked
        clicked.vx = 0
        clicked.vy = 0
      } else {
        // Empty space: Pan canvas
        isPanningRef.current = true
        panStartRef.current = { x: e.clientX - pan.x, y: e.clientY - pan.y }
      }
    }
  }

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const mx = (e.clientX - rect.left - pan.x) / zoom
    const my = (e.clientY - rect.top - pan.y) / zoom

    if (draggedNodeRef.current) {
      draggedNodeRef.current.x = mx
      draggedNodeRef.current.y = my
      draggedNodeRef.current.vx = 0
      draggedNodeRef.current.vy = 0
      return
    }

    if (isPanningRef.current) {
      setPan({
        x: e.clientX - panStartRef.current.x,
        y: e.clientY - panStartRef.current.y,
      })
      return
    }

    // Hover Detection
    const hovered = nodesRef.current.find((n) => {
      const dx = n.x - mx
      const dy = n.y - my
      return Math.sqrt(dx * dx + dy * dy) <= (n.radius * nodeScale + 6)
    })

    hoveredNodeRef.current = hovered || null
    setHoveredNodeState(hovered || null)
    setHoverPos(hovered ? { x: e.clientX, y: e.clientY } : null)
    canvas.style.cursor = hovered ? 'pointer' : isPanningRef.current ? 'grabbing' : 'grab'
  }

  const handleMouseUp = () => {
    isPanningRef.current = false
    draggedNodeRef.current = null
  }

  const handleWheel = (e: React.WheelEvent<HTMLCanvasElement>) => {
    e.preventDefault()
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const mouseX = e.clientX - rect.left
    const mouseY = e.clientY - rect.top

    const zoomFactor = e.deltaY < 0 ? 1.15 : 0.85
    const newZoom = Math.max(0.15, Math.min(3.5, zoom * zoomFactor))

    // Zoom centered on cursor
    setPan({
      x: mouseX - (mouseX - pan.x) * (newZoom / zoom),
      y: mouseY - (mouseY - pan.y) * (newZoom / zoom),
    })
    setZoom(newZoom)
    cameraAnimRef.current.active = false
  }

  const handleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const mx = (e.clientX - rect.left - pan.x) / zoom
    const my = (e.clientY - rect.top - pan.y) / zoom

    const clicked = nodesRef.current.find((n) => {
      const dx = n.x - mx
      const dy = n.y - my
      return Math.sqrt(dx * dx + dy * dy) <= (n.radius * nodeScale + 6)
    })

    if (clicked) {
      if (clicked.type === 'product' && clicked.variantId) {
        // Smoothly fly in and open Single Orbit View
        flyToNode(clicked, 1.5, () => {
          onSelectProduct(clicked.variantId!, clicked.sku)
        })
      } else {
        // Zoom in to Brand or Family cluster
        flyToNode(clicked, clicked.type === 'brand' ? 1.1 : 1.35)
      }
    }
  }

  const handleResetView = () => {
    if (!containerRef.current) return
    const w = containerRef.current.clientWidth
    const h = containerRef.current.clientHeight
    setPan({ x: w / 2, y: h / 2 })
    setZoom(0.75)
    cameraAnimRef.current.active = false
  }

  return (
    <Box
      ref={containerRef}
      sx={{
        position: 'relative',
        width: '100%',
        height: '100%',
        overflow: 'hidden',
        bgcolor: isDarkMode ? '#090d16' : '#f8fafc',
      }}
    >
      {/* 2D HTML5 Force Canvas */}
      <canvas
        ref={canvasRef}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onWheel={handleWheel}
        onClick={handleClick}
        onContextMenu={(e) => e.preventDefault()}
        style={{ width: '100%', height: '100%', display: 'block' }}
      />

      {/* Loading Overlay */}
      {loading && (
        <Box
          sx={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            bgcolor: 'rgba(9, 13, 22, 0.85)',
            backdropFilter: 'blur(8px)',
            zIndex: 10,
          }}
        >
          <Stack spacing={2} alignItems="center">
            <CircularProgress size={48} sx={{ color: '#38bdf8' }} />
            <Typography variant="h6" sx={{ color: '#f8fafc', fontWeight: 600 }}>
              Building Obsidian Knowledge Graph...
            </Typography>
            <Typography variant="body2" sx={{ color: '#94a3b8' }}>
              Computing force-directed topology across brands, families, and units
            </Typography>
          </Stack>
        </Box>
      )}

      {/* Top Left Stats HUD */}
      {data && (
        <Paper
          elevation={3}
          sx={{
            position: 'absolute',
            top: 20,
            left: 20,
            p: 1.2,
            px: 2,
            borderRadius: 3,
            bgcolor: isDarkMode ? 'rgba(15, 23, 42, 0.85)' : 'rgba(255, 255, 255, 0.9)',
            backdropFilter: 'blur(12px)',
            border: isDarkMode ? '1px solid rgba(255, 255, 255, 0.1)' : '1px solid #cbd5e1',
            zIndex: 5,
          }}
        >
          <Stack direction="row" spacing={1.5} alignItems="center">
            <Stack direction="row" spacing={1} alignItems="center">
              <Explore sx={{ color: '#38bdf8', fontSize: 18 }} />
              <Typography variant="subtitle2" sx={{ fontWeight: 700, color: isDarkMode ? '#f8fafc' : '#0f172a' }}>
                DATABASE GRAPH
              </Typography>
            </Stack>

            <Chip
              size="small"
              icon={<AutoAwesome sx={{ fontSize: '12px !important', color: '#fbbf24 !important' }} />}
              label={`${data.total_brands} Brands`}
              sx={{ bgcolor: 'rgba(251, 191, 36, 0.12)', color: '#fbbf24', fontWeight: 600, fontSize: 11 }}
            />
            <Chip
              size="small"
              icon={<Hub sx={{ fontSize: '12px !important', color: '#38bdf8 !important' }} />}
              label={`${data.total_families} Product Lines`}
              sx={{ bgcolor: 'rgba(56, 189, 248, 0.12)', color: '#38bdf8', fontWeight: 600, fontSize: 11 }}
            />
            <Chip
              size="small"
              icon={<Inventory2 sx={{ fontSize: '12px !important', color: '#a855f7 !important' }} />}
              label={`${data.total_products} Units`}
              sx={{ bgcolor: 'rgba(168, 85, 247, 0.12)', color: '#a855f7', fontWeight: 600, fontSize: 11 }}
            />
          </Stack>
        </Paper>
      )}

      {/* Top Right Obsidian Graph Controls Button */}
      <Box sx={{ position: 'absolute', top: 20, right: 20, zIndex: 5 }}>
        <Paper
          elevation={3}
          sx={{
            p: 0.5,
            borderRadius: 2.5,
            bgcolor: isDarkMode ? 'rgba(15, 23, 42, 0.85)' : 'rgba(255, 255, 255, 0.9)',
            backdropFilter: 'blur(12px)',
            border: isDarkMode ? '1px solid rgba(255, 255, 255, 0.1)' : '1px solid #cbd5e1',
          }}
        >
          <Stack direction="row" spacing={0.5}>
            <Tooltip title="Graph Settings">
              <IconButton
                size="small"
                onClick={() => setControlsOpen((o) => !o)}
                sx={{ color: controlsOpen ? '#38bdf8' : isDarkMode ? '#94a3b8' : '#64748b' }}
              >
                <Tune fontSize="small" />
              </IconButton>
            </Tooltip>
            <Tooltip title="Zoom In">
              <IconButton size="small" onClick={() => setZoom((z) => Math.min(3.5, z * 1.2))} sx={{ color: isDarkMode ? '#94a3b8' : '#64748b' }}>
                <ZoomIn fontSize="small" />
              </IconButton>
            </Tooltip>
            <Tooltip title="Zoom Out">
              <IconButton size="small" onClick={() => setZoom((z) => Math.max(0.15, z * 0.8))} sx={{ color: isDarkMode ? '#94a3b8' : '#64748b' }}>
                <ZoomOut fontSize="small" />
              </IconButton>
            </Tooltip>
            <Tooltip title="Reset View">
              <IconButton size="small" onClick={handleResetView} sx={{ color: '#38bdf8' }}>
                <RestartAlt fontSize="small" />
              </IconButton>
            </Tooltip>
          </Stack>
        </Paper>

        {/* Collapsible Obsidian-Style Settings Drawer */}
        <Collapse in={controlsOpen}>
          <Paper
            elevation={8}
            sx={{
              mt: 1,
              p: 2,
              width: 260,
              borderRadius: 3,
              bgcolor: isDarkMode ? 'rgba(15, 23, 42, 0.95)' : 'rgba(255, 255, 255, 0.95)',
              backdropFilter: 'blur(16px)',
              border: isDarkMode ? '1px solid rgba(255, 255, 255, 0.12)' : '1px solid #cbd5e1',
            }}
          >
            <Stack spacing={2}>
              <Stack direction="row" justifyContent="space-between" alignItems="center">
                <Typography variant="caption" sx={{ fontWeight: 700, color: '#94a3b8', letterSpacing: 0.5 }}>
                  GRAPH FORCES & DISPLAY
                </Typography>
                <IconButton size="small" onClick={() => setControlsOpen(false)}>
                  <Close fontSize="small" />
                </IconButton>
              </Stack>

              <FormControlLabel
                control={
                  <Switch
                    size="small"
                    checked={showLabels}
                    onChange={(e) => setShowLabels(e.target.checked)}
                    sx={{ '& .MuiSwitch-switchBase.Mui-checked': { color: '#38bdf8' } }}
                  />
                }
                label={<Typography variant="body2" sx={{ fontSize: 12 }}>Show Node Labels</Typography>}
              />

              <Box>
                <Typography variant="caption" sx={{ color: isDarkMode ? '#cbd5e1' : '#475569' }}>
                  Node Size ({nodeScale.toFixed(1)}x)
                </Typography>
                <Slider
                  size="small"
                  min={0.5}
                  max={2.0}
                  step={0.1}
                  value={nodeScale}
                  onChange={(_, val) => setNodeScale(val as number)}
                  sx={{ color: '#38bdf8' }}
                />
              </Box>

              <Box>
                <Typography variant="caption" sx={{ color: isDarkMode ? '#cbd5e1' : '#475569' }}>
                  Link Distance ({linkDistance}px)
                </Typography>
                <Slider
                  size="small"
                  min={30}
                  max={140}
                  step={5}
                  value={linkDistance}
                  onChange={(_, val) => setLinkDistance(val as number)}
                  sx={{ color: '#38bdf8' }}
                />
              </Box>

              <Box>
                <Typography variant="caption" sx={{ color: isDarkMode ? '#cbd5e1' : '#475569' }}>
                  Repulsion Strength ({repulsionStrength})
                </Typography>
                <Slider
                  size="small"
                  min={100}
                  max={800}
                  step={50}
                  value={repulsionStrength}
                  onChange={(_, val) => setRepulsionStrength(val as number)}
                  sx={{ color: '#38bdf8' }}
                />
              </Box>

              <Box>
                <Typography variant="caption" sx={{ color: isDarkMode ? '#cbd5e1' : '#475569' }}>
                  Center Gravity ({centerGravity.toFixed(2)})
                </Typography>
                <Slider
                  size="small"
                  min={0.01}
                  max={0.12}
                  step={0.01}
                  value={centerGravity}
                  onChange={(_, val) => setCenterGravity(val as number)}
                  sx={{ color: '#38bdf8' }}
                />
              </Box>
            </Stack>
          </Paper>
        </Collapse>
      </Box>

      {/* Hover Card Tooltip */}
      {hoveredNodeState && hoverPos && (
        <Paper
          elevation={8}
          sx={{
            position: 'fixed',
            left: hoverPos.x + 14,
            top: hoverPos.y - 25,
            p: 1.5,
            minWidth: 200,
            maxWidth: 300,
            borderRadius: 2.5,
            bgcolor: isDarkMode ? 'rgba(15, 23, 42, 0.95)' : 'rgba(255, 255, 255, 0.95)',
            backdropFilter: 'blur(16px)',
            border: `1px solid ${hoveredNodeState.color}`,
            pointerEvents: 'none',
            zIndex: 20,
            boxShadow: '0 8px 30px rgba(0, 0, 0, 0.5)',
          }}
        >
          <Typography variant="subtitle2" sx={{ fontWeight: 700, color: isDarkMode ? '#f8fafc' : '#0f172a' }}>
            {hoveredNodeState.type === 'brand'
              ? `⭐ ${hoveredNodeState.label}`
              : hoveredNodeState.type === 'family'
              ? `🪐 ${hoveredNodeState.label}`
              : `🌕 ${hoveredNodeState.label}`}
          </Typography>
          {hoveredNodeState.sublabel && (
            <Typography variant="caption" sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', display: 'block', mt: 0.3 }}>
              {hoveredNodeState.sublabel}
            </Typography>
          )}
          <Typography variant="caption" sx={{ color: '#38bdf8', fontWeight: 600, display: 'block', mt: 0.6 }}>
            {hoveredNodeState.type === 'product'
              ? '⚡ Click node to open single-product Orbit View'
              : '⚡ Click node to zoom into cluster'}
          </Typography>
        </Paper>
      )}
    </Box>
  )
}

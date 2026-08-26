import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import {
  Box,
  Typography,
  Chip,
  IconButton,
  Tooltip,
  Paper,
  Stack,
  CircularProgress,
  Select,
  MenuItem,
  FormControl,
} from '@mui/material'
import {
  RestartAlt,
  Explore,
  Hub,
  Inventory2,
  AutoAwesome,
} from '@mui/icons-material'
import {
  UniverseTopologyResponse,
  UniverseBrandNode,
  UniverseFamilyNode,
  UniverseProductNode,
} from '../../types/inventory'

interface OrbitGalaxy3DProps {
  data: UniverseTopologyResponse | null
  loading: boolean
  isDarkMode: boolean
  onSelectProduct: (variantId: number, sku?: string) => void
  highlightSku?: string | null
}

interface ClickableObjectData {
  type: 'brand' | 'family' | 'product'
  brand?: UniverseBrandNode
  family?: UniverseFamilyNode
  product?: UniverseProductNode
  position: THREE.Vector3
}

export default function OrbitGalaxy3D({
  data,
  loading,
  isDarkMode,
  onSelectProduct,
  highlightSku,
}: OrbitGalaxy3DProps) {
  const mountRef = useRef<HTMLDivElement>(null)
  const [hoveredInfo, setHoveredInfo] = useState<{
    type: 'brand' | 'family' | 'product'
    title: string
    subtitle: string
    extra?: string
    x: number
    y: number
  } | null>(null)

  const [selectedBrandFilter, setSelectedBrandFilter] = useState<string>('ALL')
  const [isZooming, setIsZooming] = useState(false)

  // Three.js instances refs
  const sceneRef = useRef<THREE.Scene | null>(null)
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null)
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null)
  const animationFrameRef = useRef<number | null>(null)
  const clickableObjectsRef = useRef<THREE.Object3D[]>([])

  // Camera Target Animation State
  const cameraTargetRef = useRef<{
    targetPos: THREE.Vector3
    lookAtPos: THREE.Vector3
    active: boolean
    onComplete?: () => void
  }>({
    targetPos: new THREE.Vector3(0, 450, 950),
    lookAtPos: new THREE.Vector3(0, 0, 0),
    active: false,
  })

  // Current Orbit Angle / Controls
  const isDraggingRef = useRef(false)
  const previousMousePositionRef = useRef({ x: 0, y: 0 })
  const sphericalCoordsRef = useRef({
    radius: 1100,
    theta: Math.PI / 4,
    phi: Math.PI / 3.2,
    target: new THREE.Vector3(0, 0, 0),
  })

  // Product coordinate lookup for search fly-to
  const productCoordinatesMap = useRef<Map<string, { pos: THREE.Vector3; variantId: number }>>(
    new Map(),
  )

  // Initialize Three.js Scene
  useEffect(() => {
    if (!mountRef.current) return

    const width = mountRef.current.clientWidth || window.innerWidth
    const height = mountRef.current.clientHeight || window.innerHeight

    // 1. Scene
    const scene = new THREE.Scene()
    scene.background = new THREE.Color(isDarkMode ? 0x070b14 : 0x0f172a)
    scene.fog = new THREE.FogExp2(isDarkMode ? 0x070b14 : 0x0f172a, 0.00035)
    sceneRef.current = scene

    // 2. Camera
    const camera = new THREE.PerspectiveCamera(50, width / height, 1, 15000)
    camera.position.set(0, 600, 1200)
    camera.lookAt(0, 0, 0)
    cameraRef.current = camera

    // 3. Renderer
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    renderer.setSize(width, height)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 1.2
    mountRef.current.innerHTML = ''
    mountRef.current.appendChild(renderer.domElement)
    rendererRef.current = renderer

    // 4. Ambient & Directional Lighting
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.9)
    scene.add(ambientLight)

    const sunLight = new THREE.PointLight(0x38bdf8, 2, 5000)
    sunLight.position.set(0, 100, 0)
    scene.add(sunLight)

    // 5. Starfield Dust Background
    const starsGeometry = new THREE.BufferGeometry()
    const starCount = 3500
    const starPositions = new Float32Array(starCount * 3)
    const starColors = new Float32Array(starCount * 3)

    for (let i = 0; i < starCount; i++) {
      const radius = 2500 + Math.random() * 4500
      const theta = Math.random() * Math.PI * 2
      const phi = Math.acos(Math.random() * 2 - 1)

      starPositions[i * 3] = radius * Math.sin(phi) * Math.cos(theta)
      starPositions[i * 3 + 1] = (radius * Math.sin(phi) * Math.sin(theta)) * 0.4 // Flatter galactic plane
      starPositions[i * 3 + 2] = radius * Math.cos(phi)

      // Star tint variation
      const tintChoice = Math.random()
      if (tintChoice > 0.7) {
        starColors[i * 3] = 0.4
        starColors[i * 3 + 1] = 0.8
        starColors[i * 3 + 2] = 1.0 // Cyan
      } else if (tintChoice > 0.4) {
        starColors[i * 3] = 1.0
        starColors[i * 3 + 1] = 0.8
        starColors[i * 3 + 2] = 0.4 // Amber
      } else {
        starColors[i * 3] = 0.9
        starColors[i * 3 + 1] = 0.9
        starColors[i * 3 + 2] = 1.0 // White
      }
    }

    starsGeometry.setAttribute('position', new THREE.BufferAttribute(starPositions, 3))
    starsGeometry.setAttribute('color', new THREE.BufferAttribute(starColors, 3))

    const starsMaterial = new THREE.PointsMaterial({
      size: 2.2,
      vertexColors: true,
      transparent: true,
      opacity: 0.85,
    })
    const starField = new THREE.Points(starsGeometry, starsMaterial)
    scene.add(starField)

    // 6. Galactic Center Core Ring
    const coreRingGeo = new THREE.RingGeometry(40, 48, 64)
    const coreRingMat = new THREE.MeshBasicMaterial({
      color: 0x38bdf8,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.15,
    })
    const coreRing = new THREE.Mesh(coreRingGeo, coreRingMat)
    coreRing.rotation.x = Math.PI / 2
    scene.add(coreRing)

    // 7. Mouse Orbit Controls & Interaction Event Listeners
    const dom = renderer.domElement

    const onMouseDown = (e: MouseEvent) => {
      if (e.button === 0 || e.button === 2) {
        isDraggingRef.current = true
        previousMousePositionRef.current = { x: e.clientX, y: e.clientY }
      }
    }

    const onMouseMove = (e: MouseEvent) => {
      const rect = dom.getBoundingClientRect()
      const mouseX = ((e.clientX - rect.left) / rect.width) * 2 - 1
      const mouseY = -((e.clientY - rect.top) / rect.height) * 2 + 1

      if (isDraggingRef.current) {
        const deltaX = e.clientX - previousMousePositionRef.current.x
        const deltaY = e.clientY - previousMousePositionRef.current.y

        sphericalCoordsRef.current.theta -= deltaX * 0.005
        sphericalCoordsRef.current.phi = Math.max(
          0.1,
          Math.min(Math.PI / 2.05, sphericalCoordsRef.current.phi - deltaY * 0.005),
        )

        previousMousePositionRef.current = { x: e.clientX, y: e.clientY }
        cameraTargetRef.current.active = false // Cancel fly-to if user manually drags
      } else {
        // Raycasting for Hover Tooltips
        const raycaster = new THREE.Raycaster()
        raycaster.setFromCamera(new THREE.Vector2(mouseX, mouseY), camera)
        const intersects = raycaster.intersectObjects(clickableObjectsRef.current, true)

        if (intersects.length > 0) {
          let hitObj: THREE.Object3D | null = intersects[0].object
          while (hitObj && !hitObj.userData?.type) {
            hitObj = hitObj.parent
          }

          if (hitObj && hitObj.userData?.type) {
            const uData: ClickableObjectData = hitObj.userData as ClickableObjectData
            if (uData.type === 'brand' && uData.brand) {
              setHoveredInfo({
                type: 'brand',
                title: `⭐ Brand: ${uData.brand.name}`,
                subtitle: `${uData.brand.families.length} Product Families`,
                extra: 'Click to zoom into brand planetary system',
                x: e.clientX,
                y: e.clientY,
              })
            } else if (uData.type === 'family' && uData.family) {
              setHoveredInfo({
                type: 'family',
                title: `🪐 Line: ${uData.family.base_name}`,
                subtitle: `Family SKU: ${uData.family.family_code} · ${uData.family.products.length} Products`,
                extra: 'Click to explore family orbit',
                x: e.clientX,
                y: e.clientY,
              })
            } else if (uData.type === 'product' && uData.product) {
              setHoveredInfo({
                type: 'product',
                title: `🌕 ${uData.product.full_sku}`,
                subtitle: uData.product.variant_name || 'Product Unit',
                extra: `Type: ${uData.product.identity_type} · Click to open Single Orbit View`,
                x: e.clientX,
                y: e.clientY,
              })
            }
            dom.style.cursor = 'pointer'
            return
          }
        }
        setHoveredInfo(null)
        dom.style.cursor = 'grab'
      }
    }

    const onMouseUp = () => {
      isDraggingRef.current = false
    }

    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      sphericalCoordsRef.current.radius = Math.max(
        150,
        Math.min(3200, sphericalCoordsRef.current.radius + e.deltaY * 1.2),
      )
      cameraTargetRef.current.active = false
    }

    const onClick = (e: MouseEvent) => {
      const rect = dom.getBoundingClientRect()
      const mouseX = ((e.clientX - rect.left) / rect.width) * 2 - 1
      const mouseY = -((e.clientY - rect.top) / rect.height) * 2 + 1

      const raycaster = new THREE.Raycaster()
      raycaster.setFromCamera(new THREE.Vector2(mouseX, mouseY), camera)
      const intersects = raycaster.intersectObjects(clickableObjectsRef.current, true)

      if (intersects.length > 0) {
        let hitObj: THREE.Object3D | null = intersects[0].object
        while (hitObj && !hitObj.userData?.type) {
          hitObj = hitObj.parent
        }

        if (hitObj && hitObj.userData?.type) {
          const uData: ClickableObjectData = hitObj.userData as ClickableObjectData
          const targetWorldPos = new THREE.Vector3()
          hitObj.getWorldPosition(targetWorldPos)

          if (uData.type === 'product' && uData.product) {
            // Fly directly into product and open 2D Single Orbit
            flyToPosition(
              targetWorldPos,
              new THREE.Vector3(targetWorldPos.x, targetWorldPos.y + 40, targetWorldPos.z + 120),
              () => {
                onSelectProduct(uData.product!.variant_id, uData.product!.full_sku)
              },
            )
          } else if (uData.type === 'family' && uData.family) {
            // Zoom into family planetary system
            flyToPosition(
              targetWorldPos,
              new THREE.Vector3(targetWorldPos.x, targetWorldPos.y + 80, targetWorldPos.z + 240),
            )
          } else if (uData.type === 'brand' && uData.brand) {
            // Zoom into brand sun
            flyToPosition(
              targetWorldPos,
              new THREE.Vector3(targetWorldPos.x, targetWorldPos.y + 160, targetWorldPos.z + 450),
            )
          }
        }
      }
    }

    dom.addEventListener('mousedown', onMouseDown)
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
    dom.addEventListener('wheel', onWheel, { passive: false })
    dom.addEventListener('click', onClick)

    // Resize Handler
    const handleResize = () => {
      if (!mountRef.current || !rendererRef.current || !cameraRef.current) return
      const w = mountRef.current.clientWidth
      const h = mountRef.current.clientHeight
      cameraRef.current.aspect = w / h
      cameraRef.current.updateProjectionMatrix()
      rendererRef.current.setSize(w, h)
    }
    window.addEventListener('resize', handleResize)

    // 8. Animation Loop
    let clock = new THREE.Clock()
    const animate = () => {
      animationFrameRef.current = requestAnimationFrame(animate)
      const elapsedTime = clock.getElapsedTime()

      // Slow galactic rotation
      starField.rotation.y = elapsedTime * 0.008
      coreRing.rotation.z = elapsedTime * 0.015

      // Smooth Camera Fly-To Interpolation
      if (cameraTargetRef.current.active) {
        const { targetPos, lookAtPos, onComplete } = cameraTargetRef.current
        camera.position.lerp(targetPos, 0.065)
        sphericalCoordsRef.current.target.lerp(lookAtPos, 0.065)
        camera.lookAt(sphericalCoordsRef.current.target)

        if (camera.position.distanceTo(targetPos) < 6) {
          cameraTargetRef.current.active = false
          setIsZooming(false)
          if (onComplete) onComplete()
        }
      } else {
        // Orbit Controls Camera Update
        const { radius, theta, phi, target } = sphericalCoordsRef.current
        camera.position.x = target.x + radius * Math.sin(phi) * Math.sin(theta)
        camera.position.y = target.y + radius * Math.cos(phi)
        camera.position.z = target.z + radius * Math.sin(phi) * Math.cos(theta)
        camera.lookAt(target)
      }

      renderer.render(scene, camera)
    }
    animate()

    return () => {
      if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current)
      dom.removeEventListener('mousedown', onMouseDown)
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
      dom.removeEventListener('wheel', onWheel)
      dom.removeEventListener('click', onClick)
      window.removeEventListener('resize', handleResize)
      if (mountRef.current) mountRef.current.innerHTML = ''
    }
  }, [isDarkMode])

  // Helper: Smooth Camera Fly-To
  const flyToPosition = (lookAtTarget: THREE.Vector3, cameraPos: THREE.Vector3, onDone?: () => void) => {
    setIsZooming(true)
    cameraTargetRef.current = {
      targetPos: cameraPos,
      lookAtPos: lookAtTarget,
      active: true,
      onComplete: onDone,
    }
  }

  // Populate 3D Celestial Objects from Database Topology
  useEffect(() => {
    const scene = sceneRef.current
    if (!scene || !data || !data.brands) return

    // Clear previous dynamic clickable objects
    clickableObjectsRef.current.forEach((obj) => scene.remove(obj))
    clickableObjectsRef.current = []
    productCoordinatesMap.current.clear()

    const brandList =
      selectedBrandFilter === 'ALL'
        ? data.brands
        : data.brands.filter((b) => b.name === selectedBrandFilter)

    const numBrands = brandList.length
    const galaxyRadius = Math.max(380, numBrands * 55)

    brandList.forEach((brand, bIdx) => {
      // Galactic Golden Spiral distribution for Brand Stars
      const bAngle = bIdx * 2.39996 + 0.3 // Golden angle
      const bDist = Math.sqrt(bIdx / numBrands) * galaxyRadius + 140
      const bx = Math.cos(bAngle) * bDist
      const bz = Math.sin(bAngle) * bDist
      const by = Math.sin(bIdx * 1.5) * 45 // Gentle galactic wave

      const brandColor = new THREE.Color(brand.color || '#38bdf8')

      // Brand Sun Group
      const brandGroup = new THREE.Group()
      brandGroup.position.set(bx, by, bz)

      // 1. Core Glowing Star
      const sunGeo = new THREE.SphereGeometry(14, 24, 24)
      const sunMat = new THREE.MeshStandardMaterial({
        color: brandColor,
        emissive: brandColor,
        emissiveIntensity: 0.8,
        roughness: 0.2,
      })
      const sunMesh = new THREE.Mesh(sunGeo, sunMat)
      sunMesh.userData = {
        type: 'brand',
        brand,
        position: new THREE.Vector3(bx, by, bz),
      }
      brandGroup.add(sunMesh)
      clickableObjectsRef.current.push(sunMesh)

      // 2. Corona Halo Ring
      const coronaGeo = new THREE.RingGeometry(18, 22, 32)
      const coronaMat = new THREE.MeshBasicMaterial({
        color: brandColor,
        side: THREE.DoubleSide,
        transparent: true,
        opacity: 0.45,
      })
      const coronaMesh = new THREE.Mesh(coronaGeo, coronaMat)
      coronaMesh.rotation.x = Math.PI / 2
      brandGroup.add(coronaMesh)

      // 3. Text Billboard Sprite for Brand Name
      const brandLabelCanvas = document.createElement('canvas')
      brandLabelCanvas.width = 256
      brandLabelCanvas.height = 64
      const bCtx = brandLabelCanvas.getContext('2d')
      if (bCtx) {
        bCtx.fillStyle = 'rgba(15, 23, 42, 0.75)'
        bCtx.roundRect(10, 10, 236, 44, 8)
        bCtx.fill()
        bCtx.strokeStyle = brand.color || '#38bdf8'
        bCtx.lineWidth = 2
        bCtx.stroke()

        bCtx.fillStyle = '#ffffff'
        bCtx.font = 'bold 18px Inter, sans-serif'
        bCtx.textAlign = 'center'
        bCtx.fillText(brand.name.toUpperCase(), 128, 36)
      }
      const bTexture = new THREE.CanvasTexture(brandLabelCanvas)
      const bSpriteMat = new THREE.SpriteMaterial({ map: bTexture, transparent: true })
      const bSprite = new THREE.Sprite(bSpriteMat)
      bSprite.position.set(0, 24, 0)
      bSprite.scale.set(40, 10, 1)
      brandGroup.add(bSprite)

      // 4. Product Families (Small Planets) Orbiting the Brand Star
      const numFamilies = brand.families.length
      brand.families.forEach((fam, fIdx) => {
        const fAngle = (fIdx / Math.max(1, numFamilies)) * Math.PI * 2 + bIdx * 0.4
        const fDist = 55 + (fIdx % 3) * 28 + (fIdx / numFamilies) * 50
        const fx = Math.cos(fAngle) * fDist
        const fz = Math.sin(fAngle) * fDist
        const fy = Math.sin(fIdx * 1.8) * 12

        const famGroup = new THREE.Group()
        famGroup.position.set(fx, fy, fz)

        // Orbit Guide Line
        const orbitCurve = new THREE.EllipseCurve(0, 0, fDist, fDist, 0, 2 * Math.PI, false, 0)
        const orbitPoints = orbitCurve.getPoints(48)
        const orbitGeo = new THREE.BufferGeometry().setFromPoints(
          orbitPoints.map((p) => new THREE.Vector3(p.x, 0, p.y)),
        )
        const orbitMat = new THREE.LineBasicMaterial({
          color: brandColor,
          transparent: true,
          opacity: 0.15,
        })
        const orbitLine = new THREE.Line(orbitGeo, orbitMat)
        brandGroup.add(orbitLine)

        // Planet Sphere
        const planetGeo = new THREE.SphereGeometry(6.5, 18, 18)
        const planetMat = new THREE.MeshStandardMaterial({
          color: brandColor.clone().offsetHSL(0.05, 0, 0.1),
          roughness: 0.4,
          metalness: 0.3,
        })
        const planetMesh = new THREE.Mesh(planetGeo, planetMat)
        planetMesh.userData = {
          type: 'family',
          family: fam,
          brand,
          position: new THREE.Vector3(bx + fx, by + fy, bz + fz),
        }
        famGroup.add(planetMesh)
        clickableObjectsRef.current.push(planetMesh)

        // 5. Products / Variants (Moons) Orbiting the Family Planet
        const numProducts = fam.products.length
        fam.products.forEach((prod, pIdx) => {
          const pAngle = (pIdx / Math.max(1, numProducts)) * Math.PI * 2
          const pDist = 14 + (pIdx % 2) * 8
          const px = Math.cos(pAngle) * pDist
          const pz = Math.sin(pAngle) * pDist
          const py = Math.sin(pIdx) * 4

          // Color by UPIS Type
          let moonColor = 0x38bdf8
          if (prod.identity_type === 'K') moonColor = 0xc084fc // Purple for Kit
          else if (prod.identity_type === 'B') moonColor = 0xf59e0b // Amber for Bundle
          else if (prod.identity_type === 'P') moonColor = 0x10b981 // Emerald for Part

          const moonGeo = new THREE.SphereGeometry(2.5, 12, 12)
          const moonMat = new THREE.MeshStandardMaterial({
            color: moonColor,
            emissive: moonColor,
            emissiveIntensity: 0.4,
          })
          const moonMesh = new THREE.Mesh(moonGeo, moonMat)
          moonMesh.position.set(px, py, pz)

          const worldPos = new THREE.Vector3(bx + fx + px, by + fy + py, bz + fz + pz)
          moonMesh.userData = {
            type: 'product',
            product: prod,
            family: fam,
            brand,
            position: worldPos,
          }

          famGroup.add(moonMesh)
          clickableObjectsRef.current.push(moonMesh)

          // Index for fly-to search
          productCoordinatesMap.current.set(prod.full_sku.toLowerCase(), {
            pos: worldPos,
            variantId: prod.variant_id,
          })
        })

        brandGroup.add(famGroup)
      })

      scene.add(brandGroup)
    })

    // 6. Cross-Links & Constellation Lines Between Related Systems
    if (data.cross_links && data.cross_links.length > 0) {
      data.cross_links.forEach((link) => {
        const src = productCoordinatesMap.current.get(link.source_sku.toLowerCase())
        const tgt = productCoordinatesMap.current.get(link.target_sku.toLowerCase())

        if (src && tgt) {
          // Quadratic Bezier Arc in 3D Space
          const midX = (src.pos.x + tgt.pos.x) / 2
          const midY = Math.max(src.pos.y, tgt.pos.y) + 40
          const midZ = (src.pos.z + tgt.pos.z) / 2
          const midPoint = new THREE.Vector3(midX, midY, midZ)

          const curve = new THREE.QuadraticBezierCurve3(src.pos, midPoint, tgt.pos)
          const points = curve.getPoints(24)
          const lineGeo = new THREE.BufferGeometry().setFromPoints(points)
          const lineMat = new THREE.LineBasicMaterial({
            color: new THREE.Color(link.color || '#f59e0b'),
            transparent: true,
            opacity: 0.6,
          })
          const tetherLine = new THREE.Line(lineGeo, lineMat)
          scene.add(tetherLine)
        }
      })
    }
  }, [data, selectedBrandFilter])

  // Handle Search Fly-To Trigger
  useEffect(() => {
    if (!highlightSku) return
    const target = productCoordinatesMap.current.get(highlightSku.toLowerCase())
    if (target) {
      flyToPosition(
        target.pos,
        new THREE.Vector3(target.pos.x, target.pos.y + 40, target.pos.z + 120),
        () => {
          onSelectProduct(target.variantId, highlightSku)
        },
      )
    }
  }, [highlightSku])

  // Reset Camera View to Top Galaxy
  const handleResetView = () => {
    flyToPosition(new THREE.Vector3(0, 0, 0), new THREE.Vector3(0, 600, 1200))
  }

  return (
    <Box sx={{ position: 'relative', width: '100%', height: '100%', overflow: 'hidden' }}>
      {/* 3D WebGL Canvas Container */}
      <Box
        ref={mountRef}
        sx={{
          width: '100%',
          height: '100%',
          cursor: isZooming ? 'wait' : 'grab',
        }}
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
            bgcolor: 'rgba(7, 11, 20, 0.85)',
            backdropFilter: 'blur(8px)',
            zIndex: 10,
          }}
        >
          <Stack spacing={2} alignItems="center">
            <CircularProgress size={52} sx={{ color: '#38bdf8' }} />
            <Typography variant="h6" sx={{ color: '#f8fafc', fontWeight: 600 }}>
              Generating 3D Database Galaxy...
            </Typography>
            <Typography variant="body2" sx={{ color: '#94a3b8' }}>
              Synthesizing brand stars, product lines, and cross-stellar tethers
            </Typography>
          </Stack>
        </Box>
      )}

      {/* Top Universe Stats HUD */}
      {data && (
        <Paper
          elevation={4}
          sx={{
            position: 'absolute',
            top: 20,
            left: 20,
            p: 1.5,
            px: 2.5,
            borderRadius: 3,
            bgcolor: isDarkMode ? 'rgba(15, 23, 42, 0.85)' : 'rgba(255, 255, 255, 0.9)',
            backdropFilter: 'blur(12px)',
            border: isDarkMode ? '1px solid rgba(255, 255, 255, 0.1)' : '1px solid #cbd5e1',
            zIndex: 5,
          }}
        >
          <Stack direction="row" spacing={2} alignItems="center">
            <Stack direction="row" spacing={1} alignItems="center">
              <Explore sx={{ color: '#38bdf8', fontSize: 20 }} />
              <Typography variant="subtitle2" sx={{ fontWeight: 700, color: isDarkMode ? '#f8fafc' : '#0f172a' }}>
                DATABASE UNIVERSE
              </Typography>
            </Stack>

            <Chip
              size="small"
              icon={<AutoAwesome sx={{ fontSize: '13px !important', color: '#fbbf24 !important' }} />}
              label={`${data.total_brands} Brand Stars`}
              sx={{ bgcolor: 'rgba(251, 191, 36, 0.12)', color: '#fbbf24', fontWeight: 600, fontSize: 11 }}
            />
            <Chip
              size="small"
              icon={<Hub sx={{ fontSize: '13px !important', color: '#38bdf8 !important' }} />}
              label={`${data.total_families} Product Lines`}
              sx={{ bgcolor: 'rgba(56, 189, 248, 0.12)', color: '#38bdf8', fontWeight: 600, fontSize: 11 }}
            />
            <Chip
              size="small"
              icon={<Inventory2 sx={{ fontSize: '13px !important', color: '#a855f7 !important' }} />}
              label={`${data.total_products} Units & Moons`}
              sx={{ bgcolor: 'rgba(168, 85, 247, 0.12)', color: '#a855f7', fontWeight: 600, fontSize: 11 }}
            />
          </Stack>
        </Paper>
      )}

      {/* Floating View Controls (Reset, Brand Jump) */}
      <Paper
        elevation={4}
        sx={{
          position: 'absolute',
          bottom: 24,
          right: 24,
          p: 1,
          borderRadius: 3,
          bgcolor: isDarkMode ? 'rgba(15, 23, 42, 0.85)' : 'rgba(255, 255, 255, 0.9)',
          backdropFilter: 'blur(12px)',
          border: isDarkMode ? '1px solid rgba(255, 255, 255, 0.1)' : '1px solid #cbd5e1',
          zIndex: 5,
        }}
      >
        <Stack direction="row" spacing={1} alignItems="center">
          <Tooltip title="Reset Universe View">
            <IconButton onClick={handleResetView} sx={{ color: '#38bdf8' }}>
              <RestartAlt />
            </IconButton>
          </Tooltip>

          {data?.brands && (
            <FormControl size="small" sx={{ minWidth: 140 }}>
              <Select
                value={selectedBrandFilter}
                onChange={(e) => setSelectedBrandFilter(e.target.value)}
                sx={{
                  fontSize: 12,
                  color: isDarkMode ? '#f8fafc' : '#0f172a',
                  '.MuiOutlinedInput-notchedOutline': {
                    borderColor: isDarkMode ? 'rgba(255, 255, 255, 0.15)' : '#cbd5e1',
                  },
                }}
              >
                <MenuItem value="ALL" sx={{ fontSize: 12 }}>
                  🌌 All Brands ({data.brands.length})
                </MenuItem>
                {data.brands.map((b) => (
                  <MenuItem key={b.brand_id} value={b.name} sx={{ fontSize: 12 }}>
                    ⭐ {b.name} ({b.families.length})
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          )}
        </Stack>
      </Paper>

      {/* Dynamic Hover Tooltip HUD */}
      {hoveredInfo && (
        <Paper
          elevation={8}
          sx={{
            position: 'fixed',
            left: hoveredInfo.x + 16,
            top: hoveredInfo.y - 30,
            p: 1.5,
            minWidth: 220,
            maxWidth: 320,
            borderRadius: 2.5,
            bgcolor: isDarkMode ? 'rgba(15, 23, 42, 0.95)' : 'rgba(255, 255, 255, 0.95)',
            backdropFilter: 'blur(16px)',
            border:
              hoveredInfo.type === 'brand'
                ? '1px solid #fbbf24'
                : hoveredInfo.type === 'family'
                  ? '1px solid #38bdf8'
                  : '1px solid #a855f7',
            pointerEvents: 'none',
            zIndex: 20,
            boxShadow: '0 12px 36px rgba(0, 0, 0, 0.6)',
          }}
        >
          <Typography variant="subtitle2" sx={{ fontWeight: 700, color: isDarkMode ? '#f8fafc' : '#0f172a' }}>
            {hoveredInfo.title}
          </Typography>
          <Typography variant="caption" sx={{ color: isDarkMode ? '#94a3b8' : '#64748b', display: 'block', mt: 0.3 }}>
            {hoveredInfo.subtitle}
          </Typography>
          {hoveredInfo.extra && (
            <Typography variant="caption" sx={{ color: '#38bdf8', fontWeight: 600, display: 'block', mt: 0.6 }}>
              ⚡ {hoveredInfo.extra}
            </Typography>
          )}
        </Paper>
      )}
    </Box>
  )
}

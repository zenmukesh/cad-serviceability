import { useRef, useEffect, useState, Suspense, useMemo } from 'react'
import { Canvas, useThree, useFrame } from '@react-three/fiber'
import { Html, PerspectiveCamera, OrthographicCamera } from '@react-three/drei'
import * as THREE from 'three'
import { getComponentMesh } from '../../api/client'
import { useAssemblyStore } from '../../store/assemblyStore'
import type { MeshData, Component } from '../../types/assembly'
import type { ComponentSectionOutline } from '../../types/serviceability'
import CADCameraController from './CADCameraController'
import ViewCube from './ViewCube'
import NavigationBar from './NavigationBar'
import SectionGizmo from './SectionGizmo'
import CompactSectionBar from './CompactSectionBar'
import SectionErrorBoundary from './SectionErrorBoundary'

// ─── Mesh cache ──────────────────────────────────────────────────────────────
const meshCache = new Map<number, MeshData>()

// ─── Individual component mesh ───────────────────────────────────────────────
interface ComponentMeshProps {
  component: Component
  isSelected: boolean
  isObstructing: boolean
  isTranslucent: boolean
  isXRay: boolean
  isVisible: boolean
  displacement: [number, number, number]
  clippingPlanes: THREE.Plane[]
  clipIntersection: boolean
  onSelect: (id: number) => void
}

function ComponentMesh({
  component,
  isSelected,
  isObstructing,
  isTranslucent,
  isXRay,
  isVisible,
  displacement,
  clippingPlanes,
  clipIntersection,
  onSelect,
}: ComponentMeshProps) {
  const meshRef = useRef<THREE.Mesh>(null)
  const [meshData, setMeshData] = useState<MeshData | null>(null)
  const [geo, setGeo] = useState<THREE.BufferGeometry | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        let data = meshCache.get(component.id)
        if (!data) {
          data = await getComponentMesh(component.id)
          meshCache.set(component.id, data)
        }
        if (!cancelled) setMeshData(data)
      } catch {
        // Skip if component has no mesh (e.g. assembly container)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [component.id])

  useEffect(() => {
    if (!meshData || !meshData.vertices || meshData.vertices.length === 0) return
    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute(
      'position',
      new THREE.Float32BufferAttribute(meshData.vertices, 3)
    )
    if (meshData.normals && meshData.normals.length > 0) {
      geometry.setAttribute(
        'normal',
        new THREE.Float32BufferAttribute(meshData.normals, 3)
      )
    }
    if (meshData.faces && meshData.faces.length > 0) {
      geometry.setIndex(new THREE.Uint32BufferAttribute(meshData.faces, 1))
    }
    if (!meshData.normals || meshData.normals.length === 0) {
      geometry.computeVertexNormals()
    }
    setGeo(geometry)
    return () => geometry.dispose()
  }, [meshData])

  if (!isVisible || !geo) return null

  // Material style determination
  let color = '#64748b'
  let emissive = '#000000'
  let emissiveIntensity = 0.0
  let opacity = 1.0
  let transparent = false
  let depthWrite = true

  if (isObstructing) {
    // Red highlight for obstructing parts (Phase 6)
    color = '#ef4444'
    emissive = '#b91c1c'
    emissiveIntensity = 0.55
  } else if (isSelected) {
    // Blue highlight for selected / target component (Phase 6)
    color = '#38bdf8'
    emissive = '#0284c7'
    emissiveIntensity = 0.45
  } else if (isXRay) {
    // Semi-transparent ghosted mode for covers/housings (Phase 1)
    color = '#94a3b8'
    opacity = 0.22
    transparent = true
    depthWrite = false
  } else if (isTranslucent) {
    // User-toggled transparent mode (Phase 1)
    color = '#64748b'
    opacity = 0.3
    transparent = true
    depthWrite = false
  }

  return (
    <group position={displacement}>
      <mesh
        ref={meshRef}
        geometry={geo}
        userData={{ componentId: component.id }}
        onClick={(e) => {
          e.stopPropagation()
          onSelect(component.id)
        }}
        onDoubleClick={(e) => {
          e.stopPropagation()
          onSelect(component.id)
        }}
      >
        <meshStandardMaterial
          color={color}
          roughness={0.4}
          metalness={0.3}
          side={THREE.DoubleSide}
          emissive={new THREE.Color(emissive)}
          emissiveIntensity={emissiveIntensity}
          transparent={transparent}
          opacity={opacity}
          depthWrite={depthWrite}
          clippingPlanes={clippingPlanes}
          clipIntersection={clipIntersection}
        />
      </mesh>
    </group>
  )
}

// ─── 3D Visual Clearance Dimension Line (Phase 6) ───────────────────────────
function ClearanceLineOverlay({
  p1,
  p2,
  dist,
  label,
}: {
  p1: [number, number, number]
  p2: [number, number, number]
  dist: number
  label: string
}) {
  const lineGeo = useMemo(() => {
    const pts = [new THREE.Vector3(...p1), new THREE.Vector3(...p2)]
    return new THREE.BufferGeometry().setFromPoints(pts)
  }, [p1, p2])

  const midPoint: [number, number, number] = [
    (p1[0] + p2[0]) / 2,
    (p1[1] + p2[1]) / 2,
    (p1[2] + p2[2]) / 2,
  ]

  return (
    <group>
      {/* 3D dimension line */}
      {/* @ts-ignore */}
      <line geometry={lineGeo}>
        <lineBasicMaterial color="#f59e0b" linewidth={3} />
      </line>

      {/* End point markers */}
      <mesh position={p1}>
        <sphereGeometry args={[1.2, 16, 16]} />
        <meshBasicMaterial color="#f59e0b" />
      </mesh>
      <mesh position={p2}>
        <sphereGeometry args={[1.2, 16, 16]} />
        <meshBasicMaterial color="#f59e0b" />
      </mesh>

      {/* Floating distance tag */}
      <Html position={midPoint} center distanceFactor={140}>
        <div className="bg-amber-950/90 text-amber-300 border border-amber-500/60 rounded px-2 py-0.5 text-[10px] font-mono font-semibold whitespace-nowrap shadow-lg pointer-events-none">
          {label}: {dist.toFixed(2)} mm
        </div>
      </Html>
    </group>
  )
}

// ─── 3D Visual Access Vector Arrow (Phase 6 & Part 3) ────────────────────────
function AccessVectorOverlay({
  origin,
  dir,
  label,
  componentBBox,
}: {
  origin: [number, number, number]
  dir: [number, number, number]
  label: string
  componentBBox?: { size_x: number; size_y: number; size_z: number } | null
}) {
  const arrowDir = useMemo(() => {
    const v = new THREE.Vector3(...dir).normalize()
    return isNaN(v.x) || v.lengthSq() < 1e-5 ? new THREE.Vector3(0, 0, 1) : v
  }, [dir])

  // Scale arrow and cone compactly to component size, bounded so it never occludes the assembly
  const compSize = useMemo(() => {
    if (componentBBox) {
      return Math.max(componentBBox.size_x, componentBBox.size_y, componentBBox.size_z)
    }
    return 50
  }, [componentBBox])

  // Clamped between 16mm and 26mm total length
  const totalLength = useMemo(() => {
    return Math.max(16, Math.min(26, compSize * 0.35))
  }, [compSize])

  const headLength = Math.min(4.5, totalLength * 0.22)
  const shaftLength = totalLength - headLength
  const shaftRadius = 0.55
  const headRadius = 1.7
  const coneRadius = 2.4 // Sleek, non-occluding guidance cone

  // Start arrow slightly outside the component bounding surface along arrowDir
  const arrowOrigin = useMemo(() => {
    const base = new THREE.Vector3(...origin)
    if (componentBBox) {
      const halfExtent =
        Math.abs(arrowDir.x) * (componentBBox.size_x * 0.5) +
        Math.abs(arrowDir.y) * (componentBBox.size_y * 0.5) +
        Math.abs(arrowDir.z) * (componentBBox.size_z * 0.5)
      base.addScaledVector(arrowDir, halfExtent + 1.5)
    }
    return base
  }, [origin, arrowDir, componentBBox])

  const { nearestAxis, angleDeg } = useMemo(() => {
    const cardinalVectors: [string, [number, number, number]][] = [
      ['+X', [1, 0, 0]], ['-X', [-1, 0, 0]],
      ['+Y', [0, 1, 0]], ['-Y', [0, -1, 0]],
      ['+Z', [0, 0, 1]], ['-Z', [0, 0, -1]],
    ]
    let best = '+Z'
    let maxDot = -1
    for (const [name, cv] of cardinalVectors) {
      const dot = arrowDir.x * cv[0] + arrowDir.y * cv[1] + arrowDir.z * cv[2]
      if (dot > maxDot) {
        maxDot = dot
        best = name
      }
    }
    const deg = Math.acos(Math.max(-1, Math.min(1, maxDot))) * (180 / Math.PI)
    return { nearestAxis: best, angleDeg: deg }
  }, [arrowDir])

  // Quaternion aligning +Y (standard cylinder/cone orientation) to arrowDir
  const quat = useMemo(() => {
    const q = new THREE.Quaternion()
    q.setFromUnitVectors(new THREE.Vector3(0, 1, 0), arrowDir)
    return q
  }, [arrowDir])

  // Center positions for the shaft and head relative to arrowOrigin
  const shaftCenter = useMemo(() => {
    return arrowOrigin.clone().addScaledVector(arrowDir, shaftLength * 0.5)
  }, [arrowOrigin, arrowDir, shaftLength])

  const headCenter = useMemo(() => {
    return arrowOrigin.clone().addScaledVector(arrowDir, shaftLength + headLength * 0.5)
  }, [arrowOrigin, arrowDir, shaftLength, headLength])

  const coneCenter = useMemo(() => {
    return arrowOrigin.clone().addScaledVector(arrowDir, totalLength * 0.45)
  }, [arrowOrigin, arrowDir, totalLength])

  const tipPos = useMemo(() => {
    return [
      arrowOrigin.x + arrowDir.x * (totalLength + 2),
      arrowOrigin.y + arrowDir.y * (totalLength + 2),
      arrowOrigin.z + arrowDir.z * (totalLength + 2),
    ] as [number, number, number]
  }, [arrowOrigin, arrowDir, totalLength])

  const prefix = label && !label.includes(nearestAxis) ? `${label} ` : ''
  const displayLabel = angleDeg < 1.0
    ? `${prefix}${nearestAxis} [${arrowDir.x.toFixed(2)}, ${arrowDir.y.toFixed(2)}, ${arrowDir.z.toFixed(2)}]`
    : `${prefix}${nearestAxis} (${angleDeg.toFixed(1)}°) [${arrowDir.x.toFixed(2)}, ${arrowDir.y.toFixed(2)}, ${arrowDir.z.toFixed(2)}]`

  return (
    <group>
      {/* 3.4 Primary Visual: Slender Arrow Shaft */}
      <mesh position={shaftCenter} quaternion={quat}>
        <cylinderGeometry args={[shaftRadius, shaftRadius, shaftLength, 12]} />
        <meshBasicMaterial color="#38bdf8" />
      </mesh>

      {/* 3.4 Primary Visual: Arrow Head */}
      <mesh position={headCenter} quaternion={quat}>
        <coneGeometry args={[headRadius, headLength, 16]} />
        <meshBasicMaterial color="#38bdf8" />
      </mesh>

      {/* 3.4 Primary Visual: Translucent guidance cone along removal direction (clamped to never occlude scene) */}
      <mesh position={coneCenter} quaternion={quat}>
        <coneGeometry args={[coneRadius, totalLength * 0.9, 16, 1, true]} />
        <meshBasicMaterial
          color="#38bdf8"
          transparent
          opacity={0.16}
          side={THREE.DoubleSide}
          depthWrite={false}
        />
      </mesh>

      {/* 3D Label: Fixed-scale HTML badge without distanceFactor to avoid blowing up when camera approaches */}
      <Html position={tipPos} center style={{ pointerEvents: 'none' }}>
        <div
          data-testid="access-vector-label"
          className="bg-blue-950/90 text-cyan-300 border border-cyan-500/60 rounded px-1.5 py-0.5 text-[10px] font-mono font-semibold whitespace-nowrap shadow-md pointer-events-none"
        >
          {displayLabel}
        </div>
      </Html>
    </group>
  )
}

// ─── Exact BREP Cross-Section Outlines (Phase D) ───────────────────────────
function BrepSectionOutlinesOverlay({
  sections,
}: {
  sections: ComponentSectionOutline[]
}) {
  const lineGeometries = useMemo(() => {
    const geos: THREE.BufferGeometry[] = []
    for (const sec of sections) {
      for (const poly of sec.outlines) {
        if (poly.length >= 2) {
          const pts = poly.map((p) => new THREE.Vector3(p[0], p[1], p[2]))
          geos.push(new THREE.BufferGeometry().setFromPoints(pts))
        }
      }
    }
    return geos
  }, [sections])

  return (
    <group>
      {lineGeometries.map((geo, idx) => (
        // @ts-ignore
        <line key={idx} geometry={geo}>
          <lineBasicMaterial color="#06b6d4" linewidth={3} />
        </line>
      ))}
    </group>
  )
}

// ─── Multi-Plane Solid Cap Faces with In-Plane 45° Hatching (Phase D & Part 2) ──
function SectionCapPlanes({
  planes,
  clipIntersection: _clipIntersection,
  hatchEnabled,
  assemblyCenterThree,
  capSpan,
}: {
  planes: THREE.Plane[]
  clipIntersection: boolean
  hatchEnabled: boolean
  assemblyCenterThree?: THREE.Vector3
  capSpan?: number
}) {
  const centerThree = useMemo(
    () => assemblyCenterThree || new THREE.Vector3(0, 0, 0),
    [assemblyCenterThree]
  )
  const span = capSpan || 300

  const capMaterial = useMemo(() => {
    return new THREE.ShaderMaterial({
      clipping: true,
      side: THREE.DoubleSide,
      transparent: true,
      depthWrite: false,
      uniforms: {
        uColor: { value: new THREE.Color('#334155') },
        uHatchColor: { value: new THREE.Color('#cbd5e1') },
        uHatchEnabled: { value: hatchEnabled ? 1.0 : 0.0 },
        uSpacing: { value: 3.5 },
        uLineWidth: { value: 0.45 },
      },
      vertexShader: `
        varying vec2 vPlanePos;
        #include <clipping_planes_pars_vertex>
        void main() {
          vPlanePos = position.xy;
          vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
          gl_Position = projectionMatrix * mvPosition;
          #include <clipping_planes_vertex>
        }
      `,
      fragmentShader: `
        uniform vec3 uColor;
        uniform vec3 uHatchColor;
        uniform float uHatchEnabled;
        uniform float uSpacing;
        uniform float uLineWidth;
        varying vec2 vPlanePos;
        #include <clipping_planes_pars_fragment>

        void main() {
          #include <clipping_planes_fragment>
          vec3 col = uColor;
          if (uHatchEnabled > 0.5) {
            // Spatial cells in plane space (u, v) to differentiate neighbouring parts
            float cellX = floor(vPlanePos.x / 40.0);
            float cellY = floor(vPlanePos.y / 40.0);
            float checker = mod(cellX + cellY, 2.0);

            // Alternating 45° (+0.785398) vs 135° (-0.785398)
            float angle = (checker > 0.5) ? -0.785398 : 0.785398;
            float spacing = (checker > 0.5) ? (uSpacing * 1.3) : uSpacing;

            mat2 rot = mat2(cos(angle), -sin(angle), sin(angle), cos(angle));
            vec2 rotPos = rot * vPlanePos;

            float dist = abs(fract(rotPos.x / spacing + 0.5) - 0.5) * spacing;
            float fw = fwidth(dist) * 0.75;
            float line = 1.0 - smoothstep(uLineWidth - fw, uLineWidth + fw, dist);

            col = mix(col, uHatchColor, line * 0.92);
          }
          gl_FragColor = vec4(col, 0.95);
        }
      `,
    })
  }, [hatchEnabled])

  return (
    <group renderOrder={1}>
      {planes.map((pln, i) => {
        // Calculate point on cutting plane closest to assembly center in Three.js world space
        const distToCenter = pln.normal.dot(centerThree) + pln.constant
        const pos = centerThree.clone().addScaledVector(pln.normal, -distToCenter)
        const quat = new THREE.Quaternion()
        if (pln.normal.lengthSq() > 0.5) {
          quat.setFromUnitVectors(new THREE.Vector3(0, 0, 1), pln.normal)
        }

        return (
          <mesh
            key={i}
            position={pos}
            quaternion={quat}
            material={capMaterial}
          >
            <planeGeometry args={[span, span]} />
          </mesh>
        )
      })}
    </group>
  )
}

// Helper to check if a component is or descends from an isolated component ID
function isDescendantOf(
  comp: Component,
  targetId: number,
  _byId: Map<number, Component>,
  byCadId: Map<string, Component>
): boolean {
  if (comp.id === targetId) return true
  let curr = comp
  while (curr.parent_cad_id) {
    const parent = byCadId.get(curr.parent_cad_id)
    if (!parent) break
    if (parent.id === targetId) return true
    curr = parent
  }
  return false
}

// ─── Scene content ────────────────────────────────────────────────────────────
interface SceneProps {
  showGrid: boolean
  fitViewTrigger: number
}

function Scene({ showGrid, fitViewTrigger }: SceneProps) {
  const { camera, scene, gl } = useThree()

  useEffect(() => {
    ;(window as any).THREE = THREE
    ;(window as any).__THREE_SCENE__ = scene
    ;(window as any).__THREE_CAMERA__ = camera
  }, [scene, camera])
  const store = useAssemblyStore()
  const {
    components,
    selectedComponentId,
    hiddenComponentIds,
    isolatedComponentId,
    selectComponent,
    isXRayMode,
    transparentComponentIds,
    explodeFactor,
    sectionPlaneAxis,
    sectionPlaneOffset,
    sectionPlanes,
    sectionCombinedMode,
    showSectionCaps,
    activeSectionResult,
    obstructingComponentIds,
    activeClearanceLine,
    activeAccessVector,
    selectedObstructionReport,
    dependencyGraph,
    isSectionMode,
    sectionHatchEnabled,
    assemblyBoundingBox,
    closeSectionMode,
  } = store

  // Enable local clipping on WebGLRenderer
  useEffect(() => {
    gl.localClippingEnabled = true
  }, [gl])

  // Build lookup maps for assembly hierarchy
  const byId = useMemo(() => new Map(components.map((c) => [c.id, c])), [components])
  const byCadId = useMemo(
    () => new Map(components.map((c) => [c.cad_entity_id, c])),
    [components]
  )

  // Identify components to highlight: if an assembly is selected, its leaf parts are also highlighted
  const selectedIds = useMemo(() => {
    const set = new Set<number>()
    if (selectedComponentId == null) return set
    set.add(selectedComponentId)
    for (const c of components) {
      if (isDescendantOf(c, selectedComponentId, byId, byCadId)) {
        set.add(c.id)
      }
    }
    return set
  }, [selectedComponentId, components, byId, byCadId])

  // Compute assembly center for radial exploded view (Phase 1)
  const assemblyCenter = useMemo(() => {
    const box = new THREE.Box3()
    for (const c of components) {
      if (c.is_leaf && c.bounding_box) {
        box.expandByPoint(new THREE.Vector3(c.bounding_box.xmin, c.bounding_box.ymin, c.bounding_box.zmin))
        box.expandByPoint(new THREE.Vector3(c.bounding_box.xmax, c.bounding_box.ymax, c.bounding_box.zmax))
      }
    }
    if (box.isEmpty()) return new THREE.Vector3(0, 0, 0)
    const center = new THREE.Vector3()
    box.getCenter(center)
    return center
  }, [components])

  // Map components to their verified extraction direction vector (C5)
  const stepDirections = useMemo(() => {
    const map = new Map<number, [number, number, number]>()
    if (dependencyGraph?.sequence) {
      for (const s of dependencyGraph.sequence) {
        if (s.direction_vector) {
          map.set(s.component_id, s.direction_vector)
          if (s.member_component_ids) {
            for (const mid of s.member_component_ids) {
              map.set(mid, s.direction_vector)
            }
          }
        }
      }
    }
    return map
  }, [dependencyGraph])

  // Compute individual exploded view displacement vectors along own best removal direction (C5)
  const displacements = useMemo(() => {
    const map = new Map<number, [number, number, number]>()
    if (explodeFactor <= 0) return map

    const maxDisp = 120.0 * explodeFactor
    for (const c of components) {
      if (!c.is_leaf || !c.bounding_box) continue

      const bestVec = stepDirections.get(c.id)
      let dir: THREE.Vector3
      if (bestVec) {
        dir = new THREE.Vector3(bestVec[0], bestVec[1], bestVec[2]).normalize()
      } else {
        const cx = (c.bounding_box.xmin + c.bounding_box.xmax) / 2
        const cy = (c.bounding_box.ymin + c.bounding_box.ymax) / 2
        const cz = (c.bounding_box.zmin + c.bounding_box.zmax) / 2
        dir = new THREE.Vector3(cx - assemblyCenter.x, cy - assemblyCenter.y, cz - assemblyCenter.z)
        if (dir.lengthSq() < 1.0) {
          dir.set(0, 0, 1)
        } else {
          dir.normalize()
        }
      }
      map.set(c.id, [dir.x * maxDisp, dir.y * maxDisp, dir.z * maxDisp])
    }
    return map
  }, [components, assemblyCenter, explodeFactor, stepDirections])

  // 3.4 Selected Part's Best Removal Direction (Primary Visual: arrow + translucent cone)
  const selectedRemovalVisual = useMemo(() => {
    if (selectedComponentId == null) return null
    const comp = components.find((c) => c.id === selectedComponentId)
    if (!comp || !comp.bounding_box) return null

    const bb = comp.bounding_box
    const center: [number, number, number] = [
      (bb.xmin + bb.xmax) / 2,
      (bb.ymin + bb.ymax) / 2,
      (bb.zmin + bb.zmax) / 2,
    ]

    let dir: [number, number, number] = [0, 0, 1]
    let label = ''

    if (
      selectedObstructionReport &&
      selectedObstructionReport.target_component_id === selectedComponentId &&
      selectedObstructionReport.best_direction_vector
    ) {
      dir = selectedObstructionReport.best_direction_vector
      label = selectedObstructionReport.best_direction || ''
    } else if (comp.display_name.toLowerCase().includes('motor')) {
      // Motor's verified single source of truth is -X
      dir = [-1, 0, 0]
      label = '-X'
    } else {
      const stepVec = stepDirections.get(comp.id)
      if (stepVec) {
        dir = stepVec
      }
    }

    return { origin: center, dir, label }
  }, [selectedComponentId, components, selectedObstructionReport, stepDirections])

  const selectedCompBBox = useMemo(() => {
    if (selectedComponentId == null) return null
    const comp = components.find((c) => c.id === selectedComponentId)
    return comp?.bounding_box || null
  }, [selectedComponentId, components])

  // Center of assembly mapped to Three.js coordinates
  const assemblyCenterThree = useMemo(() => {
    if (!assemblyBoundingBox) return new THREE.Vector3(0, 0, 0)
    const { center } = assemblyBoundingBox
    // CAD (x, y, z) -> Three.js (x, z, -y)
    return new THREE.Vector3(center[0], center[2], -center[1])
  }, [assemblyBoundingBox])

  // Span of cap plane based on assembly bounding box
  const capSpan = useMemo(() => {
    if (!assemblyBoundingBox) return 300
    const { size } = assemblyBoundingBox
    const maxDim = Math.max(size[0], size[1], size[2])
    return Math.max(160, Math.round(maxDim * 1.3))
  }, [assemblyBoundingBox])

  // Construct multi-axis section clipping planes (mapped from CAD Z-up to Three.js Y-up)
  const activeClippingPlanes = useMemo(() => {
    const planes: THREE.Plane[] = []
    if (sectionPlanes && sectionPlanes.length > 0) {
      for (const p of sectionPlanes) {
        if (!p.enabled) continue
        let nx = p.normal[0]
        let ny = p.normal[1]
        let nz = p.normal[2]
        if (!isFinite(nx) || !isFinite(ny) || !isFinite(nz)) continue
        const nLen = Math.hypot(nx, ny, nz)
        if (nLen < 1e-4) continue

        if (p.flipped) {
          nx = -nx
          ny = -ny
          nz = -nz
        }
        // Map CAD (x, y, z) where Z is up to Three.js coordinates
        // Under group rotation [-Math.PI / 2, 0, 0]:
        // (x_cad, y_cad, z_cad) -> (x_cad, z_cad, -y_cad)
        const tNormal = new THREE.Vector3(nx / nLen, nz / nLen, -ny / nLen).normalize()
        const pt = p.point || (assemblyBoundingBox ? assemblyBoundingBox.center : [0, 0, 0])
        const px = pt[0] + (nx / nLen) * p.offset
        const py = pt[1] + (ny / nLen) * p.offset
        const pz = pt[2] + (nz / nLen) * p.offset
        const tPoint = new THREE.Vector3(px, pz, -py)
        const constant = -tNormal.dot(tPoint)
        if (isFinite(constant)) {
          planes.push(new THREE.Plane(tNormal, constant))
        }
      }
    }

    if (planes.length === 0 && sectionPlaneAxis !== 'off') {
      let normal = new THREE.Vector3(0, -1, 0)
      if (sectionPlaneAxis === '+X') normal = new THREE.Vector3(-1, 0, 0)
      else if (sectionPlaneAxis === '-X') normal = new THREE.Vector3(1, 0, 0)
      else if (sectionPlaneAxis === '+Y') normal = new THREE.Vector3(0, 0, 1)
      else if (sectionPlaneAxis === '-Y') normal = new THREE.Vector3(0, 0, -1)
      else if (sectionPlaneAxis === '+Z') normal = new THREE.Vector3(0, -1, 0)
      else if (sectionPlaneAxis === '-Z') normal = new THREE.Vector3(0, 1, 0)
      planes.push(new THREE.Plane(normal, -sectionPlaneOffset))
    }

    return planes
  }, [sectionPlanes, sectionPlaneAxis, sectionPlaneOffset, assemblyBoundingBox])

  // Filter visible components considering isolation and hidden sets (including hierarchy)
  const visibleLeafComponents = useMemo(() => {
    return components.filter((c) => {
      // Containers have no direct mesh
      if (!c.is_leaf) return false

      // Check isolation
      if (isolatedComponentId != null) {
        if (!isDescendantOf(c, isolatedComponentId, byId, byCadId)) {
          return false
        }
      }

      // Check if self is hidden
      if (hiddenComponentIds.has(c.id)) return false

      // Check if any ancestor assembly is hidden
      let curr = c
      while (curr.parent_cad_id) {
        const parent = byCadId.get(curr.parent_cad_id)
        if (!parent) break
        if (hiddenComponentIds.has(parent.id)) return false
        curr = parent
      }

      return true
    })
  }, [components, isolatedComponentId, hiddenComponentIds, byId, byCadId])

  // Fit to view
  useEffect(() => {
    if (fitViewTrigger === 0) return
    const box = new THREE.Box3()
    scene.traverse((obj) => {
      if (obj instanceof THREE.Mesh) box.expandByObject(obj)
    })
    if (box.isEmpty()) return
    const sphere = new THREE.Sphere()
    box.getBoundingSphere(sphere)
    if (isNaN(sphere.radius) || sphere.radius === 0) return
    const cam = camera as THREE.PerspectiveCamera
    const fov = (cam.fov * Math.PI) / 180
    const dist = (sphere.radius / Math.sin(fov / 2)) * 1.3
    const dir = camera.position.clone().sub(sphere.center).normalize()
    if (dir.lengthSq() === 0) dir.set(0, 0, 1)
    camera.position.copy(sphere.center).addScaledVector(dir, dist)
    camera.lookAt(sphere.center)
  }, [fitViewTrigger, camera, scene])

  useFrame(() => {})

  return (
    <>
      <ambientLight intensity={0.6} />
      <directionalLight position={[20, 40, 30]} intensity={1.3} castShadow />
      <directionalLight position={[-20, -30, -20]} intensity={0.4} />
      {showGrid && <gridHelper args={[300, 50, '#3b82f6', '#334155']} />}

      <Suspense fallback={null}>
        <group rotation={[-Math.PI / 2, 0, 0]}>
          {visibleLeafComponents.map((comp: Component) => {
            const compNameLower = comp.display_name.toLowerCase()
            const isHousingCover =
              compNameLower.includes('housing') ||
              compNameLower.includes('cover') ||
              compNameLower.includes('casing') ||
              compNameLower.includes('cap')

            return (
              <ComponentMesh
                key={comp.id}
                component={comp}
                isSelected={selectedIds.has(comp.id)}
                isObstructing={obstructingComponentIds.has(comp.id)}
                isTranslucent={transparentComponentIds.has(comp.id)}
                isXRay={isXRayMode && isHousingCover}
                isVisible={true}
                displacement={displacements.get(comp.id) || [0, 0, 0]}
                clippingPlanes={isSectionMode ? activeClippingPlanes : []}
                clipIntersection={sectionCombinedMode === 'intersection'}
                onSelect={selectComponent}
              />
            )
          })}

          {/* Exact Analytical BREP Section Outlines (Phase D) */}
          {isSectionMode && activeSectionResult && activeSectionResult.component_sections.length > 0 && (
            <BrepSectionOutlinesOverlay sections={activeSectionResult.component_sections} />
          )}

          {/* Section Plane Clearance Dimension Line (Phase D) */}
          {isSectionMode && activeSectionResult?.clearance && (
            <ClearanceLineOverlay
              p1={activeSectionResult.clearance.point_a}
              p2={activeSectionResult.clearance.point_b}
              dist={activeSectionResult.clearance.clearance_mm}
              label={`Section Clearance: ${activeSectionResult.clearance.clearance_mm.toFixed(3)} mm (${activeSectionResult.clearance.component_a_name} - ${activeSectionResult.clearance.component_b_name})`}
            />
          )}

          {/* Milestone 2 Phase 6: 3D Visual Findings Overlays */}
          {activeClearanceLine && (
            <ClearanceLineOverlay
              p1={activeClearanceLine.p1}
              p2={activeClearanceLine.p2}
              dist={activeClearanceLine.dist}
              label={activeClearanceLine.label}
            />
          )}

          {/* 3.4 Primary Visual: Selected part's best removal direction */}
          {(activeAccessVector || selectedRemovalVisual) && (
            <AccessVectorOverlay
              origin={(activeAccessVector || selectedRemovalVisual)!.origin}
              dir={(activeAccessVector || selectedRemovalVisual)!.dir}
              label={(activeAccessVector || selectedRemovalVisual)!.label}
              componentBBox={selectedCompBBox}
            />
          )}
        </group>
      </Suspense>

      {/* Part 2: Sectioning Gizmo & Cap Planes wrapped in Error Boundary */}
      {isSectionMode && (
        <SectionErrorBoundary onReset={closeSectionMode}>
          {showSectionCaps && activeClippingPlanes.length > 0 && (
            <SectionCapPlanes
              planes={activeClippingPlanes}
              clipIntersection={sectionCombinedMode === 'intersection'}
              hatchEnabled={sectionHatchEnabled}
              assemblyCenterThree={assemblyCenterThree}
              capSpan={capSpan}
            />
          )}
          <SectionGizmo />
        </SectionErrorBoundary>
      )}
    </>
  )
}

// ─── Main viewer export ───────────────────────────────────────────────────────
interface AssemblyViewerProps {
  showGrid: boolean
  onToggleGrid: () => void
  fitViewTrigger: number
}

function CameraSync({ onCamera }: { onCamera: (c: THREE.Camera) => void }) {
  const { camera } = useThree()
  useEffect(() => {
    onCamera(camera)
  }, [camera, onCamera])
  return null
}

export function AssemblyViewerCanvas({
  showGrid,
  fitViewTrigger,
  onCameraReady,
}: {
  showGrid: boolean
  fitViewTrigger: number
  onCameraReady: (c: THREE.Camera) => void
}) {
  const { navSettings } = useAssemblyStore()
  const isOrtho = navSettings.projection === 'orthographic'

  return (
    <Canvas
      style={{ background: '#0a0f1d' }}
      camera={{ position: [0, 80, 220], fov: 45, near: 0.1, far: 20000, up: [0, 1, 0] }}
      gl={{ antialias: true, localClippingEnabled: true }}
      onContextMenu={(e) => e.preventDefault()}
    >
      {isOrtho ? (
        <OrthographicCamera makeDefault position={[0, 80, 220]} zoom={2.5} near={0.1} far={20000} up={[0, 1, 0]} />
      ) : (
        <PerspectiveCamera makeDefault position={[0, 80, 220]} fov={45} near={0.1} far={20000} up={[0, 1, 0]} />
      )}
      <CameraSync onCamera={onCameraReady} />
      <Scene showGrid={showGrid} fitViewTrigger={fitViewTrigger} />
      <CADCameraController fitViewTrigger={fitViewTrigger} />
    </Canvas>
  )
}

export default function AssemblyViewer({ showGrid, fitViewTrigger }: AssemblyViewerProps) {
  const { components, isLoading } = useAssemblyStore()
  const [mainCamera, setMainCamera] = useState<THREE.Camera | null>(null)

  return (
    <div className="relative w-full h-full select-none" onContextMenu={(e) => e.preventDefault()}>
      {isLoading && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-slate-950/70 backdrop-blur-xs">
          <div className="flex flex-col items-center gap-3">
            <div className="w-10 h-10 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
            <span className="text-slate-300 text-sm font-medium">Extracting CAD Meshes…</span>
          </div>
        </div>
      )}
      {components.length === 0 && !isLoading && (
        <div className="absolute inset-0 z-10 flex items-center justify-center pointer-events-none">
          <p className="text-slate-500 text-sm">No components to display</p>
        </div>
      )}
      <AssemblyViewerCanvas
        showGrid={showGrid}
        fitViewTrigger={fitViewTrigger}
        onCameraReady={setMainCamera}
      />

      {/* Part 1: Interactive ViewCube (Top Right, ~90px) */}
      {mainCamera && <ViewCube mainCamera={mainCamera} />}

      {/* Part 1: Mouse-less / Trackpad Navigation Bar (Bottom Left) */}
      <NavigationBar onFitAll={() => {}} />

      {/* Part 2: Compact Engineering-Graphics Section Bar (Bottom Center) */}
      <CompactSectionBar />
    </div>
  )
}

import { useRef, useEffect, useState, Suspense, useMemo } from 'react'
import { Canvas, useThree, useFrame } from '@react-three/fiber'
import { OrbitControls, Html } from '@react-three/drei'
import * as THREE from 'three'
import { getComponentMesh } from '../../api/client'
import { useAssemblyStore } from '../../store/assemblyStore'
import type { MeshData, Component } from '../../types/assembly'

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
  clippingPlane: THREE.Plane | null
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
  clippingPlane,
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

  const clippingPlanes = clippingPlane ? [clippingPlane] : []

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

// ─── 3D Visual Access Vector Arrow (Phase 6) ────────────────────────────────
function AccessVectorOverlay({
  origin,
  dir,
  label,
}: {
  origin: [number, number, number]
  dir: [number, number, number]
  label: string
}) {
  const arrowRef = useRef<THREE.ArrowHelper>(null)
  const length = 45.0
  const color = 0x38bdf8

  const arrowDir = useMemo(
    () => new THREE.Vector3(...dir).normalize(),
    [dir]
  )
  const arrowOrigin = useMemo(
    () => new THREE.Vector3(...origin),
    [origin]
  )

  const tipPos: [number, number, number] = [
    origin[0] + arrowDir.x * (length + 5),
    origin[1] + arrowDir.y * (length + 5),
    origin[2] + arrowDir.z * (length + 5),
  ]

  return (
    <group>
      <primitive
        object={new THREE.ArrowHelper(arrowDir, arrowOrigin, length, color, 8, 4)}
        ref={arrowRef}
      />
      <Html position={tipPos} center distanceFactor={140}>
        <div className="bg-blue-950/90 text-blue-300 border border-blue-500/60 rounded px-2 py-0.5 text-[10px] font-mono font-semibold whitespace-nowrap shadow-lg pointer-events-none">
          {label}
        </div>
      </Html>
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
    obstructingComponentIds,
    activeClearanceLine,
    activeAccessVector,
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

  // Compute individual exploded view displacement vectors (Phase 1)
  const displacements = useMemo(() => {
    const map = new Map<number, [number, number, number]>()
    if (explodeFactor <= 0) return map

    const maxDisp = 110.0 * explodeFactor
    for (const c of components) {
      if (!c.is_leaf || !c.bounding_box) continue
      const cx = (c.bounding_box.xmin + c.bounding_box.xmax) / 2
      const cy = (c.bounding_box.ymin + c.bounding_box.ymax) / 2
      const cz = (c.bounding_box.zmin + c.bounding_box.zmax) / 2
      const dir = new THREE.Vector3(cx - assemblyCenter.x, cy - assemblyCenter.y, cz - assemblyCenter.z)
      if (dir.lengthSq() < 1.0) {
        dir.set(0, 0, 1)
      } else {
        dir.normalize()
      }
      map.set(c.id, [dir.x * maxDisp, dir.y * maxDisp, dir.z * maxDisp])
    }
    return map
  }, [components, assemblyCenter, explodeFactor])

  // Construct section clipping plane (Phase 1)
  const clippingPlane = useMemo(() => {
    if (sectionPlaneAxis === 'off') return null
    let normal = new THREE.Vector3(0, 0, -1)
    if (sectionPlaneAxis === '+X') normal = new THREE.Vector3(-1, 0, 0)
    else if (sectionPlaneAxis === '-X') normal = new THREE.Vector3(1, 0, 0)
    else if (sectionPlaneAxis === '+Y') normal = new THREE.Vector3(0, -1, 0)
    else if (sectionPlaneAxis === '-Y') normal = new THREE.Vector3(0, 1, 0)
    else if (sectionPlaneAxis === '+Z') normal = new THREE.Vector3(0, 0, -1)
    else if (sectionPlaneAxis === '-Z') normal = new THREE.Vector3(0, 0, 1)

    return new THREE.Plane(normal, -sectionPlaneOffset)
  }, [sectionPlaneAxis, sectionPlaneOffset])

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
              clippingPlane={clippingPlane}
              onSelect={selectComponent}
            />
          )
        })}

        {/* Milestone 2 Phase 6: 3D Visual Findings Overlays */}
        {activeClearanceLine && (
          <ClearanceLineOverlay
            p1={activeClearanceLine.p1}
            p2={activeClearanceLine.p2}
            dist={activeClearanceLine.dist}
            label={activeClearanceLine.label}
          />
        )}

        {activeAccessVector && (
          <AccessVectorOverlay
            origin={activeAccessVector.origin}
            dir={activeAccessVector.dir}
            label={activeAccessVector.label}
          />
        )}
      </Suspense>
    </>
  )
}

// ─── Main viewer export ───────────────────────────────────────────────────────
interface AssemblyViewerProps {
  showGrid: boolean
  onToggleGrid: () => void
  fitViewTrigger: number
}

export function AssemblyViewerCanvas({
  showGrid,
  fitViewTrigger,
}: {
  showGrid: boolean
  fitViewTrigger: number
}) {
  return (
    <Canvas
      style={{ background: '#0a0f1d' }}
      camera={{ position: [0, 80, 220], fov: 45, near: 0.1, far: 20000 }}
      gl={{ antialias: true, localClippingEnabled: true }}
    >
      <Scene showGrid={showGrid} fitViewTrigger={fitViewTrigger} />
      <OrbitControls makeDefault enableDamping dampingFactor={0.06} />
    </Canvas>
  )
}

export default function AssemblyViewer({ showGrid, fitViewTrigger }: AssemblyViewerProps) {
  const { components, isLoading } = useAssemblyStore()

  return (
    <div className="relative w-full h-full">
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
      <AssemblyViewerCanvas showGrid={showGrid} fitViewTrigger={fitViewTrigger} />
    </div>
  )
}

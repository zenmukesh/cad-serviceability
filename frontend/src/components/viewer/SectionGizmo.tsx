import React, { useRef, useMemo, useState, useEffect } from 'react'
import * as THREE from 'three'
import { useAssemblyStore } from '../../store/assemblyStore'

export const SectionGizmo: React.FC = () => {
  const {
    isSectionMode,
    sectionTiltDeg,
    setSectionOffsetMm,
    setSectionTiltDeg,
    setSectionTiltToward,
    sectionPlanes,
    assemblyBoundingBox,
  } = useAssemblyStore()

  const activePlane = sectionPlanes[0]

  const [isHoveredArrow, setIsHoveredArrow] = useState(false)
  const [isHoveredRing1, setIsHoveredRing1] = useState(false)
  const [isHoveredRing2, setIsHoveredRing2] = useState(false)
  const [activeDrag, setActiveDrag] = useState<'arrow' | 'ring1' | 'ring2' | null>(null)

  const dragStartRef = useRef<{ y: number; x: number; startVal: number; altKey: boolean } | null>(null)

  if (!isSectionMode || !activePlane || !activePlane.enabled) return null

  // Plane normal in CAD space -> mapped to Three.js space: (nx, nz, -ny)
  const [nx, ny, nz] = activePlane.normal
  const planeNormalThree = useMemo(() => {
    const len = Math.hypot(nx, ny, nz)
    if (!isFinite(nx) || !isFinite(ny) || !isFinite(nz) || len < 1e-5) {
      return new THREE.Vector3(0, 1, 0)
    }
    let tNorm = new THREE.Vector3(nx / len, nz / len, -ny / len).normalize()
    if (activePlane.flipped) tNorm.negate()
    return tNorm
  }, [nx, ny, nz, activePlane.flipped])

  // Center position of plane in Three.js space (anchored at assembly center)
  const planePosThree = useMemo(() => {
    const pt = activePlane.point || (assemblyBoundingBox ? assemblyBoundingBox.center : [0, 0, 0])
    // Map CAD (x, y, z) -> Three.js (x, z, -y)
    const ptThree = new THREE.Vector3(pt[0], pt[2], -pt[1])
    return ptThree.addScaledVector(planeNormalThree, activePlane.offset)
  }, [planeNormalThree, activePlane.offset, activePlane.point, assemblyBoundingBox])

  // Orientation of plane (aligning +Z of plane geometry to planeNormalThree)
  const planeQuat = useMemo(() => {
    const q = new THREE.Quaternion()
    if (planeNormalThree.lengthSq() > 0.5) {
      q.setFromUnitVectors(new THREE.Vector3(0, 0, 1), planeNormalThree)
    }
    return q
  }, [planeNormalThree])

  // Sizing of gizmo plane matching assembly dimensions
  const gizmoSpan = useMemo(() => {
    if (!assemblyBoundingBox) return 220
    const { size } = assemblyBoundingBox
    const maxDim = Math.max(size[0], size[1], size[2])
    return Math.max(160, Math.round(maxDim * 1.2))
  }, [assemblyBoundingBox])

  // Mouse drag handling on handles
  useEffect(() => {
    const onPointerMove = (e: PointerEvent) => {
      if (!dragStartRef.current || !activeDrag) return
      const dx = e.clientX - dragStartRef.current.x
      const dy = e.clientY - dragStartRef.current.y

      if (activeDrag === 'arrow') {
        // Drag along normal
        const deltaOffset = -dy * 0.4
        const newOffset = Math.max(-150, Math.min(150, dragStartRef.current.startVal + deltaOffset))
        setSectionOffsetMm(parseFloat(newOffset.toFixed(1)))
      } else if (activeDrag === 'ring1' || activeDrag === 'ring2') {
        // Tilt drag
        const deltaAngle = (dx - dy) * 0.35
        let rawAngle = Math.max(0, Math.min(90, dragStartRef.current.startVal + deltaAngle))

        // Snap to 5 degrees unless Alt key is held
        if (!e.altKey) {
          rawAngle = Math.round(rawAngle / 5) * 5
        }

        if (activeDrag === 'ring1') {
          setSectionTiltToward('Front')
        } else {
          setSectionTiltToward('Side')
        }
        setSectionTiltDeg(rawAngle)
      }
    }

    const onPointerUp = () => {
      dragStartRef.current = null
      setActiveDrag(null)
    }

    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', onPointerUp)

    return () => {
      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('pointerup', onPointerUp)
    }
  }, [activeDrag, setSectionOffsetMm, setSectionTiltDeg, setSectionTiltToward])

  return (
    <group position={planePosThree} quaternion={planeQuat}>
      {/* 1. Translucent Plane Surface */}
      <mesh>
        <planeGeometry args={[gizmoSpan, gizmoSpan]} />
        <meshBasicMaterial
          color="#0284c7"
          transparent
          opacity={0.12}
          side={THREE.DoubleSide}
          depthWrite={false}
        />
      </mesh>

      {/* 2. Plane Outline */}
      <lineSegments>
        <edgesGeometry args={[new THREE.PlaneGeometry(gizmoSpan, gizmoSpan)]} />
        <lineBasicMaterial color="#38bdf8" linewidth={2} transparent opacity={0.65} />
      </lineSegments>

      {/* 3. Normal Arrow Handle */}
      <group position={[0, 0, 0]}>
        <mesh
          position={[0, 0, 18]}
          rotation={[Math.PI / 2, 0, 0]}
          onPointerDown={(e) => {
            e.stopPropagation()
            setActiveDrag('arrow')
            dragStartRef.current = { x: e.clientX, y: e.clientY, startVal: activePlane.offset, altKey: e.altKey }
          }}
          onPointerOver={() => setIsHoveredArrow(true)}
          onPointerOut={() => setIsHoveredArrow(false)}
        >
          <cylinderGeometry args={[1.4, 1.4, 36, 16]} />
          <meshBasicMaterial color={isHoveredArrow || activeDrag === 'arrow' ? '#38bdf8' : '#0284c7'} />
        </mesh>
        <mesh
          position={[0, 0, 36]}
          rotation={[Math.PI / 2, 0, 0]}
          onPointerDown={(e) => {
            e.stopPropagation()
            setActiveDrag('arrow')
            dragStartRef.current = { x: e.clientX, y: e.clientY, startVal: activePlane.offset, altKey: e.altKey }
          }}
        >
          <coneGeometry args={[4.5, 10, 16]} />
          <meshBasicMaterial color={isHoveredArrow || activeDrag === 'arrow' ? '#38bdf8' : '#0284c7'} />
        </mesh>
      </group>

      {/* 4. Ring Handle 1 (In-plane X tilt - Cyan arc) */}
      <mesh
        rotation={[0, 0, 0]}
        onPointerDown={(e) => {
          e.stopPropagation()
          setActiveDrag('ring1')
          dragStartRef.current = { x: e.clientX, y: e.clientY, startVal: sectionTiltDeg, altKey: e.altKey }
        }}
        onPointerOver={() => setIsHoveredRing1(true)}
        onPointerOut={() => setIsHoveredRing1(false)}
      >
        <torusGeometry args={[gizmoSpan * 0.35, 1.8, 16, 64, Math.PI]} />
        <meshBasicMaterial color={isHoveredRing1 || activeDrag === 'ring1' ? '#22d3ee' : '#0891b2'} />
      </mesh>

      {/* 5. Ring Handle 2 (In-plane Y tilt - Amber arc) */}
      <mesh
        rotation={[0, 0, Math.PI / 2]}
        onPointerDown={(e) => {
          e.stopPropagation()
          setActiveDrag('ring2')
          dragStartRef.current = { x: e.clientX, y: e.clientY, startVal: sectionTiltDeg, altKey: e.altKey }
        }}
        onPointerOver={() => setIsHoveredRing2(true)}
        onPointerOut={() => setIsHoveredRing2(false)}
      >
        <torusGeometry args={[gizmoSpan * 0.3, 1.8, 16, 64, Math.PI]} />
        <meshBasicMaterial color={isHoveredRing2 || activeDrag === 'ring2' ? '#fbbf24' : '#d97706'} />
      </mesh>
    </group>
  )
}
export default SectionGizmo

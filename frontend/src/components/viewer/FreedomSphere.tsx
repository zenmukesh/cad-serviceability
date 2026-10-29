import React, { useMemo, useRef } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import * as THREE from 'three'
import { X } from 'lucide-react'
import type { ComponentObstructionReport } from '../../types/serviceability'

interface FreedomSphereProps {
  report: ComponentObstructionReport | null
  componentName?: string
  onClose?: () => void
}

/**
 * Derive nearest cardinal axis and angle from direction vector
 */
export function deriveCardinalLabel(vec: [number, number, number]): { axis: string; angleDeg: number } {
  const dir = new THREE.Vector3(...vec).normalize()
  const cardinals: [string, [number, number, number]][] = [
    ['+X', [1, 0, 0]], ['-X', [-1, 0, 0]],
    ['+Y', [0, 1, 0]], ['-Y', [0, -1, 0]],
    ['+Z', [0, 0, 1]], ['-Z', [0, 0, -1]],
  ]
  let best = '+Z'
  let maxDot = -2
  for (const [name, cv] of cardinals) {
    const dot = dir.x * cv[0] + dir.y * cv[1] + dir.z * cv[2]
    if (dot > maxDot) {
      maxDot = dot
      best = name
    }
  }
  const deg = Math.acos(Math.max(-1, Math.min(1, maxDot))) * (180 / Math.PI)
  return { axis: best, angleDeg: deg }
}

function SphereContent({
  samples,
  bestDir,
  coneAngle,
}: {
  samples: Array<{ vector: [number, number, number]; is_free: boolean }>
  bestDir: [number, number, number]
  coneAngle: number
}) {
  const groupRef = useRef<THREE.Group>(null)

  // Gentle rotation
  useFrame((_, delta) => {
    if (groupRef.current) {
      groupRef.current.rotation.z += delta * 0.12
    }
  })

  // Points geometry from 162 samples + explicitly verified bestDir point
  const pointsGeo = useMemo(() => {
    const positions: number[] = []
    const colors: number[] = []

    for (const s of samples) {
      positions.push(s.vector[0], s.vector[1], s.vector[2])
      if (s.is_free) {
        colors.push(0.06, 0.73, 0.51) // Emerald green
      } else {
        colors.push(0.94, 0.25, 0.37) // Rose red
      }
    }

    // Always include the verified best direction as a bright green point
    const bVec = new THREE.Vector3(...bestDir).normalize()
    positions.push(bVec.x, bVec.y, bVec.z)
    colors.push(0.1, 0.95, 0.6)

    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
    geo.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3))
    return geo
  }, [samples, bestDir])

  // Continuous freedom cone geometry (minimum visible angle for narrow cones)
  const coneMesh = useMemo(() => {
    // Effective visual half angle: at least 4 degrees so narrow cones remain visible
    const effectiveAngle = Math.max(4.0, coneAngle)
    const rad = (effectiveAngle * Math.PI) / 180
    const height = 1.05
    const radius = Math.tan(rad) * height

    const coneGeo = new THREE.ConeGeometry(radius, height, 32, 1, true)
    coneGeo.translate(0, -height / 2, 0)
    coneGeo.rotateX(Math.PI / 2)

    const dirVec = new THREE.Vector3(...bestDir).normalize()
    const quat = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 0, 1), dirVec)
    coneGeo.applyQuaternion(quat)

    return coneGeo
  }, [coneAngle, bestDir])

  const bestDirVec = useMemo(() => new THREE.Vector3(...bestDir).normalize(), [bestDir])

  return (
    <group ref={groupRef}>
      {/* Semi-transparent reference unit sphere */}
      <mesh>
        <sphereGeometry args={[0.98, 24, 24]} />
        <meshBasicMaterial color="#1e293b" wireframe transparent opacity={0.2} />
      </mesh>

      {/* Fibonacci Sphere Samples + Verified Ray Point */}
      <points geometry={pointsGeo}>
        <pointsMaterial size={6.0} vertexColors sizeAttenuation={false} />
      </points>

      {/* Continuous Translucent Freedom Cone */}
      {coneMesh && (
        <mesh geometry={coneMesh}>
          <meshBasicMaterial
            color="#10b981"
            transparent
            opacity={0.35}
            side={THREE.DoubleSide}
            depthWrite={false}
          />
        </mesh>
      )}

      {/* Optimal Direction Arrow */}
      <primitive
        object={
          new THREE.ArrowHelper(
            bestDirVec,
            new THREE.Vector3(0, 0, 0),
            1.4,
            0x10b981,
            0.22,
            0.12
          )
        }
      />
    </group>
  )
}

export const FreedomSphere: React.FC<FreedomSphereProps> = ({
  report,
  componentName,
  onClose,
}) => {
  if (!report) return null

  // Single source of truth for best direction vector:
  // If directions list contains a clear direction matching best_direction, use its direction_vector
  let bestVec: [number, number, number] = [0, 0, 1]
  if (report.directions && report.directions.length > 0) {
    const match = report.directions.find((d) => d.direction_name === report.best_direction)
    if (match) {
      bestVec = match.direction_vector
    } else {
      const bestClear = report.directions.find((d) => d.is_clear)
      if (bestClear) {
        bestVec = bestClear.direction_vector
      } else if (report.best_direction_vector) {
        bestVec = report.best_direction_vector
      }
    }
  } else if (report.best_direction_vector) {
    bestVec = report.best_direction_vector
  }

  // Derive axis label directly from bestVec
  const { axis: derivedAxis } = deriveCardinalLabel(bestVec)

  const samples = report.freedom_sphere_samples || []
  const freeSampleCount = samples.filter((s) => s.is_free).length
  const totalCount = samples.length || 162

  const rawConeDeg = report.freedom_cone_half_angle_deg

  // Formatting cone text: Never print "0.0 deg" for a nonzero or verified direction
  let coneText = ''
  if (rawConeDeg != null && rawConeDeg >= 1.0) {
    coneText = `θ = ±${rawConeDeg.toFixed(1)}°`
  } else {
    coneText = '< 1° (tight fit)'
  }

  // Freedom status message
  let feasibleStatus = ''
  if (freeSampleCount > 0) {
    feasibleStatus = `${freeSampleCount} / ${totalCount} directions`
  } else {
    feasibleStatus = 'Narrow free cone (< 1°)'
  }

  return (
    <div
      className="mt-2 w-full bg-slate-900/95 backdrop-blur-md border border-slate-700/80 rounded-xl p-3 shadow-xl relative"
      data-testid="freedom-sphere-container"
    >
      {/* Header with Title and Close button */}
      <div className="flex items-center justify-between border-b border-slate-800 pb-2 mb-2">
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <span className="text-[11px] font-bold uppercase tracking-wider text-slate-200">
            Freedom Sphere Inspector
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span
            data-testid="freedom-sphere-cone-badge"
            className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-950/80 text-emerald-300 border border-emerald-700/50"
          >
            {coneText}
          </span>
          {onClose && (
            <button
              onClick={onClose}
              data-testid="freedom-sphere-close-btn"
              className="text-slate-400 hover:text-white p-0.5 rounded transition-colors"
              title="Close (Esc)"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* 3D Sphere Canvas */}
      <div className="relative w-full h-44 bg-slate-950/90 rounded-lg overflow-hidden border border-slate-800">
        <Canvas
          camera={{ position: [1.6, 1.6, 1.8], fov: 42, up: [0, 0, 1] }}
          gl={{ antialias: true }}
        >
          <ambientLight intensity={0.8} />
          <pointLight position={[10, 10, 10]} intensity={1.2} />
          <SphereContent
            samples={samples}
            bestDir={bestVec}
            coneAngle={rawConeDeg || 0.8}
          />
          <OrbitControls enableZoom={false} enablePan={false} autoRotate={false} />
        </Canvas>
      </div>

      {/* Vector and Feasibility Summary */}
      <div className="mt-2.5 space-y-1.5 text-[11px]">
        <div className="flex justify-between items-center text-slate-400 bg-slate-950/50 px-2 py-1 rounded border border-slate-800/60">
          <span>Best Direction:</span>
          <span
            data-testid="freedom-sphere-best-vector"
            className="font-mono text-cyan-300 font-bold"
          >
            {derivedAxis} [{bestVec[0].toFixed(2)}, {bestVec[1].toFixed(2)}, {bestVec[2].toFixed(2)}]
          </span>
        </div>
        <div className="flex justify-between items-center text-slate-400 bg-slate-950/50 px-2 py-1 rounded border border-slate-800/60">
          <span>Feasible Directions:</span>
          <span
            data-testid="freedom-sphere-feasible-status"
            className="font-mono text-emerald-400 font-semibold"
          >
            {feasibleStatus}
          </span>
        </div>
        {componentName && (
          <div className="text-[10px] text-slate-500 pt-1 flex justify-between border-t border-slate-800">
            <span>Inspecting Component:</span>
            <span className="text-slate-300 font-medium">{componentName}</span>
          </div>
        )}
      </div>
    </div>
  )
}

export default FreedomSphere

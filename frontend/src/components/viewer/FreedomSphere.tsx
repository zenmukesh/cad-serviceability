import { useMemo, useRef } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import * as THREE from 'three'
import type { ComponentObstructionReport } from '../../types/serviceability'

interface FreedomSphereProps {
  report: ComponentObstructionReport | null
  componentName?: string
}

function SphereContent({ report }: { report: ComponentObstructionReport }) {
  const groupRef = useRef<THREE.Group>(null)

  // Rotate slowly for presentation
  useFrame((_, delta) => {
    if (groupRef.current) {
      groupRef.current.rotation.z += delta * 0.15
    }
  })

  const samples = report.freedom_sphere_samples || []
  const bestDir = report.best_direction_vector || [0, 0, 1]
  const coneAngle = report.freedom_cone_half_angle_deg || 0

  // Points geometry
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

    const geo = new THREE.BufferGeometry()
    if (positions.length > 0) {
      geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
      geo.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3))
    }
    return geo
  }, [samples])

  // Freedom cone geometry
  const coneMesh = useMemo(() => {
    if (coneAngle <= 0.1) return null
    const rad = (coneAngle * Math.PI) / 180
    const height = 1.05
    const radius = Math.tan(rad) * height

    const coneGeo = new THREE.ConeGeometry(radius, height, 32, 1, true)
    // Rotate cone to align along +Z, with tip at (0,0,0)
    coneGeo.translate(0, -height / 2, 0)
    coneGeo.rotateX(Math.PI / 2)

    // Orient cone along bestDir
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
        <meshBasicMaterial color="#1e293b" wireframe transparent opacity={0.18} />
      </mesh>

      {/* 162-point Fibonacci Sphere Samples */}
      {samples.length > 0 && (
        <points geometry={pointsGeo}>
          <pointsMaterial size={5.5} vertexColors sizeAttenuation={false} />
        </points>
      )}

      {/* Freedom Cone Visual */}
      {coneMesh && (
        <mesh geometry={coneMesh}>
          <meshBasicMaterial
            color="#38bdf8"
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
            1.45,
            0x38bdf8,
            0.2,
            0.12
          )
        }
      />
    </group>
  )
}

export default function FreedomSphere({ report, componentName }: FreedomSphereProps) {
  if (!report) return null

  const bestVec = report.best_direction_vector || [0, 0, 1]
  const coneDeg = report.freedom_cone_half_angle_deg
  const freeCount = (report.freedom_sphere_samples || []).filter((s) => s.is_free).length
  const totalCount = (report.freedom_sphere_samples || []).length || 162

  return (
    <div className="absolute bottom-4 left-4 z-20 w-56 bg-slate-900/90 backdrop-blur-md border border-slate-700/80 rounded-xl p-2.5 shadow-2xl pointer-events-auto">
      <div className="flex items-center justify-between border-b border-slate-800 pb-1.5 mb-1.5">
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-200">
            Freedom Sphere
          </span>
        </div>
        <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-blue-950 text-blue-300 border border-blue-800/60">
          {coneDeg != null ? `θ = ${coneDeg.toFixed(1)}°` : '0.0° cone'}
        </span>
      </div>

      <div className="relative w-full h-36 bg-slate-950/80 rounded-lg overflow-hidden border border-slate-800/60">
        <Canvas
          camera={{ position: [1.6, 1.6, 1.8], fov: 42, up: [0, 0, 1] }}
          gl={{ antialias: true }}
        >
          <ambientLight intensity={0.7} />
          <pointLight position={[10, 10, 10]} intensity={1.0} />
          <SphereContent report={report} />
          <OrbitControls enableZoom={false} enablePan={false} autoRotate={false} />
        </Canvas>
      </div>

      <div className="mt-2 space-y-1 text-[10px]">
        <div className="flex justify-between text-slate-400">
          <span>Best Vector:</span>
          <span className="font-mono text-cyan-300 font-semibold">
            [{bestVec[0].toFixed(2)}, {bestVec[1].toFixed(2)}, {bestVec[2].toFixed(2)}]
          </span>
        </div>
        <div className="flex justify-between text-slate-400">
          <span>Feasible Sphere:</span>
          <span className="font-mono text-emerald-400 font-medium">
            {freeCount} / {totalCount} directions
          </span>
        </div>
        {componentName && (
          <p className="text-[9px] text-slate-500 truncate pt-0.5 border-t border-slate-800/80">
            Target: <span className="text-slate-300">{componentName}</span>
          </p>
        )}
      </div>
    </div>
  )
}

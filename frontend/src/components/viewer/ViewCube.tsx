import React, { useRef, useEffect, useState } from 'react'
import * as THREE from 'three'
import { Home, MoreVertical } from 'lucide-react'
import { useAssemblyStore, CameraProjection } from '../../store/assemblyStore'

interface ViewCubeProps {
  mainCamera: THREE.Camera
}

// Generate labeled textures for cube faces
function createFaceTexture(label: string, isHovered: boolean = false): THREE.CanvasTexture {
  const canvas = document.createElement('canvas')
  canvas.width = 128
  canvas.height = 128
  const ctx = canvas.getContext('2d')!

  ctx.fillStyle = isHovered ? '#0284c7' : '#1e293b'
  ctx.fillRect(0, 0, 128, 128)

  ctx.strokeStyle = '#475569'
  ctx.lineWidth = 4
  ctx.strokeRect(2, 2, 124, 124)

  ctx.fillStyle = '#f8fafc'
  ctx.font = 'bold 22px system-ui, -apple-system, sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(label, 64, 64)

  const texture = new THREE.CanvasTexture(canvas)
  texture.needsUpdate = true
  return texture
}

export const ViewCube: React.FC<ViewCubeProps> = ({ mainCamera }) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const {
    navSettings,
    setNavSettings,
    triggerCameraTransition,
    components,
  } = useAssemblyStore()

  const [showContextMenu, setShowContextMenu] = useState(false)
  const [hoveredPart, setHoveredPart] = useState<string | null>(null)

  // Drag tracking on ViewCube
  const isDraggingCube = useRef(false)
  const lastMousePos = useRef<{ x: number; y: number }>({ x: 0, y: 0 })

  // Compute assembly target
  const getTarget = () => {
    const box = new THREE.Box3()
    for (const c of components) {
      if (c.is_leaf && c.bounding_box) {
        box.expandByPoint(new THREE.Vector3(c.bounding_box.xmin, c.bounding_box.zmin, -c.bounding_box.ymax))
        box.expandByPoint(new THREE.Vector3(c.bounding_box.xmax, c.bounding_box.zmax, -c.bounding_box.ymin))
      }
    }
    const center = new THREE.Vector3()
    if (!box.isEmpty()) box.getCenter(center)
    return center
  }

  const getDistance = () => {
    const target = getTarget()
    return Math.max(80, mainCamera.position.distanceTo(target))
  }

  // Camera directions for faces in Three.js world space (where CAD Z-up is Three.js Y-up)
  const FACE_DIRECTIONS: Record<string, { dir: [number, number, number]; up: [number, number, number] }> = {
    TOP: { dir: [0, 1, 0.0001], up: [0, 0, -1] },
    BOTTOM: { dir: [0, -1, 0.0001], up: [0, 0, 1] },
    FRONT: { dir: [0, 0, 1], up: [0, 1, 0] },
    BACK: { dir: [0, 0, -1], up: [0, 1, 0] },
    RIGHT: { dir: [1, 0, 0], up: [0, 1, 0] },
    LEFT: { dir: [-1, 0, 0], up: [0, 1, 0] },
  }

  useEffect(() => {
    ;(window as any).__VIEW_CUBE__ = {
      clickFace: handleFaceClick,
      clickHome: handleHomeClick,
      getFaceDirections: () => FACE_DIRECTIONS,
    }
  }, [mainCamera])

  const handleFaceClick = (faceName: string) => {
    const config = FACE_DIRECTIONS[faceName]
    if (!config) return
    const target = getTarget()
    const dist = getDistance()
    const pos: [number, number, number] = [
      target.x + config.dir[0] * dist,
      target.y + config.dir[1] * dist,
      target.z + config.dir[2] * dist,
    ]
    triggerCameraTransition({
      position: pos,
      target: [target.x, target.y, target.z],
      up: config.up,
      durationMs: 300,
    })
  }

  const handleHomeClick = () => {
    const target = getTarget()
    const dist = getDistance()
    const inv = 1 / Math.sqrt(3)
    const pos: [number, number, number] = [
      target.x + inv * dist,
      target.y + inv * dist,
      target.z + inv * dist,
    ]
    triggerCameraTransition({
      position: pos,
      target: [target.x, target.y, target.z],
      up: [0, 1, 0],
      durationMs: 300,
    })
  }

  const handleProjectionChange = (proj: CameraProjection) => {
    setNavSettings({ projection: proj })
    setShowContextMenu(false)
  }

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true })
    renderer.setSize(90, 90)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))

    const scene = new THREE.Scene()
    const cubeCamera = new THREE.PerspectiveCamera(40, 1, 0.1, 100)
    cubeCamera.position.set(0, 0, 3.2)

    // Lighting for ViewCube
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.9)
    scene.add(ambientLight)
    const dirLight = new THREE.DirectionalLight(0xffffff, 1.2)
    dirLight.position.set(2, 4, 3)
    scene.add(dirLight)

    // Materials for 6 faces: Right (+X), Left (-X), Top (+Y), Bottom (-Y), Front (+Z), Back (-Z)
    const materials = [
      new THREE.MeshStandardMaterial({ map: createFaceTexture('RIGHT'), roughness: 0.4 }),
      new THREE.MeshStandardMaterial({ map: createFaceTexture('LEFT'), roughness: 0.4 }),
      new THREE.MeshStandardMaterial({ map: createFaceTexture('TOP'), roughness: 0.4 }),
      new THREE.MeshStandardMaterial({ map: createFaceTexture('BOTTOM'), roughness: 0.4 }),
      new THREE.MeshStandardMaterial({ map: createFaceTexture('FRONT'), roughness: 0.4 }),
      new THREE.MeshStandardMaterial({ map: createFaceTexture('BACK'), roughness: 0.4 }),
    ]

    const boxGeo = new THREE.BoxGeometry(1.2, 1.2, 1.2)
    const cubeMesh = new THREE.Mesh(boxGeo, materials)
    scene.add(cubeMesh)

    // Wireframe edges outline
    const wireGeo = new THREE.EdgesGeometry(boxGeo)
    const wireMat = new THREE.LineBasicMaterial({ color: '#38bdf8', linewidth: 2 })
    const wireMesh = new THREE.LineSegments(wireGeo, wireMat)
    scene.add(wireMesh)

    // Raycaster for clicking faces/edges
    const raycaster = new THREE.Raycaster()
    const mouse = new THREE.Vector2()

    const onPointerDown = (e: MouseEvent) => {
      if (e.button === 2) {
        // Right click opens context menu
        e.preventDefault()
        setShowContextMenu(true)
        return
      }
      isDraggingCube.current = true
      lastMousePos.current = { x: e.clientX, y: e.clientY }
    }

    const onPointerMove = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect()
      mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1
      mouse.y = -(((e.clientY - rect.top) / rect.height) * 2 - 1)

      raycaster.setFromCamera(mouse, cubeCamera)
      const hits = raycaster.intersectObject(cubeMesh)

      if (hits.length > 0 && hits[0].faceIndex != null) {
        const matIdx = Math.floor(hits[0].faceIndex / 2)
        const names = ['RIGHT', 'LEFT', 'TOP', 'BOTTOM', 'FRONT', 'BACK']
        setHoveredPart(names[matIdx] || null)
      } else {
        setHoveredPart(null)
      }

      if (isDraggingCube.current) {
        const dx = e.clientX - lastMousePos.current.x
        const dy = e.clientY - lastMousePos.current.y
        lastMousePos.current = { x: e.clientX, y: e.clientY }

        // Dragging the cube orbits the main camera
        const target = getTarget()
        const eye = mainCamera.position.clone().sub(target)
        const forward = eye.clone().negate().normalize()
        const right = new THREE.Vector3().crossVectors(forward, mainCamera.up).normalize()
        const up = new THREE.Vector3().crossVectors(right, forward).normalize()

        const rotAxis = new THREE.Vector3()
          .addScaledVector(right, dy)
          .addScaledVector(up, -dx)

        const len = rotAxis.length()
        if (len > 1e-4) {
          rotAxis.normalize()
          const q = new THREE.Quaternion().setFromAxisAngle(rotAxis, len * 0.01)
          eye.applyQuaternion(q)
          mainCamera.up.applyQuaternion(q)
          mainCamera.position.copy(target).add(eye)
          mainCamera.lookAt(target)
          mainCamera.updateMatrixWorld()
        }
      }
    }

    const onPointerUp = (e: MouseEvent) => {
      if (isDraggingCube.current && Math.hypot(e.clientX - lastMousePos.current.x, e.clientY - lastMousePos.current.y) < 3) {
        // Simple click on face
        const rect = canvas.getBoundingClientRect()
        mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1
        mouse.y = -(((e.clientY - rect.top) / rect.height) * 2 - 1)
        raycaster.setFromCamera(mouse, cubeCamera)
        const hits = raycaster.intersectObject(cubeMesh)
        if (hits.length > 0 && hits[0].faceIndex != null) {
          const matIdx = Math.floor(hits[0].faceIndex / 2)
          const names = ['RIGHT', 'LEFT', 'TOP', 'BOTTOM', 'FRONT', 'BACK']
          handleFaceClick(names[matIdx])
        }
      }
      isDraggingCube.current = false
    }

    const onContextMenu = (e: MouseEvent) => {
      e.preventDefault()
      setShowContextMenu(true)
    }

    canvas.addEventListener('mousedown', onPointerDown)
    window.addEventListener('mousemove', onPointerMove)
    window.addEventListener('mouseup', onPointerUp)
    canvas.addEventListener('contextmenu', onContextMenu)

    let animId: number
    const animate = () => {
      animId = requestAnimationFrame(animate)

      // Sync cube rotation with main camera
      // The cube orientation matches the inverse of the camera rotation so that faces point toward camera
      cubeCamera.quaternion.copy(mainCamera.quaternion)
      cubeCamera.position.set(0, 0, 3.2).applyQuaternion(mainCamera.quaternion)
      cubeCamera.up.copy(mainCamera.up)
      cubeCamera.lookAt(0, 0, 0)

      renderer.render(scene, cubeCamera)
    }
    animate()

    return () => {
      cancelAnimationFrame(animId)
      canvas.removeEventListener('mousedown', onPointerDown)
      window.removeEventListener('mousemove', onPointerMove)
      window.removeEventListener('mouseup', onPointerUp)
      canvas.removeEventListener('contextmenu', onContextMenu)
      renderer.dispose()
      boxGeo.dispose()
      wireGeo.dispose()
      materials.forEach((m) => m.dispose())
    }
  }, [mainCamera])

  return (
    <div
      ref={containerRef}
      className="absolute top-3 right-3 z-30 flex flex-col items-end select-none pointer-events-auto"
      data-testid="view-cube-container"
    >
      {/* Home & Menu header bar */}
      <div className="flex items-center gap-1 mb-1 bg-slate-900/80 backdrop-blur-sm border border-slate-700/60 rounded px-1.5 py-0.5">
        <button
          onClick={handleHomeClick}
          className="text-slate-300 hover:text-white p-0.5 rounded transition-colors"
          title="Home View (Isometric)"
          data-testid="view-cube-home-btn"
        >
          <Home className="w-3.5 h-3.5" />
        </button>
        <button
          onClick={() => setShowContextMenu((o) => !o)}
          className="text-slate-300 hover:text-white p-0.5 rounded transition-colors"
          title="Projection & Options"
          data-testid="view-cube-menu-btn"
        >
          <MoreVertical className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* 3D ViewCube Canvas */}
      <div className="relative w-[90px] h-[90px] rounded-lg overflow-hidden border border-slate-700/60 shadow-xl bg-slate-950/60 backdrop-blur-xs cursor-grab active:cursor-grabbing">
        <canvas ref={canvasRef} className="w-full h-full block" />
        {hoveredPart && (
          <div className="absolute bottom-1 inset-x-0 text-center pointer-events-none">
            <span className="text-[9px] font-mono font-bold bg-blue-950/90 text-cyan-300 px-1 py-0.5 rounded border border-cyan-500/40">
              {hoveredPart}
            </span>
          </div>
        )}
      </div>

      {/* Context Menu (Perspective / Orthographic) */}
      {showContextMenu && (
        <div
          className="absolute top-8 right-0 w-44 bg-slate-900 border border-slate-700 rounded-lg p-1.5 shadow-2xl z-40 text-xs text-slate-200 space-y-1"
          data-testid="view-cube-context-menu"
        >
          <div className="text-[10px] uppercase font-semibold text-slate-400 px-2 py-1">
            Camera Projection
          </div>
          <button
            onClick={() => handleProjectionChange('perspective')}
            className={`w-full text-left px-2 py-1.5 rounded flex items-center justify-between text-xs transition-colors ${
              navSettings.projection === 'perspective'
                ? 'bg-blue-600 text-white font-medium'
                : 'hover:bg-slate-800 text-slate-300'
            }`}
          >
            <span>Perspective</span>
            {navSettings.projection === 'perspective' && <span>✓</span>}
          </button>
          <button
            onClick={() => handleProjectionChange('orthographic')}
            className={`w-full text-left px-2 py-1.5 rounded flex items-center justify-between text-xs transition-colors ${
              navSettings.projection === 'orthographic'
                ? 'bg-blue-600 text-white font-medium'
                : 'hover:bg-slate-800 text-slate-300'
            }`}
          >
            <span>Orthographic</span>
            {navSettings.projection === 'orthographic' && <span>✓</span>}
          </button>
          <div className="border-t border-slate-800 pt-1 mt-1">
            <button
              onClick={() => {
                handleHomeClick()
                setShowContextMenu(false)
              }}
              className="w-full text-left px-2 py-1.5 rounded hover:bg-slate-800 text-slate-300 text-xs"
            >
              Reset to Home
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
export default ViewCube

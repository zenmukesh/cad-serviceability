import React, { useRef, useEffect, useMemo, useState } from 'react'
import { useThree, useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { useAssemblyStore } from '../../store/assemblyStore'

interface CADCameraControllerProps {
  fitViewTrigger: number
}

export const CADCameraController: React.FC<CADCameraControllerProps> = ({ fitViewTrigger }) => {
  const { camera, gl, scene } = useThree()
  const store = useAssemblyStore()
  const {
    components,
    selectedComponentId,
    selectComponent,
    navSettings,
    activeNavTool,
    setActiveNavTool,
    cameraTransition,
    fitSelectionTrigger,
    isSectionMode,
    closeSectionMode,
    isPickingSectionFace,
    setIsPickingSectionFace,
    setSectionPlane,
  } = store

  // Target / Orbit Pivot
  const targetRef = useRef<THREE.Vector3>(new THREE.Vector3(0, 0, 0))
  const [isOrbiting, setIsOrbiting] = useState(false)
  const isOrbitingRef = useRef(false)
  const [pivotScreenPos, setPivotScreenPos] = useState<{ x: number; y: number } | null>(null)

  // Drag tracking
  const pointerStartRef = useRef<{ x: number; y: number; button: number; shift: boolean } | null>(null)
  const isDraggingRef = useRef(false)
  const DRAG_THRESHOLD_PX = 4

  // Transition animation state
  const transitionRef = useRef<{
    startPos: THREE.Vector3
    endPos: THREE.Vector3
    startTarget: THREE.Vector3
    endTarget: THREE.Vector3
    startUp: THREE.Vector3
    endUp: THREE.Vector3
    startTime: number
    duration: number
    active: boolean
  } | null>(null)

  // Compute assembly center and selected component center
  const assemblyBounds = useMemo(() => {
    const box = new THREE.Box3()
    for (const c of components) {
      if (c.is_leaf && c.bounding_box) {
        // CAD coordinates rotated by [-Math.PI/2, 0, 0]: (x, z, -y)
        box.expandByPoint(new THREE.Vector3(c.bounding_box.xmin, c.bounding_box.zmin, -c.bounding_box.ymax))
        box.expandByPoint(new THREE.Vector3(c.bounding_box.xmax, c.bounding_box.zmax, -c.bounding_box.ymin))
      }
    }
    const center = new THREE.Vector3()
    const size = new THREE.Vector3()
    if (!box.isEmpty()) {
      box.getCenter(center)
      box.getSize(size)
    }
    const radius = Math.max(size.x, size.y, size.z) * 0.5 || 80
    return { box, center, radius }
  }, [components])

  const selectedCenter = useMemo(() => {
    if (selectedComponentId == null) return null
    const comp = components.find((c) => c.id === selectedComponentId)
    if (!comp || !comp.bounding_box) return null
    // In Three.js world coordinates
    const cx = (comp.bounding_box.xmin + comp.bounding_box.xmax) / 2
    const cy = (comp.bounding_box.zmin + comp.bounding_box.zmax) / 2
    const cz = -(comp.bounding_box.ymin + comp.bounding_box.ymax) / 2
    return new THREE.Vector3(cx, cy, cz)
  }, [selectedComponentId, components])

  // Current pivot: selected center if any, otherwise assembly center
  const currentPivot = useMemo(() => {
    if (selectedCenter) return selectedCenter.clone()
    return assemblyBounds.center.clone()
  }, [selectedCenter, assemblyBounds.center])

  // Expose camera debugging interface for Playwright tests
  useEffect(() => {
    ;(window as any).__CAD_VIEWER__ = {
      getCameraPosition: () => [camera.position.x, camera.position.y, camera.position.z],
      getCameraTarget: () => [targetRef.current.x, targetRef.current.y, targetRef.current.z],
      getCameraUp: () => [camera.up.x, camera.up.y, camera.up.z],
      getCameraQuaternion: () => [camera.quaternion.x, camera.quaternion.y, camera.quaternion.z, camera.quaternion.w],
      isOrthographic: () => Boolean((camera as THREE.OrthographicCamera).isOrthographicCamera),
      getTargetDistance: () => camera.position.distanceTo(targetRef.current),
    }
  }, [camera])

  // Update target when selection changes (if not actively dragging)
  useEffect(() => {
    if (!isDraggingRef.current) {
      targetRef.current.copy(currentPivot)
    }
  }, [currentPivot])

  // Handle camera transition requests (from ViewCube, Home, Look At, etc.)
  useEffect(() => {
    if (!cameraTransition) return
    const dur = cameraTransition.durationMs || 300
    transitionRef.current = {
      startPos: camera.position.clone(),
      endPos: new THREE.Vector3(...cameraTransition.position),
      startTarget: targetRef.current.clone(),
      endTarget: new THREE.Vector3(...cameraTransition.target),
      startUp: camera.up.clone(),
      endUp: new THREE.Vector3(...cameraTransition.up).normalize(),
      startTime: performance.now(),
      duration: dur,
      active: true,
    }
  }, [cameraTransition, camera])

  // Fit All logic
  const handleFitAll = () => {
    const { center, radius } = assemblyBounds
    const cam = camera as THREE.PerspectiveCamera
    const fov = (cam.fov || 45) * (Math.PI / 180)
    const dist = (radius / Math.sin(fov / 2)) * 1.4

    // Keep current direction if possible, otherwise isometric
    const dir = camera.position.clone().sub(targetRef.current).normalize()
    if (dir.lengthSq() < 0.1) dir.set(1, 1, 1).normalize()

    const newPos = center.clone().addScaledVector(dir, dist)
    targetRef.current.copy(center)
    transitionRef.current = {
      startPos: camera.position.clone(),
      endPos: newPos,
      startTarget: targetRef.current.clone(),
      endTarget: center.clone(),
      startUp: camera.up.clone(),
      endUp: new THREE.Vector3(0, 1, 0), // CAD Z-up corresponds to Three.js Y-up
      startTime: performance.now(),
      duration: 300,
      active: true,
    }
  }

  // Fit Selection logic
  const handleFitSelection = () => {
    if (!selectedCenter || selectedComponentId == null) {
      handleFitAll()
      return
    }
    const comp = components.find((c) => c.id === selectedComponentId)
    if (!comp || !comp.bounding_box) return
    const bb = comp.bounding_box
    const diag = Math.hypot(bb.size_x, bb.size_y, bb.size_z)
    const rad = Math.max(10, diag * 0.6)

    const cam = camera as THREE.PerspectiveCamera
    const fov = (cam.fov || 45) * (Math.PI / 180)
    const dist = (rad / Math.sin(fov / 2)) * 1.5

    const dir = camera.position.clone().sub(targetRef.current).normalize()
    if (dir.lengthSq() < 0.1) dir.set(1, 1, 1).normalize()

    const newPos = selectedCenter.clone().addScaledVector(dir, dist)
    targetRef.current.copy(selectedCenter)
    transitionRef.current = {
      startPos: camera.position.clone(),
      endPos: newPos,
      startTarget: targetRef.current.clone(),
      endTarget: selectedCenter.clone(),
      startUp: camera.up.clone(),
      endUp: new THREE.Vector3(0, 1, 0),
      startTime: performance.now(),
      duration: 300,
      active: true,
    }
  }

  useEffect(() => {
    if (fitViewTrigger > 0) handleFitAll()
  }, [fitViewTrigger])

  useEffect(() => {
    if (fitSelectionTrigger > 0) handleFitSelection()
  }, [fitSelectionTrigger])

  // Keyboard navigation shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't trigger if user is typing in an input field
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes((e.target as HTMLElement)?.tagName)) {
        return
      }

      if (e.key === 'Home') {
        e.preventDefault()
        // Standard Isometric Home view
        const { center, radius } = assemblyBounds
        const dist = radius * 2.5
        const homeDir = new THREE.Vector3(1, 1, 1).normalize()
        const newPos = center.clone().addScaledVector(homeDir, dist)
        transitionRef.current = {
          startPos: camera.position.clone(),
          endPos: newPos,
          startTarget: targetRef.current.clone(),
          endTarget: center.clone(),
          startUp: camera.up.clone(),
          endUp: new THREE.Vector3(0, 1, 0),
          startTime: performance.now(),
          duration: 350,
          active: true,
        }
      } else if (e.key === 'f' || e.key === 'F') {
        e.preventDefault()
        if (selectedComponentId != null) {
          handleFitSelection()
        } else {
          handleFitAll()
        }
      } else if (e.key === 'Escape') {
        setActiveNavTool('select')
        if (isSectionMode) closeSectionMode()
        if (isPickingSectionFace) setIsPickingSectionFace(false)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [assemblyBounds, selectedComponentId, selectedCenter, camera, isSectionMode, isPickingSectionFace, closeSectionMode, setIsPickingSectionFace, setActiveNavTool])

  // Free tumble quaternion orbit math
  const applyOrbit = (deltaX: number, deltaY: number) => {
    const speed = (navSettings.orbitSpeed || 1.0) * 0.0055
    const pivot = targetRef.current
    const eye = camera.position.clone().sub(pivot)

    if (navSettings.constrainedZUp) {
      // Turntable rotation: azimuth around world Y (CAD Z-up), elevation around camera right
      const azimuthAngle = -deltaX * speed
      const elevationAngle = -deltaY * speed

      const qYaw = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), azimuthAngle)
      eye.applyQuaternion(qYaw)
      camera.up.applyQuaternion(qYaw)

      const forward = eye.clone().negate().normalize()
      const right = new THREE.Vector3().crossVectors(forward, camera.up).normalize()
      const qPitch = new THREE.Quaternion().setFromAxisAngle(right, elevationAngle)
      eye.applyQuaternion(qPitch)
      camera.up.applyQuaternion(qPitch)
    } else {
      // Quaternion-based Free Tumble (Fusion 360 style):
      // No polar angle clamp, no axis lock!
      // Rotating simultaneously around both screen axes
      const forward = eye.clone().negate().normalize()
      const right = new THREE.Vector3().crossVectors(forward, camera.up).normalize()
      const up = new THREE.Vector3().crossVectors(right, forward).normalize()

      // The instantaneous rotation axis in world coordinates
      // deltaX moves along screen X (rotates around camera up)
      // deltaY moves along screen Y (rotates around camera right)
      const rotAxis = new THREE.Vector3()
        .addScaledVector(right, deltaY)
        .addScaledVector(up, -deltaX)

      const length = rotAxis.length()
      if (length > 1e-6) {
        rotAxis.normalize()
        const angle = length * speed
        const q = new THREE.Quaternion().setFromAxisAngle(rotAxis, angle)
        eye.applyQuaternion(q)
        camera.up.applyQuaternion(q)
      }
    }

    camera.position.copy(pivot).add(eye)
    camera.lookAt(pivot)
    camera.updateMatrixWorld()
  }

  // Pan math
  const applyPan = (deltaX: number, deltaY: number) => {
    const eye = camera.position.clone().sub(targetRef.current)
    const dist = eye.length()
    const factor = dist * 0.0012

    const forward = eye.clone().negate().normalize()
    const right = new THREE.Vector3().crossVectors(forward, camera.up).normalize()
    const up = new THREE.Vector3().crossVectors(right, forward).normalize()

    const panOffset = new THREE.Vector3()
      .addScaledVector(right, -deltaX * factor)
      .addScaledVector(up, deltaY * factor)

    targetRef.current.add(panOffset)
    camera.position.add(panOffset)
    camera.updateMatrixWorld()
  }

  // Cursor-centered zoom math
  const applyZoom = (deltaY: number, clientX: number, clientY: number) => {
    const factor = Math.exp(deltaY * 0.0015)
    const rect = gl.domElement.getBoundingClientRect()
    const ndcX = ((clientX - rect.left) / rect.width) * 2 - 1
    const ndcY = -(((clientY - rect.top) / rect.height) * 2 - 1)

    // Raycast cursor into scene to find zoom focal point
    const raycaster = new THREE.Raycaster()
    raycaster.setFromCamera(new THREE.Vector2(ndcX, ndcY), camera)

    // Intersect plane parallel to camera at target
    const planeNormal = camera.position.clone().sub(targetRef.current).normalize()
    const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(planeNormal, targetRef.current)
    const focalPoint = new THREE.Vector3()
    raycaster.ray.intersectPlane(plane, focalPoint)

    if (!focalPoint || isNaN(focalPoint.x)) {
      focalPoint.copy(targetRef.current)
    }

    if ((camera as THREE.OrthographicCamera).isOrthographicCamera) {
      const ortho = camera as THREE.OrthographicCamera
      ortho.zoom = Math.max(0.01, Math.min(100.0, ortho.zoom / factor))
      ortho.updateProjectionMatrix()
    } else {
      const eye = camera.position.clone().sub(focalPoint)
      eye.multiplyScalar(factor)
      camera.position.copy(focalPoint).add(eye)
      camera.lookAt(targetRef.current)
      camera.updateMatrixWorld()
    }
  }

  // Pointer event listeners on canvas element
  useEffect(() => {
    const canvas = gl.domElement

    const onPointerDown = (e: PointerEvent) => {
      pointerStartRef.current = {
        x: e.clientX,
        y: e.clientY,
        button: e.button,
        shift: e.shiftKey,
      }
      isDraggingRef.current = false
    }

    const onPointerMove = (e: PointerEvent) => {
      if (!pointerStartRef.current) return
      const dx = e.clientX - pointerStartRef.current.x
      const dy = e.clientY - pointerStartRef.current.y
      const dist = Math.hypot(dx, dy)

      if (!isDraggingRef.current && dist > DRAG_THRESHOLD_PX) {
        isDraggingRef.current = true
        // Set pivot to selection center if any, otherwise assembly center
        targetRef.current.copy(currentPivot)
      }

      if (isDraggingRef.current) {
        // Stop any running camera transition animation
        if (transitionRef.current) transitionRef.current.active = false

        const movementX = e.movementX || dx
        const movementY = e.movementY || dy

        const { button, shift } = pointerStartRef.current
        const preset = navSettings.preset // 'fusion' or 'standard'

        // Fusion 360 Mapping:
        // - Shift + Middle drag (or activeNavTool === 'orbit'): Orbit
        // - Middle drag (or activeNavTool === 'pan'): Pan
        // Standard Mapping:
        // - Left drag: Orbit
        // - Middle drag: Pan
        let shouldOrbit = false
        let shouldPan = false
        let shouldZoom = false

        if (activeNavTool === 'orbit') {
          shouldOrbit = button === 0 || (button === 1 && shift)
        } else if (activeNavTool === 'pan') {
          shouldPan = button === 0 || button === 1
        } else if (activeNavTool === 'zoom') {
          shouldZoom = button === 0
        } else if (preset === 'fusion') {
          if (button === 1 && shift) shouldOrbit = true
          else if (button === 1 && !shift) shouldPan = true
          else if (button === 2) shouldPan = true // Right drag pan fallback
        } else if (preset === 'standard') {
          if (button === 0) shouldOrbit = true
          else if (button === 1 || button === 2) shouldPan = true
        }

        if (shouldOrbit) {
          setIsOrbiting(true)
          isOrbitingRef.current = true
          applyOrbit(movementX, movementY)
        } else if (shouldPan) {
          applyPan(movementX, movementY)
        } else if (shouldZoom) {
          applyZoom(movementY * 5, e.clientX, e.clientY)
        }
      }
    }

    const onPointerUp = (e: PointerEvent) => {
      setIsOrbiting(false)
      isOrbitingRef.current = false
      setPivotScreenPos(null)

      if (pointerStartRef.current && !isDraggingRef.current && pointerStartRef.current.button === 0) {
        // Left click without drag: Part selection or Look At tool
        const rect = canvas.getBoundingClientRect()
        const mouse = new THREE.Vector2(
          ((e.clientX - rect.left) / rect.width) * 2 - 1,
          -(((e.clientY - rect.top) / rect.height) * 2 - 1)
        )

        const raycaster = new THREE.Raycaster()
        raycaster.setFromCamera(mouse, camera)

        const intersects = raycaster.intersectObjects(scene.children, true)
        const hit = intersects.find((i) => i.object.userData?.componentId != null)

        if (isPickingSectionFace && hit && hit.face) {
          // Align section plane to clicked planar face
          const worldNormal = hit.face.normal.clone().transformDirection(hit.object.matrixWorld).normalize()
          // CAD mapping under rotation [-Math.PI/2, 0, 0]: Three.js (X, Y, Z) -> CAD (X, -Z, Y)
          const cnx = parseFloat(worldNormal.x.toFixed(4))
          const cny = parseFloat((-worldNormal.z).toFixed(4))
          const cnz = parseFloat(worldNormal.y.toFixed(4))
          const cpx = hit.point.x
          const cpy = -hit.point.z
          const cpz = hit.point.y
          const offset = parseFloat((cnx * cpx + cny * cpy + cnz * cpz).toFixed(1))

          setSectionPlane(0, {
            enabled: true,
            normal: [cnx, cny, cnz],
            offset,
            label: `Picked Face [${cnx.toFixed(2)}, ${cny.toFixed(2)}, ${cnz.toFixed(2)}]`,
          })
          setIsPickingSectionFace(false)
        } else if (activeNavTool === 'lookAt' && hit && hit.face) {
          // Look At: Align camera perpendicular to clicked face
          const worldNormal = hit.face.normal.clone().transformDirection(hit.object.matrixWorld).normalize()
          const hitPoint = hit.point.clone()
          const dist = camera.position.distanceTo(hitPoint)

          const newPos = hitPoint.clone().addScaledVector(worldNormal, dist)
          transitionRef.current = {
            startPos: camera.position.clone(),
            endPos: newPos,
            startTarget: targetRef.current.clone(),
            endTarget: hitPoint,
            startUp: camera.up.clone(),
            endUp: new THREE.Vector3(0, 1, 0),
            startTime: performance.now(),
            duration: 350,
            active: true,
          }
          setActiveNavTool('select')
        } else if (hit) {
          selectComponent(hit.object.userData.componentId)
        } else if (activeNavTool === 'select') {
          selectComponent(null)
        }
      }

      pointerStartRef.current = null
      isDraggingRef.current = false
    }

    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      if (transitionRef.current) transitionRef.current.active = false
      applyZoom(e.deltaY, e.clientX, e.clientY)
    }

    const onContextMenu = (e: MouseEvent) => {
      e.preventDefault() // Prevent browser context menu over canvas
    }

    canvas.addEventListener('pointerdown', onPointerDown)
    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', onPointerUp)
    canvas.addEventListener('wheel', onWheel, { passive: false })
    canvas.addEventListener('contextmenu', onContextMenu)

    return () => {
      canvas.removeEventListener('pointerdown', onPointerDown)
      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('pointerup', onPointerUp)
      canvas.removeEventListener('wheel', onWheel)
      canvas.removeEventListener('contextmenu', onContextMenu)
    }
  }, [gl, camera, scene, navSettings, activeNavTool, currentPivot, selectComponent, setActiveNavTool])

  // Camera transition animation loop (slerp/easing over 300ms)
  useFrame(() => {
    if (transitionRef.current && transitionRef.current.active) {
      const { startPos, endPos, startTarget, endTarget, startUp, endUp, startTime, duration } =
        transitionRef.current

      const now = performance.now()
      const elapsed = now - startTime
      const progress = Math.min(1.0, elapsed / duration)

      // Smooth easeInOutCubic
      const ease =
        progress < 0.5
          ? 4 * progress * progress * progress
          : 1 - Math.pow(-2 * progress + 2, 3) / 2

      camera.position.lerpVectors(startPos, endPos, ease)
      targetRef.current.lerpVectors(startTarget, endTarget, ease)

      // Slerp camera up vector
      const qStart = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), startUp)
      const qEnd = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), endUp)
      const qCur = qStart.clone().slerp(qEnd, ease)
      camera.up.set(0, 1, 0).applyQuaternion(qCur).normalize()

      camera.lookAt(targetRef.current)
      camera.updateMatrixWorld()

      if (progress >= 1.0) {
        transitionRef.current.active = false
      }
    }

    // Update screen position of orbit pivot for visual feedback
    if (isOrbitingRef.current) {
      const p = targetRef.current.clone().project(camera)
      const rect = gl.domElement.getBoundingClientRect()
      const x = ((p.x + 1) / 2) * rect.width
      const y = ((-p.y + 1) / 2) * rect.height
      setPivotScreenPos({ x, y })
    }
  })

  return (
    <>
      {/* Visual Orbit Pivot Marker when orbiting */}
      {isOrbiting && pivotScreenPos && (
        <group>
          <mesh position={targetRef.current}>
            <sphereGeometry args={[1.5, 16, 16]} />
            <meshBasicMaterial color="#38bdf8" transparent opacity={0.6} />
          </mesh>
        </group>
      )}
    </>
  )
}
export default CADCameraController

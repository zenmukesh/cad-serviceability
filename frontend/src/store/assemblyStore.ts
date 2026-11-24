import { create } from 'zustand'
import * as THREE from 'three'
import toast from 'react-hot-toast'
import type { Assembly, Component } from '../types/assembly'
import type {
  AssemblyServiceabilityReport,
  ClearanceMeasurement,
  ComponentObstructionReport,
  DisassemblyGraph,
  AssemblySectionResponse,
  SectionPlaneConfig,
} from '../types/serviceability'

export type RightPanelTab =
  | 'properties'
  | 'serviceability'
  | 'obstructions'
  | 'clearances'
  | 'disassembly'
  | 'revision'

export interface ClearanceLineVisual {
  p1: [number, number, number]
  p2: [number, number, number]
  dist: number
  label: string
}

export interface AccessVectorVisual {
  origin: [number, number, number]
  dir: [number, number, number]
  label: string
}

// ─── Fusion 360 Navigation Types (Part 1) ───────────────────────────────────
export type NavigationPreset = 'fusion' | 'standard'
export type NavigationTool = 'select' | 'orbit' | 'pan' | 'zoom' | 'lookAt'
export type CameraProjection = 'perspective' | 'orthographic'

export interface NavigationSettings {
  preset: NavigationPreset
  orbitSpeed: number
  constrainedZUp: boolean
  projection: CameraProjection
}

export interface CameraTransitionRequest {
  id: number
  position: [number, number, number]
  target: [number, number, number]
  up: [number, number, number]
  durationMs?: number
  isOrthographic?: boolean
}

const NAV_SETTINGS_KEY = 'cad_serviceability_nav_settings'

function loadSavedNavSettings(): NavigationSettings {
  try {
    const raw = localStorage.getItem(NAV_SETTINGS_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      return {
        preset: parsed.preset === 'standard' ? 'standard' : 'fusion',
        orbitSpeed: typeof parsed.orbitSpeed === 'number' ? parsed.orbitSpeed : 1.0,
        constrainedZUp: Boolean(parsed.constrainedZUp),
        projection: parsed.projection === 'orthographic' ? 'orthographic' : 'perspective',
      }
    }
  } catch (err) {
    console.warn('Failed to load navigation settings from localStorage:', err)
  }
  return {
    preset: 'fusion',
    orbitSpeed: 1.0,
    constrainedZUp: false,
    projection: 'perspective',
  }
}

function saveNavSettings(settings: NavigationSettings) {
  try {
    localStorage.setItem(NAV_SETTINGS_KEY, JSON.stringify(settings))
  } catch (err) {
    console.warn('Failed to save navigation settings to localStorage:', err)
  }
}

export interface AssemblyBoundingBox {
  min: [number, number, number]
  max: [number, number, number]
  center: [number, number, number]
  size: [number, number, number]
}

interface AssemblyStore {
  assemblies: Assembly[]
  currentAssembly: Assembly | null
  components: Component[]
  assemblyBoundingBox: AssemblyBoundingBox | null
  selectedComponentId: number | null
  hiddenComponentIds: Set<number>
  isolatedComponentId: number | null
  isLoading: boolean
  error: string | null

  // ─── Milestone 2 Analysis State ─────────────────────────────────────────────
  serviceabilityReport: AssemblyServiceabilityReport | null
  selectedObstructionReport: ComponentObstructionReport | null
  clearances: ClearanceMeasurement[]
  dependencyGraph: DisassemblyGraph | null
  isAnalyzing: boolean
  rightPanelTab: RightPanelTab

  // ─── Phase 1: Inspection Tools State ─────────────────────────────────────────
  isXRayMode: boolean
  transparentComponentIds: Set<number>
  explodeFactor: number // 0.0 to 1.0
  sectionPlaneAxis: 'off' | '+X' | '-X' | '+Y' | '-Y' | '+Z' | '-Z'
  sectionPlaneOffset: number // in mm

  // ─── Phase D: Multi-Axis Sectioning (D1 - D3) ──────────────────────────────
  sectionPlanes: SectionPlaneConfig[]
  sectionCombinedMode: 'union' | 'intersection'
  showSectionCaps: boolean
  activeSectionResult: AssemblySectionResponse | null
  isComputingSection: boolean

  // ─── Part 2: Engineering-Graphics Sectioning State ──────────────────────────
  isSectionMode: boolean
  sectionRefPlane: 'Top' | 'Front' | 'Side'
  sectionTiltDeg: number
  sectionTiltToward: 'Front' | 'Side' | 'Top'
  sectionOffsetMm: number
  sectionFlipped: boolean
  sectionHatchEnabled: boolean
  isTrueShapeActive: boolean
  isPickingSectionFace: boolean
  previousCameraBeforeTrueShape: {
    position: [number, number, number]
    target: [number, number, number]
    up: [number, number, number]
    projection: CameraProjection
  } | null

  // ─── Phase 6: 3D Visual Findings Highlighting ──────────────────────────────
  obstructingComponentIds: Set<number>
  activeClearanceLine: ClearanceLineVisual | null
  activeAccessVector: AccessVectorVisual | null

  // ─── Part 1: Fusion 360 Navigation State ───────────────────────────────────
  navSettings: NavigationSettings
  activeNavTool: NavigationTool
  cameraTransition: CameraTransitionRequest | null
  fitSelectionTrigger: number
  lookAtPlaneNormal: [number, number, number] | null

  // ─── Actions ────────────────────────────────────────────────────────────────
  setAssemblies: (a: Assembly[]) => void
  setCurrentAssembly: (a: Assembly | null) => void
  setComponents: (c: Component[]) => void
  selectComponent: (id: number | null) => void
  toggleHidden: (id: number) => void
  clearHidden: () => void
  setIsolated: (id: number | null) => void
  setLoading: (v: boolean) => void
  setError: (e: string | null) => void

  // Part 1: Navigation Actions
  setNavSettings: (settings: Partial<NavigationSettings>) => void
  setActiveNavTool: (tool: NavigationTool) => void
  triggerCameraTransition: (req: Omit<CameraTransitionRequest, 'id'>) => void
  triggerFitSelection: () => void
  setLookAtPlaneNormal: (normal: [number, number, number] | null) => void

  // Milestone 2 Actions
  setServiceabilityReport: (r: AssemblyServiceabilityReport | null) => void
  setSelectedObstructionReport: (r: ComponentObstructionReport | null) => void
  setClearances: (c: ClearanceMeasurement[]) => void
  setDependencyGraph: (g: DisassemblyGraph | null) => void
  setIsAnalyzing: (v: boolean) => void
  setRightPanelTab: (t: RightPanelTab) => void

  // Inspection Tools Actions
  toggleXRayMode: () => void
  toggleTransparentComponent: (id: number) => void
  setExplodeFactor: (f: number) => void
  setSectionPlaneAxis: (axis: 'off' | '+X' | '-X' | '+Y' | '-Y' | '+Z' | '-Z') => void
  setSectionPlaneOffset: (offset: number) => void

  // Phase D Actions
  setSectionPlane: (index: number, config: Partial<SectionPlaneConfig>) => void
  setSectionCombinedMode: (mode: 'union' | 'intersection') => void
  setShowSectionCaps: (show: boolean) => void
  setActiveSectionResult: (res: AssemblySectionResponse | null) => void
  setIsComputingSection: (v: boolean) => void
  applySectionPreset: (preset: 'XY' | 'XZ' | 'YZ' | '45_XZ' | '45_YZ' | '45_XY' | 'compound_45' | 'removal_vector' | 'clear') => void
  setSectionThroughFinding: (point: [number, number, number], normal: [number, number, number], label?: string) => void

  // Part 2: Engineering-Graphics Sectioning Actions
  setIsSectionMode: (active: boolean) => void
  setSectionPlaneFromSimple: (ref: 'Top' | 'Front' | 'Side') => void
  setSectionRefPlane: (ref: 'Top' | 'Front' | 'Side') => void
  setSectionTiltDeg: (deg: number) => void
  setSectionTiltToward: (toward: 'Front' | 'Side' | 'Top') => void
  setSectionOffsetMm: (mm: number) => void
  toggleSectionFlip: () => void
  toggleSectionHatch: () => void
  toggleTrueShape: () => void
  setIsPickingSectionFace: (picking: boolean) => void
  resetSectionPlane: () => void
  closeSectionMode: () => void

  // 3D Visual Findings Actions
  setObstructingComponentIds: (ids: Set<number>) => void
  setActiveClearanceLine: (line: ClearanceLineVisual | null) => void
  setActiveAccessVector: (vec: AccessVectorVisual | null) => void
  clearVisualFindings: () => void
}

export function computeAssemblyBounds(components: Component[]): AssemblyBoundingBox | null {
  let minX = Infinity, minY = Infinity, minZ = Infinity
  let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity
  for (const c of components) {
    if (c.is_leaf && c.bounding_box) {
      minX = Math.min(minX, c.bounding_box.xmin)
      minY = Math.min(minY, c.bounding_box.ymin)
      minZ = Math.min(minZ, c.bounding_box.zmin)
      maxX = Math.max(maxX, c.bounding_box.xmax)
      maxY = Math.max(maxY, c.bounding_box.ymax)
      maxZ = Math.max(maxZ, c.bounding_box.zmax)
    }
  }
  if (!isFinite(minX) || minX === Infinity) return null
  return {
    min: [minX, minY, minZ],
    max: [maxX, maxY, maxZ],
    center: [(minX + maxX) / 2, (minY + maxY) / 2, (minZ + maxZ) / 2],
    size: [maxX - minX, maxY - minY, maxZ - minZ],
  }
}

export function validateSectionPlaneClipping(
  normal: [number, number, number],
  point: [number, number, number],
  offsetMm: number,
  flipped: boolean,
  bbox: AssemblyBoundingBox | null
): { valid: boolean; reason?: string; safeOffset: number } {
  const [nx, ny, nz] = normal
  if (!isFinite(nx) || !isFinite(ny) || !isFinite(nz) || !isFinite(offsetMm)) {
    return { valid: false, reason: 'Plane contains non-finite values (NaN / Infinity)', safeOffset: 0 }
  }
  const len = Math.hypot(nx, ny, nz)
  if (len < 1e-5) {
    return { valid: false, reason: 'Plane normal is zero-length', safeOffset: 0 }
  }
  if (!bbox) {
    return { valid: true, safeOffset: offsetMm }
  }

  const unx = (flipped ? -nx : nx) / len
  const uny = (flipped ? -ny : ny) / len
  const unz = (flipped ? -nz : nz) / len

  // Plane point with offset along normal
  const p0 = [
    point[0] + unx * offsetMm,
    point[1] + uny * offsetMm,
    point[2] + unz * offsetMm,
  ]

  let allClipped = true
  const xs = [bbox.min[0], bbox.max[0]]
  const ys = [bbox.min[1], bbox.max[1]]
  const zs = [bbox.min[2], bbox.max[2]]

  for (const x of xs) {
    for (const y of ys) {
      for (const z of zs) {
        // Signed distance to plane: n . (P - p0)
        const dist = unx * (x - p0[0]) + uny * (y - p0[1]) + unz * (z - p0[2])
        if (dist >= -1e-3) {
          allClipped = false
        }
      }
    }
  }

  if (allClipped) {
    return {
      valid: false,
      reason: 'Cutting plane would clip 100% of the assembly. Reverting to safe center.',
      safeOffset: 0,
    }
  }

  return { valid: true, safeOffset: offsetMm }
}

export function computeSectionPlaneDefinition(
  refPlane: 'Top' | 'Front' | 'Side',
  tiltDeg: number,
  tiltToward: 'Front' | 'Side' | 'Top' = 'Front',
  _offsetMm: number = 0,
  flipped: boolean = false
): { normal: [number, number, number]; badge: string } {
  const rad = (tiltDeg * Math.PI) / 180
  let nx = 0
  let ny = 0
  let nz = 1
  let perp = 'Front'

  if (refPlane === 'Top') {
    if (tiltToward === 'Side') {
      nx = Math.sin(rad)
      ny = 0
      nz = Math.cos(rad)
      perp = 'Front'
    } else {
      nx = 0
      ny = -Math.sin(rad)
      nz = Math.cos(rad)
      perp = 'Side'
    }
  } else if (refPlane === 'Front') {
    if (tiltToward === 'Side') {
      nx = Math.sin(rad)
      ny = -Math.cos(rad)
      nz = 0
      perp = 'Top'
    } else {
      nx = 0
      ny = -Math.cos(rad)
      nz = Math.sin(rad)
      perp = 'Side'
    }
  } else {
    // Side
    if (tiltToward === 'Front') {
      nx = Math.cos(rad)
      ny = -Math.sin(rad)
      nz = 0
      perp = 'Top'
    } else {
      nx = Math.cos(rad)
      ny = 0
      nz = Math.sin(rad)
      perp = 'Front'
    }
  }

  if (flipped) {
    nx = -nx
    ny = -ny
    nz = -nz
  }

  let badge = ''
  if (Math.abs(tiltDeg) < 0.5) {
    if (refPlane === 'Top') badge = 'Top view section (horizontal)'
    else if (refPlane === 'Front') badge = 'Front view section (vertical)'
    else badge = 'Side view section (profile)'
  } else {
    badge = `Inclined ${Math.round(tiltDeg)} deg to ${refPlane}, perpendicular to ${perp}`
  }

  return { normal: [nx, ny, nz], badge }
}

export const useAssemblyStore = create<AssemblyStore>((set, get) => ({
  assemblies: [],
  currentAssembly: null,
  components: [],
  assemblyBoundingBox: null,
  selectedComponentId: null,
  hiddenComponentIds: new Set<number>(),
  isolatedComponentId: null,
  isLoading: false,
  error: null,

  // Milestone 2
  serviceabilityReport: null,
  selectedObstructionReport: null,
  clearances: [],
  dependencyGraph: null,
  isAnalyzing: false,
  rightPanelTab: 'serviceability',

  // Inspection Tools
  isXRayMode: false,
  transparentComponentIds: new Set<number>(),
  explodeFactor: 0.0,
  sectionPlaneAxis: 'off',
  sectionPlaneOffset: 0.0,

  // ─── Phase D: Multi-Axis Sectioning (D1 - D3) ──────────────────────────────
  sectionPlanes: [
    { id: 1, enabled: false, point: [0, 0, 0], normal: [0, 0, 1], offset: 0, flipped: false, label: 'Plane 1 (Z)' },
    { id: 2, enabled: false, point: [0, 0, 0], normal: [0, 1, 0], offset: 0, flipped: false, label: 'Plane 2 (Y)' },
    { id: 3, enabled: false, point: [0, 0, 0], normal: [1, 0, 0], offset: 0, flipped: false, label: 'Plane 3 (X)' },
  ],
  sectionCombinedMode: 'union',
  showSectionCaps: true,
  activeSectionResult: null,
  isComputingSection: false,

  // Visual Findings
  obstructingComponentIds: new Set<number>(),
  activeClearanceLine: null,
  activeAccessVector: null,

  // Part 2: Engineering-Graphics Sectioning State
  isSectionMode: false,
  sectionRefPlane: 'Top',
  sectionTiltDeg: 0,
  sectionTiltToward: 'Front',
  sectionOffsetMm: 0,
  sectionFlipped: false,
  sectionHatchEnabled: true,
  isTrueShapeActive: false,
  isPickingSectionFace: false,
  previousCameraBeforeTrueShape: null,

  // Part 1: Navigation State
  navSettings: loadSavedNavSettings(),
  activeNavTool: 'select',
  cameraTransition: null,
  fitSelectionTrigger: 0,
  lookAtPlaneNormal: null,

  setAssemblies: (a) => set({ assemblies: a }),
  setCurrentAssembly: (a) => set({ currentAssembly: a }),
  setComponents: (c) => {
    const bbox = computeAssemblyBounds(c)
    const planes = [...get().sectionPlanes]
    if (bbox) {
      planes.forEach((p) => {
        p.point = [...bbox.center] as [number, number, number]
      })
    }
    set({ components: c, assemblyBoundingBox: bbox, sectionPlanes: planes })
  },
  selectComponent: (id) => {
    set({
      selectedComponentId: id,
      // Clear visual findings on selection change
      obstructingComponentIds: new Set<number>(),
      activeClearanceLine: null,
      activeAccessVector: null,
    })
  },
  toggleHidden: (id) => {
    const next = new Set(get().hiddenComponentIds)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    set({ hiddenComponentIds: next })
  },
  clearHidden: () => set({ hiddenComponentIds: new Set<number>() }),
  setIsolated: (id) => set({ isolatedComponentId: id }),
  setLoading: (v) => set({ isLoading: v }),
  setError: (e) => set({ error: e }),

  // Milestone 2 setters
  setServiceabilityReport: (r) => set({ serviceabilityReport: r }),
  setSelectedObstructionReport: (r) => set({ selectedObstructionReport: r }),
  setClearances: (c) => set({ clearances: c }),
  setDependencyGraph: (g) => set({ dependencyGraph: g }),
  setIsAnalyzing: (v) => set({ isAnalyzing: v }),
  setRightPanelTab: (t) => set({ rightPanelTab: t }),

  // Inspection tools setters
  toggleXRayMode: () => set((s) => ({ isXRayMode: !s.isXRayMode })),
  toggleTransparentComponent: (id) => {
    const next = new Set(get().transparentComponentIds)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    set({ transparentComponentIds: next })
  },
  setExplodeFactor: (f) => set({ explodeFactor: Math.max(0, Math.min(1, f)) }),
  setSectionPlaneAxis: (axis) => set({ sectionPlaneAxis: axis }),
  setSectionPlaneOffset: (offset) => set({ sectionPlaneOffset: offset }),

  // Phase D setters
  setSectionPlane: (index, config) => {
    const planes = [...get().sectionPlanes]
    if (index >= 0 && index < planes.length) {
      planes[index] = { ...planes[index], ...config }
      set({ sectionPlanes: planes })
    }
  },
  setSectionCombinedMode: (mode) => set({ sectionCombinedMode: mode }),
  setShowSectionCaps: (show) => set({ showSectionCaps: show }),
  setActiveSectionResult: (res) => set({ activeSectionResult: res }),
  setIsComputingSection: (v) => set({ isComputingSection: v }),
  applySectionPreset: (preset) => {
    const planes = [...get().sectionPlanes]
    if (preset === 'clear') {
      planes.forEach((p) => (p.enabled = false))
      set({ sectionPlanes: planes, activeSectionResult: null, sectionPlaneAxis: 'off' })
      return
    }

    // Configure Plane 1 based on preset
    planes[0].enabled = true
    if (preset === 'XY') {
      planes[0].normal = [0, 0, 1]
      planes[0].offset = 0
      planes[0].label = 'XY Preset (Z-Cut)'
      set({ sectionPlaneAxis: '+Z', sectionPlaneOffset: 0 })
    } else if (preset === 'XZ') {
      planes[0].normal = [0, 1, 0]
      planes[0].offset = 0
      planes[0].label = 'XZ Preset (Y-Cut)'
      set({ sectionPlaneAxis: '+Y', sectionPlaneOffset: 0 })
    } else if (preset === 'YZ') {
      planes[0].normal = [1, 0, 0]
      planes[0].offset = 0
      planes[0].label = 'YZ Preset (X-Cut)'
      set({ sectionPlaneAxis: '+X', sectionPlaneOffset: 0 })
    } else if (preset === '45_XZ') {
      const inv = 1 / Math.sqrt(2)
      planes[0].normal = [inv, 0, inv]
      planes[0].offset = 0
      planes[0].label = '45° XZ Oblique'
    } else if (preset === '45_YZ') {
      const inv = 1 / Math.sqrt(2)
      planes[0].normal = [0, inv, inv]
      planes[0].offset = 0
      planes[0].label = '45° YZ Oblique'
    } else if (preset === '45_XY') {
      const inv = 1 / Math.sqrt(2)
      planes[0].normal = [inv, inv, 0]
      planes[0].offset = 0
      planes[0].label = '45° XY Oblique'
    } else if (preset === 'compound_45') {
      const inv = 1 / Math.sqrt(3)
      planes[0].normal = [inv, inv, inv]
      planes[0].offset = 0
      planes[0].label = 'Compound 45°/45° Oblique'
    } else if (preset === 'removal_vector') {
      const activeVec = get().activeAccessVector
      if (activeVec) {
        planes[0].normal = activeVec.dir
        planes[0].point = activeVec.origin
        planes[0].offset = 0
        planes[0].label = `Removal Normal [${activeVec.dir.map((v: number) => v.toFixed(2)).join(', ')}]`
      }
    }
    set({ sectionPlanes: planes })
  },
  setSectionThroughFinding: (point, normal, label) => {
    const planes = [...get().sectionPlanes]
    planes[0].enabled = true
    planes[0].point = point
    planes[0].normal = normal
    planes[0].offset = 0
    planes[0].label = label || 'Finding Section Plane'
    set({
      sectionPlanes: planes,
      rightPanelTab: 'serviceability',
    })
  },

  // Part 2: Engineering-Graphics Sectioning Action Implementations
  setIsSectionMode: (active: boolean) => {
    if (!active) {
      get().closeSectionMode()
      return
    }
    const { sectionRefPlane, sectionTiltDeg, sectionTiltToward, sectionOffsetMm, sectionFlipped, assemblyBoundingBox } = get()
    const { normal, badge } = computeSectionPlaneDefinition(
      sectionRefPlane,
      sectionTiltDeg,
      sectionTiltToward,
      sectionOffsetMm,
      sectionFlipped
    )
    const center: [number, number, number] = assemblyBoundingBox ? [...assemblyBoundingBox.center] : [0, 0, 0]
    const check = validateSectionPlaneClipping(normal, center, sectionOffsetMm, sectionFlipped, assemblyBoundingBox)
    const validOffset = check.valid ? sectionOffsetMm : check.safeOffset
    if (!check.valid) {
      toast.error(check.reason || 'Cutting plane reverted to safe center.')
    }

    const planes = [...get().sectionPlanes]
    planes[0] = {
      ...planes[0],
      enabled: true,
      point: [...center] as [number, number, number],
      normal,
      offset: validOffset,
      flipped: sectionFlipped,
      label: badge,
    }
    set({
      isSectionMode: true,
      sectionOffsetMm: validOffset,
      sectionPlanes: planes,
      sectionPlaneAxis: sectionRefPlane === 'Top' ? '+Z' : sectionRefPlane === 'Front' ? '+Y' : '+X',
    })
  },
  setSectionPlaneFromSimple: (ref) => {
    const { normal, badge } = computeSectionPlaneDefinition(
      ref,
      0,
      'Front',
      0,
      false
    )
    const bbox = get().assemblyBoundingBox
    const center = bbox ? bbox.center : [0, 0, 0]
    const planes = [...get().sectionPlanes]
    planes[0] = {
      ...planes[0],
      enabled: true,
      point: [...center] as [number, number, number],
      normal,
      offset: 0,
      flipped: false,
      label: badge,
    }
    set({
      isSectionMode: true,
      sectionRefPlane: ref,
      sectionTiltDeg: 0,
      sectionOffsetMm: 0,
      sectionFlipped: false,
      sectionPlanes: planes,
      sectionPlaneAxis: ref === 'Top' ? '+Z' : ref === 'Front' ? '+Y' : '+X',
    })
  },
  setSectionRefPlane: (ref) => {
    const { sectionTiltDeg, sectionTiltToward, sectionOffsetMm, sectionFlipped, assemblyBoundingBox } = get()
    const { normal, badge } = computeSectionPlaneDefinition(ref, sectionTiltDeg, sectionTiltToward, sectionOffsetMm, sectionFlipped)
    const center = assemblyBoundingBox ? assemblyBoundingBox.center : [0, 0, 0]
    const planes = [...get().sectionPlanes]
    planes[0] = { ...planes[0], enabled: true, point: [...center] as [number, number, number], normal, label: badge }
    set({
      sectionRefPlane: ref,
      sectionPlanes: planes,
      sectionPlaneAxis: ref === 'Top' ? '+Z' : ref === 'Front' ? '+Y' : '+X',
    })
  },
  setSectionTiltDeg: (deg) => {
    const { sectionRefPlane, sectionTiltToward, sectionOffsetMm, sectionFlipped, assemblyBoundingBox } = get()
    const { normal, badge } = computeSectionPlaneDefinition(sectionRefPlane, deg, sectionTiltToward, sectionOffsetMm, sectionFlipped)
    const center = assemblyBoundingBox ? assemblyBoundingBox.center : [0, 0, 0]
    const planes = [...get().sectionPlanes]
    planes[0] = { ...planes[0], enabled: true, point: [...center] as [number, number, number], normal, label: badge }
    set({ sectionTiltDeg: deg, sectionPlanes: planes })
  },
  setSectionTiltToward: (toward) => {
    const { sectionRefPlane, sectionTiltDeg, sectionOffsetMm, sectionFlipped, assemblyBoundingBox } = get()
    const { normal, badge } = computeSectionPlaneDefinition(sectionRefPlane, sectionTiltDeg, toward, sectionOffsetMm, sectionFlipped)
    const center = assemblyBoundingBox ? assemblyBoundingBox.center : [0, 0, 0]
    const planes = [...get().sectionPlanes]
    planes[0] = { ...planes[0], enabled: true, point: [...center] as [number, number, number], normal, label: badge }
    set({ sectionTiltToward: toward, sectionPlanes: planes })
  },
  setSectionOffsetMm: (mm) => {
    const rawVal = isFinite(mm) ? mm : 0
    const planes = [...get().sectionPlanes]
    const activeP = planes[0]
    const bbox = get().assemblyBoundingBox
    const center = bbox ? bbox.center : (activeP.point || [0, 0, 0])

    const check = validateSectionPlaneClipping(
      activeP.normal,
      center,
      rawVal,
      activeP.flipped,
      bbox
    )

    const finalOffset = check.valid ? rawVal : check.safeOffset
    if (!check.valid) {
      toast.error(check.reason || 'Offset clipped 100% of assembly. Clamped to safe range.')
    }

    planes[0] = {
      ...planes[0],
      point: [...center] as [number, number, number],
      offset: finalOffset,
    }
    set({ sectionOffsetMm: finalOffset, sectionPlanes: planes, sectionPlaneOffset: finalOffset })
  },
  toggleSectionFlip: () => {
    const nextFlipped = !get().sectionFlipped
    const { sectionRefPlane, sectionTiltDeg, sectionTiltToward, sectionOffsetMm, assemblyBoundingBox } = get()
    const { normal, badge } = computeSectionPlaneDefinition(sectionRefPlane, sectionTiltDeg, sectionTiltToward, sectionOffsetMm, nextFlipped)
    const center = assemblyBoundingBox ? assemblyBoundingBox.center : [0, 0, 0]
    const planes = [...get().sectionPlanes]
    planes[0] = { ...planes[0], point: [...center] as [number, number, number], normal, flipped: nextFlipped, label: badge }
    set({ sectionFlipped: nextFlipped, sectionPlanes: planes })
  },
  toggleSectionHatch: () => set((s) => ({ sectionHatchEnabled: !s.sectionHatchEnabled })),
  toggleTrueShape: () => {
    const isNowActive = !get().isTrueShapeActive
    if (isNowActive) {
      // Calculate true shape view orientation perpendicular to cut plane
      const activePlane = get().sectionPlanes[0]
      const [nx, ny, nz] = activePlane.normal
      // In Three.js world space: (nx, nz, -ny)
      const tNormal = new THREE.Vector3(nx, nz, -ny).normalize()
      if (activePlane.flipped) tNormal.negate()

      const target = new THREE.Vector3(0, 0, 0)
      const dist = 280
      const pos: [number, number, number] = [
        target.x + tNormal.x * dist,
        target.y + tNormal.y * dist,
        target.z + tNormal.z * dist,
      ]

      let up: [number, number, number] = [0, 1, 0]
      if (Math.abs(tNormal.y) > 0.9) {
        up = [0, 0, -1]
      }

      set({
        isTrueShapeActive: true,
        navSettings: { ...get().navSettings, projection: 'orthographic' },
      })
      get().triggerCameraTransition({
        position: pos,
        target: [target.x, target.y, target.z],
        up,
        durationMs: 300,
        isOrthographic: true,
      })
    } else {
      set({
        isTrueShapeActive: false,
        navSettings: { ...get().navSettings, projection: 'perspective' },
      })
      get().triggerCameraTransition({
        position: [0, 80, 220],
        target: [0, 0, 0],
        up: [0, 1, 0],
        durationMs: 300,
      })
    }
  },
  setIsPickingSectionFace: (picking) => set({ isPickingSectionFace: picking }),
  resetSectionPlane: () => {
    const bbox = get().assemblyBoundingBox
    const center = bbox ? bbox.center : [0, 0, 0]
    const planes = [...get().sectionPlanes]
    planes[0] = {
      ...planes[0],
      enabled: true,
      point: [...center] as [number, number, number],
      normal: [0, 0, 1],
      offset: 0,
      flipped: false,
      label: 'Top view section (horizontal)',
    }
    set({
      sectionRefPlane: 'Top',
      sectionTiltDeg: 0,
      sectionOffsetMm: 0,
      sectionFlipped: false,
      sectionPlanes: planes,
      sectionPlaneAxis: '+Z',
      sectionPlaneOffset: 0,
    })
  },
  closeSectionMode: () => {
    const planes = [...get().sectionPlanes]
    planes.forEach((p) => (p.enabled = false))
    set({
      isSectionMode: false,
      isTrueShapeActive: false,
      isPickingSectionFace: false,
      activeSectionResult: null,
      sectionPlanes: planes,
      sectionPlaneAxis: 'off',
    })
  },

  // Part 1: Navigation setters
  setNavSettings: (settings) => {
    const next = { ...get().navSettings, ...settings }
    saveNavSettings(next)
    set({ navSettings: next })
  },
  setActiveNavTool: (tool) => set({ activeNavTool: tool }),
  triggerCameraTransition: (req) =>
    set({
      cameraTransition: {
        id: Date.now(),
        ...req,
      },
    }),
  triggerFitSelection: () => set((s) => ({ fitSelectionTrigger: s.fitSelectionTrigger + 1 })),
  setLookAtPlaneNormal: (normal) => set({ lookAtPlaneNormal: normal }),

  // Visual findings setters
  setObstructingComponentIds: (ids) => set({ obstructingComponentIds: ids }),
  setActiveClearanceLine: (line) => set({ activeClearanceLine: line }),
  setActiveAccessVector: (vec) => set({ activeAccessVector: vec }),
  clearVisualFindings: () =>
    set({
      obstructingComponentIds: new Set<number>(),
      activeClearanceLine: null,
      activeAccessVector: null,
    }),
}))

if (typeof window !== 'undefined') {
  ;(window as any).useAssemblyStore = useAssemblyStore
}

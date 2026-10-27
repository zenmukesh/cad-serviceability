import { create } from 'zustand'
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

interface AssemblyStore {
  assemblies: Assembly[]
  currentAssembly: Assembly | null
  components: Component[]
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

  // ─── Phase 6: 3D Visual Findings Highlighting ──────────────────────────────
  obstructingComponentIds: Set<number>
  activeClearanceLine: ClearanceLineVisual | null
  activeAccessVector: AccessVectorVisual | null

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

  // 3D Visual Findings Actions
  setObstructingComponentIds: (ids: Set<number>) => void
  setActiveClearanceLine: (line: ClearanceLineVisual | null) => void
  setActiveAccessVector: (vec: AccessVectorVisual | null) => void
  clearVisualFindings: () => void
}

export const useAssemblyStore = create<AssemblyStore>((set, get) => ({
  assemblies: [],
  currentAssembly: null,
  components: [],
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

  setAssemblies: (a) => set({ assemblies: a }),
  setCurrentAssembly: (a) => set({ currentAssembly: a }),
  setComponents: (c) => set({ components: c }),
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

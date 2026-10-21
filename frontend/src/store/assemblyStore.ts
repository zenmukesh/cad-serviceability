import { create } from 'zustand'
import type { Assembly, Component } from '../types/assembly'
import type {
  AssemblyServiceabilityReport,
  ClearanceMeasurement,
  ComponentObstructionReport,
  DisassemblyGraph,
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

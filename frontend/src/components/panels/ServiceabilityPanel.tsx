import { useState, useEffect } from 'react'
import {
  ShieldAlert,
  CheckCircle2,
  Compass,
  Ruler,
  GitCommit,
  Loader2,
  RefreshCw,
  ChevronDown,
  ChevronRight,
  Scissors,
} from 'lucide-react'
import { useAssemblyStore, RightPanelTab } from '../../store/assemblyStore'
import {
  getServiceabilityReport,
  runServiceabilityAnalysis,
  getComponentObstructions,
  getComponentClearances,
  getDependencyGraph,
  getAssemblySection,
} from '../../api/client'
import toast from 'react-hot-toast'

export default function ServiceabilityPanel() {
  const {
    currentAssembly,
    components,
    selectedComponentId,
    selectComponent,
    serviceabilityReport,
    setServiceabilityReport,
    selectedObstructionReport,
    setSelectedObstructionReport,
    clearances,
    setClearances,
    dependencyGraph,
    setDependencyGraph,
    isAnalyzing,
    setIsAnalyzing,
    rightPanelTab,
    setRightPanelTab,
    setObstructingComponentIds,
    setActiveClearanceLine,
    setActiveAccessVector,
    setSectionThroughFinding,
    setActiveSectionResult,
    setIsComputingSection,
  } = useAssemblyStore()

  const [minClearanceMm, setMinClearanceMm] = useState(3.0)
  const [expandedStep, setExpandedStep] = useState<number | null>(null)

  const selectedComp = components.find((c) => c.id === selectedComponentId)

  // Selected component's score in the report
  const selectedCompScore = serviceabilityReport?.component_scores.find(
    (cs) => cs.component_id === selectedComponentId
  )

  // Auto-fetch analysis report on assembly change if not yet loaded
  useEffect(() => {
    if (!currentAssembly || currentAssembly.status !== 'ready') return
    const fetchReport = async () => {
      try {
        setIsAnalyzing(true)
        const rep = await getServiceabilityReport(currentAssembly.id, minClearanceMm)
        setServiceabilityReport(rep)
        const dep = await getDependencyGraph(currentAssembly.id)
        setDependencyGraph(dep)
      } catch (err: any) {
        console.warn('Could not auto-fetch serviceability report:', err)
      } finally {
        setIsAnalyzing(false)
      }
    }
    fetchReport()
  }, [currentAssembly?.id])

  // Fetch component-specific obstruction & clearance when selection changes
  useEffect(() => {
    if (!currentAssembly || selectedComponentId == null) {
      setSelectedObstructionReport(null)
      return
    }

    const fetchComponentDetails = async () => {
      try {
        const obs = await getComponentObstructions(currentAssembly.id, selectedComponentId)
        setSelectedObstructionReport(obs)

        // Set access vector preview for best direction
        if (obs.best_direction_vector && selectedComp?.bounding_box) {
          const bb = selectedComp.bounding_box
          const center: [number, number, number] = [
            (bb.xmin + bb.xmax) / 2,
            (bb.ymin + bb.ymax) / 2,
            (bb.zmin + bb.zmax) / 2,
          ]
          setActiveAccessVector({
            origin: center,
            dir: obs.best_direction_vector,
            label: `Extraction: ${obs.best_direction}`,
          })
        }

        const clrs = await getComponentClearances(
          currentAssembly.id,
          selectedComponentId,
          minClearanceMm
        )
        setClearances(clrs)
      } catch (err: any) {
        console.warn('Error fetching component obstruction/clearance:', err)
      }
    }
    fetchComponentDetails()
  }, [currentAssembly?.id, selectedComponentId, minClearanceMm])

  // Run or re-run analysis
  const handleRunAnalysis = async () => {
    if (!currentAssembly) return
    setIsAnalyzing(true)
    try {
      const rep = await runServiceabilityAnalysis(currentAssembly.id, minClearanceMm)
      setServiceabilityReport(rep)
      const dep = await getDependencyGraph(currentAssembly.id)
      setDependencyGraph(dep)
      toast.success('Serviceability assessment completed')
    } catch (err: any) {
      toast.error('Analysis failed: ' + (err?.message || 'Unknown error'))
    } finally {
      setIsAnalyzing(false)
    }
  }

  // Highlight obstructing components in 3D
  const handleHighlightObstructions = (obstructingIds: number[], dirName: string) => {
    setObstructingComponentIds(new Set(obstructingIds))
    toast(`Highlighting ${obstructingIds.length} obstructing part(s) in Red along ${dirName}`, {
      icon: '🚨',
    })
  }

  // Show 3D clearance dimension line
  const handleShowClearanceIn3D = (c: any) => {
    setActiveClearanceLine({
      p1: [c.point_on_target.x, c.point_on_target.y, c.point_on_target.z],
      p2: [c.point_on_neighbor.x, c.point_on_neighbor.y, c.point_on_neighbor.z],
      dist: c.distance_mm,
      label: `${c.target_component_name} ↔ ${c.neighbor_component_name}`,
    })
    toast.success(`Clearance: ${c.distance_mm.toFixed(2)} mm visualized in 3D`)
  }

  // Phase D (D3): Section through clearance finding
  const handleSectionThroughClearance = async (c: any) => {
    const p1: [number, number, number] = [c.point_on_target.x, c.point_on_target.y, c.point_on_target.z]
    const p2: [number, number, number] = [c.point_on_neighbor.x, c.point_on_neighbor.y, c.point_on_neighbor.z]
    const sep = [p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2]]
    const mag = Math.sqrt(sep[0] ** 2 + sep[1] ** 2 + sep[2] ** 2)
    let normal: [number, number, number] = [0, 0, 1]
    if (mag > 1e-4) {
      normal = [sep[0] / mag, sep[1] / mag, sep[2] / mag]
    } else if (c.removal_direction_vector) {
      normal = c.removal_direction_vector
    }

    setSectionThroughFinding(p1, normal, `Clearance finding: ${c.target_component_name} ↔ ${c.neighbor_component_name}`)
    toast.success(`Section plane aligned through contact points`)

    if (currentAssembly) {
      setIsComputingSection(true)
      try {
        const res = await getAssemblySection(currentAssembly.id, {
          point: p1,
          normal: normal,
          measure_clearance_between: [c.target_component_id, c.neighbor_component_id],
        })
        setActiveSectionResult(res)
      } catch (err: any) {
        console.error('Section calculation failed:', err)
      } finally {
        setIsComputingSection(false)
      }
    }
  }

  // Phase D (D3): Section through obstruction finding
  const handleSectionThroughObstruction = async (ob: any, dirVector?: [number, number, number]) => {
    const targetComp = components.find((c) => c.id === selectedComponentId)
    if (!targetComp || !targetComp.bounding_box) return

    const cx = (targetComp.bounding_box.xmin + targetComp.bounding_box.xmax) / 2
    const cy = (targetComp.bounding_box.ymin + targetComp.bounding_box.ymax) / 2
    const cz = (targetComp.bounding_box.zmin + targetComp.bounding_box.zmax) / 2
    const p: [number, number, number] = [cx, cy, cz]

    let normal: [number, number, number] = dirVector || [0, 0, 1]
    if (ob.nearest_point) {
      const v = [ob.nearest_point.x - cx, ob.nearest_point.y - cy, ob.nearest_point.z - cz]
      const mag = Math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
      if (mag > 1e-4) {
        normal = [v[0] / mag, v[1] / mag, v[2] / mag]
      }
    }

    setSectionThroughFinding(p, normal, `Obstruction finding: ${ob.component_name}`)
    toast.success(`Section plane aligned along obstruction path`)

    if (currentAssembly) {
      setIsComputingSection(true)
      try {
        const res = await getAssemblySection(currentAssembly.id, {
          point: p,
          normal: normal,
          measure_clearance_between: selectedComponentId ? [selectedComponentId, ob.component_id] : undefined,
        })
        setActiveSectionResult(res)
      } catch (err: any) {
        console.error('Section calculation failed:', err)
      } finally {
        setIsComputingSection(false)
      }
    }
  }

  const scoreRatingColor = (score: number) => {
    if (score >= 88) return 'text-emerald-400 border-emerald-500/40 bg-emerald-500/10'
    if (score >= 70) return 'text-blue-400 border-blue-500/40 bg-blue-500/10'
    if (score >= 50) return 'text-amber-400 border-amber-500/40 bg-amber-500/10'
    return 'text-red-400 border-red-500/40 bg-red-500/10'
  }

  const tabs: { id: RightPanelTab; label: string; icon: any }[] = [
    { id: 'serviceability', label: 'Score', icon: CheckCircle2 },
    { id: 'obstructions', label: 'Access', icon: Compass },
    { id: 'clearances', label: 'Clearance', icon: Ruler },
    { id: 'disassembly', label: 'Sequence', icon: GitCommit },
  ]

  return (
    <div className="flex flex-col h-full bg-slate-900 text-slate-100">
      {/* Tab Navigation */}
      <div className="flex items-center border-b border-slate-800 bg-slate-950/60 px-2 pt-2 gap-1 shrink-0 overflow-x-auto">
        {tabs.map((tab) => {
          const Icon = tab.icon
          const isActive = rightPanelTab === tab.id
          return (
            <button
              key={tab.id}
              onClick={() => setRightPanelTab(tab.id)}
              className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 transition-colors whitespace-nowrap ${
                isActive
                  ? 'border-blue-500 text-blue-400 bg-slate-900/80'
                  : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-900/40'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              <span>{tab.label}</span>
            </button>
          )
        })}
      </div>

      {/* Main Content Area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {isAnalyzing && (
          <div className="p-4 bg-blue-950/40 border border-blue-500/30 rounded-lg flex items-center gap-3">
            <Loader2 className="w-5 h-5 text-blue-400 animate-spin shrink-0" />
            <div className="text-xs">
              <p className="font-medium text-white">Performing Geometric Serviceability Analysis</p>
              <p className="text-slate-400">Ray-casting B-Rep surfaces & measuring clearances…</p>
            </div>
          </div>
        )}

        {/* ─── TAB 1: SERVICEABILITY SCORE & DEDUCTIONS ────────────────────── */}
        {rightPanelTab === 'serviceability' && (
          <div className="space-y-4">
            {/* Overall Assembly Score Card */}
            {serviceabilityReport && (
              <div className="bg-slate-950/60 border border-slate-800 rounded-xl p-4">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                    Overall Assembly Serviceability
                  </span>
                  <button
                    onClick={handleRunAnalysis}
                    className="p-1 rounded text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
                    title="Re-run analysis"
                  >
                    <RefreshCw className="w-3.5 h-3.5" />
                  </button>
                </div>

                <div className="flex items-center gap-4">
                  <div
                    className={`w-16 h-16 rounded-xl border flex flex-col items-center justify-center shrink-0 ${scoreRatingColor(
                      serviceabilityReport.overall_score
                    )}`}
                  >
                    <span className="text-2xl font-bold font-mono">
                      {Math.round(serviceabilityReport.overall_score)}
                    </span>
                    <span className="text-[9px] font-semibold tracking-wider uppercase">
                      {serviceabilityReport.overall_rating}
                    </span>
                  </div>

                  <div className="flex-1 text-xs space-y-1">
                    <p className="text-slate-300">
                      Based on CAD kernel bounding boxes, BRepExtrema clearances, and ray-casting access.
                    </p>
                    <div className="flex items-center gap-3 text-[11px] text-slate-400 pt-1">
                      <span>Parts: {serviceabilityReport.analyzed_components_count}</span>
                      <span>Warnings: {serviceabilityReport.warnings_count}</span>
                      {serviceabilityReport.critical_issues_count > 0 && (
                        <span className="text-red-400 font-semibold">
                          Critical: {serviceabilityReport.critical_issues_count}
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Critical Safety Findings */}
                {serviceabilityReport.critical_safety_findings.length > 0 && (
                  <div className="mt-3 p-3 bg-red-950/60 border border-red-500/40 rounded-lg space-y-1">
                    <div className="flex items-center gap-1.5 text-red-400 text-xs font-semibold">
                      <ShieldAlert className="w-4 h-4" />
                      <span>Critical Safety Findings</span>
                    </div>
                    {serviceabilityReport.critical_safety_findings.map((f, idx) => (
                      <p key={idx} className="text-[11px] text-red-300">
                        • {f}
                      </p>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Selected Component Score Card */}
            {selectedComp ? (
              <div className="bg-slate-950/60 border border-slate-800 rounded-xl p-4 space-y-3">
                <div className="flex items-center justify-between pb-2 border-b border-slate-800">
                  <div>
                    <h4 className="text-xs font-semibold text-white truncate max-w-[200px]">
                      {selectedComp.display_name}
                    </h4>
                    <p className="text-[10px] text-slate-400 font-mono">
                      ID: {selectedComp.cad_entity_id}
                    </p>
                  </div>

                  {selectedCompScore && (
                    <div
                      className={`px-2.5 py-1 rounded-lg border font-mono font-bold text-sm ${scoreRatingColor(
                        selectedCompScore.score
                      )}`}
                    >
                      {selectedCompScore.score} / 100
                    </div>
                  )}
                </div>

                {selectedCompScore ? (
                  <>
                    {/* Sub-score bars */}
                    <div className="space-y-2 pt-1">
                      <div className="space-y-1">
                        <div className="flex justify-between text-[11px] text-slate-400">
                          <span>Access & Obstruction:</span>
                          <span className="font-mono text-slate-200">
                            {selectedCompScore.access_score} / 25
                          </span>
                        </div>
                        <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
                          <div
                            className="bg-blue-500 h-full rounded-full"
                            style={{ width: `${(selectedCompScore.access_score / 25) * 100}%` }}
                          />
                        </div>
                      </div>

                      <div className="space-y-1">
                        <div className="flex justify-between text-[11px] text-slate-400">
                          <span>Clearance & Fit:</span>
                          <span className="font-mono text-slate-200">
                            {selectedCompScore.clearance_score} / 25
                          </span>
                        </div>
                        <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
                          <div
                            className="bg-emerald-500 h-full rounded-full"
                            style={{ width: `${(selectedCompScore.clearance_score / 25) * 100}%` }}
                          />
                        </div>
                      </div>

                      <div className="space-y-1">
                        <div className="flex justify-between text-[11px] text-slate-400">
                          <span>Disassembly Effort:</span>
                          <span className="font-mono text-slate-200">
                            {selectedCompScore.disassembly_score} / 25
                          </span>
                        </div>
                        <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
                          <div
                            className="bg-purple-500 h-full rounded-full"
                            style={{ width: `${(selectedCompScore.disassembly_score / 25) * 100}%` }}
                          />
                        </div>
                      </div>

                      <div className="space-y-1">
                        <div className="flex justify-between text-[11px] text-slate-400">
                          <span>Fastener Complexity:</span>
                          <span className="font-mono text-slate-200">
                            {selectedCompScore.fastener_score} / 25
                          </span>
                        </div>
                        <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
                          <div
                            className="bg-amber-500 h-full rounded-full"
                            style={{ width: `${(selectedCompScore.fastener_score / 25) * 100}%` }}
                          />
                        </div>
                      </div>
                    </div>

                    {/* Deductions Breakdown */}
                    <div className="pt-2">
                      <h5 className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-2">
                        Traceable Score Deductions ({selectedCompScore.deductions.length})
                      </h5>
                      {selectedCompScore.deductions.length === 0 ? (
                        <p className="text-xs text-emerald-400 flex items-center gap-1.5">
                          <CheckCircle2 className="w-3.5 h-3.5" />
                          No penalties — optimal access and clearance!
                        </p>
                      ) : (
                        <div className="space-y-1.5">
                          {selectedCompScore.deductions.map((d, idx) => (
                            <div
                              key={idx}
                              className="p-2 bg-slate-900 border border-slate-800 rounded text-xs space-y-0.5"
                            >
                              <div className="flex items-center justify-between">
                                <span className="font-medium text-slate-300 text-[11px]">
                                  {d.criterion}
                                </span>
                                <span className="text-red-400 font-mono font-bold text-[11px]">
                                  -{d.penalty_points} pts
                                </span>
                              </div>
                              <p className="text-slate-400 text-[11px]">{d.description}</p>
                              {d.measured_value && (
                                <p className="text-[10px] text-slate-500 font-mono">
                                  Measured: {d.measured_value} (Threshold: {d.threshold})
                                </p>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </>
                ) : (
                  <p className="text-xs text-slate-500">Run analysis to view component scoring.</p>
                )}
              </div>
            ) : (
              <div className="p-6 text-center text-slate-500 text-xs border border-dashed border-slate-800 rounded-xl">
                Select a component in the tree or 3D viewer to inspect its serviceability deductions.
              </div>
            )}
          </div>
        )}

        {/* ─── TAB 2: OBSTRUCTION & ACCESS PATHS ───────────────────────────── */}
        {rightPanelTab === 'obstructions' && (
          <div className="space-y-3">
            {selectedComp ? (
              selectedObstructionReport ? (
                <>
                  {/* Phase C Continuous Extraction Vector & Freedom Cone */}
                  <div className="bg-slate-950/60 border border-slate-800 rounded-xl p-3 space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                        Arbitrary Direction Engine
                      </span>
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-blue-950 text-blue-300 border border-blue-700/50">
                        Best: {selectedObstructionReport.best_direction || 'None'}
                      </span>
                    </div>

                    <div className="grid grid-cols-2 gap-2 text-[11px]">
                      <div className="bg-slate-900/60 p-2 rounded border border-slate-800">
                        <div className="text-[9px] uppercase tracking-wider text-slate-500 font-semibold">
                          Optimal Vector
                        </div>
                        <div className="font-mono font-bold text-cyan-300">
                          {selectedObstructionReport.best_direction_vector
                            ? `[${selectedObstructionReport.best_direction_vector.map((v) => v.toFixed(2)).join(', ')}]`
                            : 'None'}
                        </div>
                      </div>
                      <div className="bg-slate-900/60 p-2 rounded border border-slate-800">
                        <div className="text-[9px] uppercase tracking-wider text-slate-500 font-semibold">
                          Freedom Cone θ
                        </div>
                        <div className="font-mono font-bold text-emerald-400">
                          {selectedObstructionReport.freedom_cone_half_angle_deg != null
                            ? `±${selectedObstructionReport.freedom_cone_half_angle_deg.toFixed(1)}°`
                            : '0.0°'}
                        </div>
                      </div>
                    </div>

                    <div className="flex justify-between items-center text-[11px] text-slate-400 pt-1 border-t border-slate-800/80">
                      <span>Max Free Travel:</span>
                      <span className="font-mono font-semibold text-white">
                        {selectedObstructionReport.max_free_travel_mm.toFixed(1)} mm
                      </span>
                    </div>
                  </div>

                  {/* Fastener Tool Approach Card (if applicable) */}
                  {(() => {
                    const toolApp = serviceabilityReport?.tool_approaches?.find(
                      (ta) => ta.component_id === selectedComponentId
                    )
                    if (!toolApp) return null
                    return (
                      <div className="bg-slate-950/60 border border-slate-800 rounded-xl p-3 space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                            Fastener Tool Approach
                          </span>
                          <span
                            className={`text-[10px] font-mono px-2 py-0.5 rounded font-bold border ${
                              toolApp.is_tool_access_free
                                ? 'bg-emerald-950/80 text-emerald-300 border-emerald-600/40'
                                : 'bg-red-950/80 text-red-300 border-red-600/40'
                            }`}
                          >
                            {toolApp.is_tool_access_free ? 'Tool Access Free' : 'Tool Path Obstructed'}
                          </span>
                        </div>
                        <p className="text-[11px] text-slate-400">{toolApp.details}</p>
                        <div className="grid grid-cols-2 gap-2 text-[11px]">
                          <div className="bg-slate-900/60 p-1.5 rounded border border-slate-800">
                            <span className="text-[9px] uppercase text-slate-500 block">Envelope</span>
                            <span className="font-mono text-slate-300">
                              R={toolApp.tool_radius_mm}mm, L={toolApp.tool_length_mm}mm
                            </span>
                          </div>
                          <div className="bg-slate-900/60 p-1.5 rounded border border-slate-800">
                            <span className="text-[9px] uppercase text-slate-500 block">Usable Tilt</span>
                            <span className="font-mono text-cyan-300">
                              {toolApp.usable_tilt_angle_deg.toFixed(1)}° / {toolApp.tilt_cone_half_angle_deg.toFixed(1)}°
                            </span>
                          </div>
                        </div>
                        {toolApp.blocking_components.length > 0 && (
                          <div className="text-[10px] text-red-300 bg-red-950/40 p-1.5 rounded border border-red-900/50">
                            Blocked by: {toolApp.blocking_components.join(', ')}
                          </div>
                        )}
                      </div>
                    )
                  })()}

                  {/* Feasible Candidate Directions (if any beyond cardinal) */}
                  {selectedObstructionReport.feasible_candidate_directions &&
                    selectedObstructionReport.feasible_candidate_directions.length > 0 && (
                      <div className="space-y-1.5">
                        <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                          Feasible Arbitrary Motions ({selectedObstructionReport.feasible_candidate_directions.length})
                        </div>
                        <div className="space-y-1">
                          {selectedObstructionReport.feasible_candidate_directions.map((fc, i) => (
                            <div
                              key={i}
                              className="p-2 rounded bg-emerald-950/20 border border-emerald-500/30 flex items-center justify-between text-xs"
                            >
                              <div className="flex items-center gap-1.5">
                                <span className="font-mono text-emerald-300 font-bold">{fc.direction_name}</span>
                                <span className="font-mono text-[10px] text-slate-400">
                                  [{fc.direction_vector.map((v) => v.toFixed(2)).join(', ')}]
                                </span>
                              </div>
                              <span className="font-mono text-emerald-400 text-[11px]">
                                {fc.free_travel_mm.toFixed(1)} mm
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                  <div className="bg-slate-950/60 border border-slate-800 rounded-xl p-3">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                        Cardinal Axes (Derived View)
                      </span>
                    </div>
                    <p className="text-[11px] text-slate-400">
                      Evaluated along the 6 principal axes derived from the arbitrary swept collision engine.
                    </p>
                  </div>

                  {/* Directions Table */}
                  <div className="space-y-2">
                    {selectedObstructionReport.directions.map((d) => (
                      <div
                        key={d.direction_name}
                        className={`p-3 rounded-lg border text-xs space-y-2 ${
                          d.is_clear
                            ? 'bg-emerald-950/20 border-emerald-500/30'
                            : d.direction_name === selectedObstructionReport.best_direction
                            ? 'bg-blue-950/20 border-blue-500/40'
                            : 'bg-slate-950/40 border-slate-800'
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="font-mono font-bold text-white text-sm">
                              {d.direction_name}
                            </span>
                            {d.is_clear ? (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-900/60 text-emerald-300 font-semibold uppercase">
                                Clear
                              </span>
                            ) : (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-900/60 text-red-300 font-semibold uppercase">
                                Obstructed ({Math.round(d.blockage_ratio * 100)}%)
                              </span>
                            )}
                          </div>

                          <span className="font-mono text-slate-300 text-[11px]">
                            Free: {d.free_travel_mm.toFixed(1)} mm
                          </span>
                        </div>

                        {d.obstructing_components.length > 0 && (
                          <div className="pt-1 space-y-1">
                            <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                              Obstructing Components:
                            </div>
                            {d.obstructing_components.map((ob, idx) => (
                              <div
                                key={idx}
                                className="flex items-center justify-between text-[11px] bg-slate-900/80 p-1.5 rounded"
                              >
                                <span className="text-slate-200 truncate max-w-[140px]">
                                  {ob.component_name}
                                </span>
                                <div className="flex items-center gap-2">
                                  <span className="font-mono text-slate-400">
                                    {ob.distance_to_obstruction_mm.toFixed(1)} mm
                                  </span>
                                  <button
                                    onClick={() =>
                                      handleHighlightObstructions(
                                        [ob.component_id],
                                        d.direction_name
                                      )
                                    }
                                    className="text-[10px] text-red-400 hover:text-red-200 underline"
                                  >
                                    Highlight
                                  </button>
                                  <button
                                    onClick={() => handleSectionThroughObstruction(ob, d.direction_vector)}
                                    className="flex items-center gap-0.5 text-[10px] text-cyan-400 hover:text-cyan-200 underline"
                                    title="Cut a section plane through this obstruction finding"
                                  >
                                    <Scissors className="w-2.5 h-2.5" />
                                    <span>Section</span>
                                  </button>
                                </div>
                              </div>
                            ))}

                            <button
                              onClick={() =>
                                handleHighlightObstructions(
                                  d.obstructing_components.map((o) => o.component_id),
                                  d.direction_name
                                )
                              }
                              className="w-full mt-1 py-1 rounded bg-red-950/60 hover:bg-red-900/70 text-red-300 border border-red-500/30 text-[10px] font-medium transition-colors"
                            >
                              Highlight All Obstructing in Red
                            </button>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <div className="p-4 text-center text-slate-400 text-xs">
                  Loading obstruction analysis…
                </div>
              )
            ) : (
              <div className="p-6 text-center text-slate-500 text-xs border border-dashed border-slate-800 rounded-xl">
                Select a component to inspect its multi-directional obstruction envelopes.
              </div>
            )}
          </div>
        )}

        {/* ─── TAB 3: CLEARANCE MEASUREMENTS ──────────────────────────────── */}
        {rightPanelTab === 'clearances' && (
          <div className="space-y-3">
            <div className="bg-slate-950/60 border border-slate-800 rounded-xl p-3 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                  Clearance Threshold
                </span>
                <span className="text-xs font-mono text-blue-400 font-semibold">
                  {minClearanceMm.toFixed(1)} mm
                </span>
              </div>
              <input
                type="range"
                min={0.5}
                max={15.0}
                step={0.5}
                value={minClearanceMm}
                onChange={(e) => setMinClearanceMm(parseFloat(e.target.value))}
                className="w-full h-1.5 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-blue-500"
              />
            </div>

            {clearances.length > 0 ? (
              <div className="space-y-2">
                <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                  Measured Pairwise Clearances ({clearances.length})
                </div>
                {clearances.map((c, idx) => (
                  <div
                    key={idx}
                    className={`p-2.5 rounded-lg border text-xs space-y-1.5 transition-colors ${
                      c.classification === 'INTERFERENCE'
                        ? 'bg-red-950/40 border-red-500/50'
                        : c.is_contact
                        ? 'bg-slate-950/40 border-slate-800'
                        : c.is_pass
                        ? 'bg-emerald-950/20 border-emerald-500/30'
                        : 'bg-amber-950/20 border-amber-500/30'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-slate-200 truncate max-w-[160px]">
                        {c.neighbor_component_name}
                      </span>
                      <span
                        className={`font-mono font-bold text-xs ${
                          c.classification === 'INTERFERENCE'
                            ? 'text-red-400'
                            : c.is_contact
                            ? 'text-slate-400'
                            : c.is_pass
                            ? 'text-emerald-400'
                            : 'text-amber-400'
                        }`}
                      >
                        {c.classification === 'INTERFERENCE'
                          ? `Clash (${c.intersection_volume_mm3 ? c.intersection_volume_mm3.toFixed(2) : '>0'} mm³)`
                          : c.is_contact
                          ? 'Contact (0.00 mm³)'
                          : `${c.distance_mm.toFixed(2)} mm`}
                      </span>
                    </div>

                    <div className="flex items-center justify-between text-[10px] text-slate-400">
                      <span>{c.notes}</span>
                      <div className="flex items-center gap-1.5">
                        {!c.is_contact && (
                          <button
                            onClick={() => handleShowClearanceIn3D(c)}
                            className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-blue-400 text-[10px] font-medium transition-colors"
                          >
                            View in 3D
                          </button>
                        )}
                        <button
                          onClick={() => handleSectionThroughClearance(c)}
                          className="flex items-center gap-1 px-2 py-0.5 rounded bg-cyan-950/80 hover:bg-cyan-900 border border-cyan-500/40 text-cyan-300 text-[10px] font-medium transition-colors"
                          title="Cut an exact section plane through this clearance finding"
                        >
                          <Scissors className="w-2.5 h-2.5" />
                          <span>Section</span>
                        </button>
                      </div>
                    </div>

                    {c.directional_clearance_mm != null && (
                      <div className="flex items-center justify-between text-[10px] bg-slate-900/60 px-1.5 py-0.5 rounded border border-slate-800/80">
                        <span className="text-slate-400">Swept Clearance ({c.removal_direction_name || 'vector'}):</span>
                        <span className="font-mono text-cyan-300 font-semibold">{c.directional_clearance_mm.toFixed(2)} mm</span>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-slate-500 text-center py-4">
                No clearances measured. Select a component to view its adjacent clearances.
              </p>
            )}
          </div>
        )}

        {/* ─── TAB 4: DISASSEMBLY DEPENDENCY SEQUENCE ──────────────────────── */}
        {rightPanelTab === 'disassembly' && (
          <div className="space-y-3">
            {dependencyGraph ? (
              <>
                {/* Header Metrics Card */}
                <div className="bg-slate-950/60 border border-slate-800 rounded-xl p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                      Disassembly Planner
                    </span>
                    <div className="flex items-center gap-1.5 flex-wrap justify-end">
                      <span
                        className={`text-[10px] font-mono px-2 py-0.5 rounded font-semibold border ${
                          dependencyGraph.sequence_status === 'physically_verified'
                            ? 'bg-emerald-950/80 text-emerald-400 border-emerald-600/40'
                            : dependencyGraph.sequence_status === 'cycle_detected'
                            ? 'bg-amber-950/80 text-amber-400 border-amber-600/40'
                            : dependencyGraph.sequence_status === 'budget_exhausted'
                            ? 'bg-purple-950/80 text-purple-400 border-purple-600/40'
                            : dependencyGraph.sequence_status === 'candidate_with_path_collisions'
                            ? 'bg-rose-950/80 text-rose-400 border-rose-600/40'
                            : 'bg-blue-950/80 text-blue-400 border-blue-600/40'
                        }`}
                      >
                        {dependencyGraph.sequence_status === 'physically_verified'
                          ? 'Complete Sequence Verified'
                          : dependencyGraph.sequence_status === 'cycle_detected'
                          ? 'Cycle Detected'
                          : dependencyGraph.sequence_status === 'budget_exhausted'
                          ? 'Search Budget Exhausted'
                          : dependencyGraph.sequence_status === 'candidate_with_path_collisions'
                          ? 'Partial Sequence'
                          : 'Candidate Sequence'}
                      </span>
                      <span className="text-xs font-mono text-purple-400 font-semibold">
                        {dependencyGraph.total_steps} Steps
                      </span>
                    </div>
                  </div>

                  {/* Planner Metrics */}
                  <div className="grid grid-cols-3 gap-2 pt-1 border-t border-slate-800/80 text-[11px]">
                    <div className="bg-slate-900/60 p-1.5 rounded border border-slate-800">
                      <div className="text-[9px] uppercase tracking-wider text-slate-500 font-semibold">
                        Effort Cost
                      </div>
                      <div className="font-mono font-bold text-slate-200">
                        {dependencyGraph.total_disassembly_effort_score !== undefined
                          ? dependencyGraph.total_disassembly_effort_score.toFixed(1)
                          : '0.0'}{' '}
                        pts
                      </div>
                    </div>
                    <div className="bg-slate-900/60 p-1.5 rounded border border-slate-800">
                      <div className="text-[9px] uppercase tracking-wider text-slate-500 font-semibold">
                        Search Nodes
                      </div>
                      <div className="font-mono font-bold text-slate-200">
                        {dependencyGraph.search_nodes_explored ?? 0} explored
                      </div>
                    </div>
                    <div className="bg-slate-900/60 p-1.5 rounded border border-slate-800">
                      <div className="text-[9px] uppercase tracking-wider text-slate-500 font-semibold">
                        Verified Steps
                      </div>
                      <div className="font-mono font-bold text-emerald-400">
                        {dependencyGraph.verified_steps_count}/{dependencyGraph.total_steps}
                      </div>
                    </div>
                  </div>

                  {dependencyGraph.validation_notes && dependencyGraph.validation_notes.length > 0 && (
                    <div className="text-[10px] text-slate-400 pt-1 border-t border-slate-800/50 space-y-0.5">
                      {dependencyGraph.validation_notes.map((note, idx) => (
                        <p key={idx} className="leading-tight text-slate-400">
                          • {note}
                        </p>
                      ))}
                    </div>
                  )}
                </div>

                {/* Steps List */}
                <div className="space-y-2">
                  {dependencyGraph.sequence.map((step) => {
                    const isSelected = selectedComponentId === step.component_id
                    const isExpanded = expandedStep === step.step_number

                    // Distinct status classification strictly enforcing verified vs unverified
                    const statusText = !step.is_path_verified
                      ? (step.status_label && !step.status_label.includes('verified') && !step.status_label.includes('found')
                          ? step.status_label
                          : (step.path_validation_status === 'cyclic'
                              ? 'Unresolved dependency cycle'
                              : step.path_validation_status === 'blocked' ||
                                step.path_validation_status === 'collision_detected'
                              ? 'No feasible straight-line path found'
                              : 'Candidate — unverified'))
                      : (step.status_label || 'Ready — path verified')

                    const statusStyle =
                      statusText === 'Ready — path verified'
                        ? 'bg-emerald-950/80 text-emerald-400 border-emerald-600/40'
                        : statusText === 'Alternative direction found'
                        ? 'bg-cyan-950/80 text-cyan-400 border-cyan-600/40'
                        : statusText === 'Prerequisite required'
                        ? 'bg-amber-950/80 text-amber-400 border-amber-600/40'
                        : statusText === 'No feasible straight-line path found'
                        ? 'bg-rose-950/80 text-rose-400 border-rose-600/40'
                        : statusText === 'Candidate — unverified'
                        ? 'bg-slate-900 text-slate-300 border-slate-700'
                        : 'bg-purple-950/80 text-purple-400 border-purple-600/40'

                    return (
                      <div
                        key={step.step_number}
                        className={`p-2.5 rounded-lg border text-xs transition-colors space-y-1.5 ${
                          isSelected
                            ? 'bg-blue-600/25 border-blue-500 shadow-xs'
                            : 'bg-slate-950/40 border-slate-800 hover:bg-slate-800/60'
                        }`}
                      >
                        {/* Row Header */}
                        <div
                          className="flex items-center justify-between cursor-pointer"
                          onClick={() => selectComponent(step.component_id)}
                        >
                          <div className="flex items-center gap-2">
                            <span className="w-5 h-5 rounded-full bg-slate-800 text-slate-300 flex items-center justify-center font-mono text-[10px] font-bold">
                              {step.step_number}
                            </span>
                            <span
                              className={`font-medium ${
                                isSelected ? 'text-white' : 'text-slate-200'
                              }`}
                            >
                              {step.component_name}
                            </span>
                            {step.is_unified_fastener && (
                              <span className="text-[9px] font-mono px-1 py-0.2 rounded bg-purple-950 text-purple-300 border border-purple-600/30">
                                Rigid Fastener
                              </span>
                            )}
                          </div>

                          <div className="flex items-center gap-1.5">
                            {step.motion_type && (
                              <span className="text-[9px] font-mono px-1.5 py-0.2 rounded bg-cyan-950 text-cyan-300 font-semibold border border-cyan-800/40 uppercase">
                                {step.motion_type}
                              </span>
                            )}
                            {step.removal_direction && (
                              <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-slate-800 text-blue-300 font-bold border border-slate-700">
                                {step.removal_direction}
                              </span>
                            )}
                            <span
                              className={`text-[9px] font-mono font-semibold px-1.5 py-0.5 rounded border ${statusStyle}`}
                            >
                              {statusText}
                            </span>
                          </div>
                        </div>

                        {/* Step Details & Travel Metric */}
                        <div className="flex items-center justify-between text-[10px] text-slate-400 pl-7">
                          <span>
                            {step.action.replace('_', ' ').toUpperCase()} •{' '}
                            {step.max_verified_travel_mm != null && step.is_path_verified
                              ? `${step.max_verified_travel_mm.toFixed(1)} mm travel`
                              : 'No travel verified'}
                          </span>
                          <div className="flex items-center gap-2">
                            {step.step_effort_cost != null && step.step_effort_cost > 0 && (
                              <span className="font-mono text-slate-400">
                                {step.step_effort_cost.toFixed(1)} pts
                              </span>
                            )}
                            <button
                              onClick={(e) => {
                                e.stopPropagation()
                                setExpandedStep(isExpanded ? null : step.step_number)
                              }}
                              className="text-slate-400 hover:text-slate-200 p-0.5 rounded transition-colors"
                              title="Toggle evidence details"
                            >
                              {isExpanded ? (
                                <ChevronDown className="w-3.5 h-3.5" />
                              ) : (
                                <ChevronRight className="w-3.5 h-3.5" />
                              )}
                            </button>
                          </div>
                        </div>

                        {/* Prerequisites */}
                        {step.prerequisites.length > 0 && (
                          <div className="text-[10px] text-slate-400 pl-7 flex items-center gap-1">
                            <span className="text-slate-500">Requires:</span>
                            <span className="text-slate-300 truncate">
                              {step.prerequisites.join(', ')}
                            </span>
                          </div>
                        )}

                        {/* Blocking components summary when relevant */}
                        {!step.is_path_verified && step.colliding_components_along_path && step.colliding_components_along_path.length > 0 && (
                          <div className="text-[10px] text-rose-400 pl-7 flex items-center gap-1 truncate">
                            <span className="text-rose-500 font-semibold">Blocking:</span>
                            <span className="truncate">{step.colliding_components_along_path.join(', ')}</span>
                          </div>
                        )}

                        {/* Expandable Details Accordion */}
                        {isExpanded && (
                          <div className="mt-2 pt-2 border-t border-slate-800 text-[11px] space-y-2 pl-7 bg-slate-900/40 p-2.5 rounded">
                            <div className="text-slate-300">
                              <span className="text-slate-500 font-semibold">Details:</span> {step.notes}
                            </div>

                            {/* 6-Direction Evaluation Grid */}
                            {step.direction_attempts && step.direction_attempts.length > 0 && (
                              <div className="space-y-1 pt-1 border-t border-slate-800/80">
                                <span className="text-slate-400 font-semibold text-[10px] uppercase tracking-wider">
                                  Tested Extraction Directions ({step.direction_attempts.length} axes):
                                </span>
                                <div className="grid grid-cols-2 gap-1.5 pt-0.5">
                                  {step.direction_attempts.map((att) => {
                                    const isSelectedDir = att.direction === step.removal_direction && step.is_path_verified
                                    return (
                                      <div
                                        key={att.direction}
                                        className={`p-1.5 rounded border text-[10px] flex items-center justify-between ${
                                          att.is_clear
                                            ? isSelectedDir
                                              ? 'bg-emerald-950/60 border-emerald-500/50 text-emerald-300 font-semibold'
                                              : 'bg-slate-900 border-slate-800 text-slate-300'
                                            : 'bg-rose-950/30 border-rose-900/40 text-rose-300'
                                        }`}
                                      >
                                        <span className="font-mono font-bold">{att.direction}</span>
                                        <span className="truncate max-w-[130px] text-[9px] text-right">
                                          {att.is_clear
                                            ? `✓ Clear (${att.max_travel_mm?.toFixed(1)} mm)${isSelectedDir ? ' ★' : ''}`
                                            : `✕ ${att.colliding_components.join(', ')}`}
                                        </span>
                                      </div>
                                    )
                                  })}
                                </div>
                              </div>
                            )}

                            {step.reorientation_required && (
                              <div className="text-amber-400 text-[10px]">
                                ↻ Reorientation penalty applied (+2.0 effort pts)
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </>
            ) : (
              <p className="text-xs text-slate-500 text-center py-4">
                Loading disassembly dependency sequence…
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

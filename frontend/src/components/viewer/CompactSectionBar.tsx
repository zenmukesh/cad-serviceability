import React, { useState, useMemo } from 'react'
import {
  X,
  RotateCw,
  Check,
  Eye,
  Crosshair,
  Sliders,
  Layers,
  Sparkles,
} from 'lucide-react'
import { useAssemblyStore, computeSectionPlaneDefinition } from '../../store/assemblyStore'
import { getAssemblySection } from '../../api/client'
import toast from 'react-hot-toast'

export const CompactSectionBar: React.FC = () => {
  const {
    isSectionMode,
    sectionRefPlane,
    sectionTiltDeg,
    sectionTiltToward,
    sectionOffsetMm,
    sectionFlipped,
    sectionHatchEnabled,
    isTrueShapeActive,
    isPickingSectionFace,
    currentAssembly,
    sectionPlanes,
    setSectionPlane,
    sectionCombinedMode,
    setSectionCombinedMode,
    setSectionPlaneFromSimple,
    setSectionOffsetMm,
    setSectionTiltDeg,
    toggleSectionFlip,
    toggleSectionHatch,
    toggleTrueShape,
    setIsPickingSectionFace,
    resetSectionPlane,
    closeSectionMode,
    setActiveSectionResult,
    isComputingSection,
    setIsComputingSection,
    dependencyGraph,
    assemblyBoundingBox,
  } = useAssemblyStore()

  const maxOffsetRange = assemblyBoundingBox
    ? Math.max(60, Math.round(Math.max(assemblyBoundingBox.size[0], assemblyBoundingBox.size[1], assemblyBoundingBox.size[2]) * 0.45))
    : 100

  const [isAdvancedOpen, setIsAdvancedOpen] = useState(false)
  const [activeAdvPlaneIdx, setActiveAdvPlaneIdx] = useState(0)

  // 3-point plane default reference points
  const pt1: [number, number, number] = [0, 0, 0]
  const pt2: [number, number, number] = [20, 0, 0]
  const pt3: [number, number, number] = [0, 20, 0]

  const activePlane = sectionPlanes[0]

  // Live Engineering-Graphics Badge text
  const badgeText = useMemo(() => {
    const { badge } = computeSectionPlaneDefinition(
      sectionRefPlane,
      sectionTiltDeg,
      sectionTiltToward,
      sectionOffsetMm,
      sectionFlipped
    )
    return badge
  }, [sectionRefPlane, sectionTiltDeg, sectionTiltToward, sectionOffsetMm, sectionFlipped])

  if (!isSectionMode) return null

  // On-demand exact BREP section calculation
  const handleComputeExactSection = async () => {
    if (!currentAssembly || !activePlane) return
    setIsComputingSection(true)
    try {
      const res = await getAssemblySection(currentAssembly.id, {
        point: activePlane.point,
        normal: activePlane.normal,
      })
      setActiveSectionResult(res)
      toast.success(
        `Exact BREP section: ${res.component_sections.length} parts cut (${res.total_cut_area_mm2.toFixed(1)} mm²)`
      )
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to compute exact section')
    } finally {
      setIsComputingSection(false)
    }
  }

  // 3-Point Plane Calculation in Advanced
  const applyThreePoints = () => {
    const v1 = [pt2[0] - pt1[0], pt2[1] - pt1[1], pt2[2] - pt1[2]]
    const v2 = [pt3[0] - pt1[0], pt3[1] - pt1[1], pt3[2] - pt1[2]]
    const nx = v1[1] * v2[2] - v1[2] * v2[1]
    const ny = v1[2] * v2[0] - v1[0] * v2[2]
    const nz = v1[0] * v2[1] - v1[1] * v2[0]
    const mag = Math.sqrt(nx * nx + ny * ny + nz * nz)

    if (mag < 1e-6) {
      toast.error('Points are collinear; cannot define a unique plane.')
      return
    }

    const norm: [number, number, number] = [nx / mag, ny / mag, nz / mag]
    setSectionPlane(0, {
      enabled: true,
      point: pt1,
      normal: norm,
      offset: 0,
      label: '3-Point Plane',
    })
    toast.success('3-Point section plane applied')
  }

  // Plane through removal direction of selected component
  const handlePlaneThroughRemoval = () => {
    const selectedId = useAssemblyStore.getState().selectedComponentId
    if (!selectedId || !dependencyGraph?.sequence) {
      toast.error('Select a component with a removal sequence first')
      return
    }
    const step = dependencyGraph.sequence.find((s) => s.component_id === selectedId)
    if (!step?.direction_vector) {
      toast.error('No verified removal direction for selected component')
      return
    }
    const [dx, dy, dz] = step.direction_vector
    setSectionPlane(0, {
      enabled: true,
      normal: [dx, dy, dz],
      offset: 0,
      label: `Through Removal Vector [${dx.toFixed(2)}, ${dy.toFixed(2)}, ${dz.toFixed(2)}]`,
    })
    toast.success('Section plane aligned through component removal vector')
  }

  return (
    <div
      className="absolute bottom-5 left-1/2 -translate-x-1/2 z-30 flex flex-col items-center select-none"
      style={{ maxWidth: 'min(94vw, 520px)' }}
      data-testid="compact-section-bar"
    >
      {/* 2.2 Live Engineering-Graphics Badge (Docked above bar, never over model center) */}
      <div
        data-testid="section-gizmo-badge"
        className="flex items-center justify-between gap-3 px-3 py-1 bg-slate-950/90 text-cyan-300 border border-cyan-500/60 rounded-lg text-xs font-mono font-semibold whitespace-nowrap shadow-xl backdrop-blur-md mb-1.5"
      >
        <div className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 inline-block animate-pulse" />
          <span>{badgeText}</span>
        </div>
        <div className="text-[10px] text-slate-400 font-sans">
          Offset: {sectionOffsetMm.toFixed(1)} mm | Tilt: {sectionTiltDeg.toFixed(0)}° (Snap 5°, Alt=Free)
        </div>
      </div>

      {/* ─── Compact Engineering-Graphics Section Bar (~420-480px) ─────────── */}
      <div className="flex items-center gap-1.5 px-3 py-2 bg-slate-900/95 backdrop-blur-md border border-slate-700/80 rounded-xl shadow-2xl text-slate-200 text-xs w-full justify-between">
        {/* Reference Plane Selector: [ Top | Front | Side ] */}
        <div className="flex items-center bg-slate-800 rounded-lg p-0.5 border border-slate-700/60 shrink-0">
          {(['Top', 'Front', 'Side'] as const).map((ref) => (
            <button
              key={ref}
              onClick={() => setSectionPlaneFromSimple(ref)}
              data-testid={`section-ref-${ref.toLowerCase()}`}
              className={`px-2 py-1 rounded text-[11px] font-semibold transition-colors ${
                sectionRefPlane === ref
                  ? 'bg-blue-600 text-white shadow-xs'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/50'
              }`}
            >
              {ref}
            </button>
          ))}
        </div>

        {/* [ Pick face ] button */}
        <button
          onClick={() => setIsPickingSectionFace(!isPickingSectionFace)}
          data-testid="section-pick-face-btn"
          title="Click a planar face to coincide cutting plane"
          className={`flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium transition-colors border shrink-0 ${
            isPickingSectionFace
              ? 'bg-cyan-600 border-cyan-400 text-white shadow-xs animate-pulse'
              : 'bg-slate-800 border-slate-700/60 text-slate-300 hover:text-white hover:bg-slate-700'
          }`}
        >
          <Crosshair className="w-3 h-3 text-cyan-400" />
          <span className="hidden sm:inline">Pick</span>
        </button>

        {/* Offset [slider + mm] */}
        <div className="flex items-center gap-1 bg-slate-800/80 px-2 py-1 rounded-md border border-slate-700/50">
          <span className="text-[10px] text-slate-400 font-medium">Off:</span>
          <input
            type="range"
            min={-maxOffsetRange}
            max={maxOffsetRange}
            step={1}
            value={sectionOffsetMm}
            onChange={(e) => {
              const v = parseFloat(e.target.value)
              setSectionOffsetMm(isNaN(v) ? 0 : v)
            }}
            data-testid="section-offset-slider"
            className="w-14 sm:w-16 h-1 bg-slate-700 rounded appearance-none cursor-pointer accent-blue-500"
            title={`Offset: ${sectionOffsetMm} mm`}
          />
          <span className="text-[10px] font-mono w-7 text-right text-slate-300">
            {sectionOffsetMm}
          </span>
        </div>

        {/* Tilt [angle + deg] */}
        <div className="flex items-center gap-1 bg-slate-800/80 px-2 py-1 rounded-md border border-slate-700/50">
          <span className="text-[10px] text-slate-400 font-medium">Tilt:</span>
          <input
            type="range"
            min={0}
            max={90}
            step={5}
            value={sectionTiltDeg}
            onChange={(e) => setSectionTiltDeg(parseFloat(e.target.value))}
            data-testid="section-tilt-slider"
            className="w-14 sm:w-16 h-1 bg-slate-700 rounded appearance-none cursor-pointer accent-cyan-400"
            title={`Tilt: ${sectionTiltDeg}°`}
          />
          <span className="text-[10px] font-mono w-6 text-right text-cyan-300">
            {sectionTiltDeg}°
          </span>
        </div>

        {/* Quick Actions: Flip, Hatch, True Shape, Reset, Close */}
        <div className="flex items-center gap-1 shrink-0">
          {/* Flip */}
          <button
            onClick={toggleSectionFlip}
            data-testid="section-flip-btn"
            title={sectionFlipped ? 'Normal flipped (-)' : 'Normal standard (+)'}
            className={`p-1.5 rounded-md transition-colors ${
              sectionFlipped
                ? 'bg-amber-600/80 text-white'
                : 'text-slate-400 hover:text-white hover:bg-slate-800'
            }`}
          >
            <RotateCw className="w-3.5 h-3.5" />
          </button>

          {/* Hatch ✓ */}
          <button
            onClick={toggleSectionHatch}
            data-testid="section-hatch-btn"
            title="Toggle 45° engineering graphics section hatch lining"
            className={`flex items-center gap-0.5 px-1.5 py-1 rounded-md text-[11px] font-medium transition-colors border ${
              sectionHatchEnabled
                ? 'bg-blue-600/90 border-blue-400 text-white shadow-xs'
                : 'bg-slate-800 border-slate-700 text-slate-400 hover:text-slate-200'
            }`}
          >
            <span>Hatch</span>
            {sectionHatchEnabled && <Check className="w-3 h-3 text-white" />}
          </button>

          {/* True shape */}
          <button
            onClick={toggleTrueShape}
            data-testid="section-true-shape-btn"
            title="Auxiliary View: Orthographic perpendicular looking straight into cut face"
            className={`flex items-center gap-1 px-1.5 py-1 rounded-md text-[11px] font-semibold transition-colors border ${
              isTrueShapeActive
                ? 'bg-emerald-600 border-emerald-400 text-white shadow-xs'
                : 'bg-slate-800 border-slate-700 text-emerald-400 hover:text-emerald-300'
            }`}
          >
            <Eye className="w-3 h-3" />
            <span className="hidden sm:inline">True</span>
          </button>

          {/* Reset */}
          <button
            onClick={resetSectionPlane}
            data-testid="section-reset-btn"
            title="Reset section plane to default Top view"
            className="p-1 text-slate-400 hover:text-white hover:bg-slate-800 rounded-md transition-colors"
          >
            <RotateCw className="w-3 h-3" />
          </button>

          {/* Toggle Advanced */}
          <button
            onClick={() => setIsAdvancedOpen(!isAdvancedOpen)}
            data-testid="section-advanced-toggle"
            title="Advanced section settings (extra planes, 3-point, BREP, clearance)"
            className={`p-1 rounded-md transition-colors ${
              isAdvancedOpen
                ? 'text-cyan-400 bg-slate-800'
                : 'text-slate-400 hover:text-white hover:bg-slate-800'
            }`}
          >
            <Sliders className="w-3.5 h-3.5" />
          </button>

          {/* Close [x] */}
          <button
            onClick={closeSectionMode}
            data-testid="section-close-btn"
            title="Close section mode (Esc)"
            className="p-1 text-slate-400 hover:text-red-400 hover:bg-slate-800 rounded-md transition-colors ml-0.5"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* ─── Collapsed Advanced Drawer (Closed by default) ──────────────────── */}
      {isAdvancedOpen && (
        <div
          data-testid="section-advanced-panel"
          className="mt-2 w-full bg-slate-900/98 backdrop-blur-md border border-slate-700/80 rounded-xl shadow-2xl p-3 text-slate-300 text-xs flex flex-col gap-2.5 max-h-[48vh] overflow-y-auto"
        >
          <div className="flex items-center justify-between pb-1.5 border-b border-slate-800">
            <span className="font-semibold text-slate-200 flex items-center gap-1.5 text-[11px]">
              <Layers className="w-3.5 h-3.5 text-cyan-400" />
              Advanced Section Tools
            </span>
            <span className="text-[10px] text-slate-500">Max 3 clipping planes</span>
          </div>

          {/* Planes 1, 2, 3 selector & enable toggles */}
          <div className="flex items-center gap-1.5">
            {sectionPlanes.map((p, idx) => (
              <button
                key={p.id}
                onClick={() => setActiveAdvPlaneIdx(idx)}
                className={`flex-1 py-1 px-2 rounded font-medium text-[11px] border transition-colors flex items-center justify-between ${
                  activeAdvPlaneIdx === idx
                    ? 'bg-blue-600/80 border-blue-400 text-white'
                    : 'bg-slate-800/80 border-slate-700 text-slate-400 hover:text-slate-200'
                }`}
              >
                <span>Plane {idx + 1}</span>
                <input
                  type="checkbox"
                  checked={p.enabled}
                  onChange={(e) => {
                    e.stopPropagation()
                    setSectionPlane(idx, { enabled: e.target.checked })
                  }}
                  className="rounded text-blue-500 focus:ring-0 ml-1 cursor-pointer"
                />
              </button>
            ))}
          </div>

          {/* Union / Intersection Mode */}
          <div className="flex items-center justify-between bg-slate-800/60 p-1.5 rounded-lg border border-slate-700/50">
            <span className="text-[11px] text-slate-400">Multiple Planes Mode:</span>
            <div className="flex items-center gap-1 bg-slate-800 rounded p-0.5">
              <button
                onClick={() => setSectionCombinedMode('union')}
                className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                  sectionCombinedMode === 'union'
                    ? 'bg-cyan-600 text-white'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                Union
              </button>
              <button
                onClick={() => setSectionCombinedMode('intersection')}
                className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                  sectionCombinedMode === 'intersection'
                    ? 'bg-cyan-600 text-white'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                Intersection
              </button>
            </div>
          </div>

          {/* Numeric Normal Input for Active Advanced Plane */}
          <div className="bg-slate-800/60 p-2 rounded-lg border border-slate-700/50 flex flex-col gap-1.5">
            <span className="text-[10px] text-slate-400 font-medium">
              Plane {activeAdvPlaneIdx + 1} Numeric Normal [nx, ny, nz]:
            </span>
            <div className="flex items-center gap-2">
              {(['X', 'Y', 'Z'] as const).map((axis, aIdx) => (
                <div key={axis} className="flex-1 flex items-center gap-1 bg-slate-900 px-1.5 py-1 rounded border border-slate-700">
                  <span className="text-[10px] text-slate-500 font-mono">{axis}:</span>
                  <input
                    type="number"
                    step={0.1}
                    value={sectionPlanes[activeAdvPlaneIdx]?.normal[aIdx] ?? 0}
                    onChange={(e) => {
                      const val = parseFloat(e.target.value) || 0
                      const curr = [...sectionPlanes[activeAdvPlaneIdx].normal] as [number, number, number]
                      curr[aIdx] = val
                      const mag = Math.hypot(...curr)
                      if (mag > 1e-4) {
                        setSectionPlane(activeAdvPlaneIdx, {
                          normal: [curr[0] / mag, curr[1] / mag, curr[2] / mag],
                        })
                      }
                    }}
                    className="w-full bg-transparent text-[11px] font-mono text-cyan-300 focus:outline-hidden"
                  />
                </div>
              ))}
            </div>
          </div>

          {/* 3-Point Plane and Removal Direction Plane */}
          <div className="grid grid-cols-2 gap-1.5">
            <button
              onClick={applyThreePoints}
              data-testid="section-3point-btn"
              className="py-1 px-2 rounded bg-slate-800 hover:bg-slate-750 text-slate-200 border border-slate-700 font-medium text-[11px] text-center"
            >
              Apply 3-Point Plane
            </button>
            <button
              onClick={handlePlaneThroughRemoval}
              data-testid="section-through-removal-btn"
              className="py-1 px-2 rounded bg-slate-800 hover:bg-slate-750 text-cyan-300 border border-slate-700 font-medium text-[11px] text-center"
            >
              Through Removal Dir
            </button>
          </div>

          {/* On-Demand Exact BREP Section & Section Clearance */}
          <div className="pt-1.5 border-t border-slate-800 flex items-center gap-2">
            <button
              onClick={handleComputeExactSection}
              disabled={isComputingSection}
              data-testid="section-brep-btn"
              className="flex-1 py-1.5 px-3 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white font-medium text-xs flex items-center justify-center gap-1.5 shadow-sm"
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>{isComputingSection ? 'Computing BREP…' : 'Exact BREP Section'}</span>
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default CompactSectionBar

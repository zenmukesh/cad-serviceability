import React, { useState } from 'react'
import {
  Scissors,
  RotateCw,
  X,
  Play,
} from 'lucide-react'
import { useAssemblyStore } from '../../store/assemblyStore'
import { getAssemblySection } from '../../api/client'
import toast from 'react-hot-toast'

interface MultiAxisSectionControlsProps {
  isOpen: boolean
  onClose: () => void
}

export const MultiAxisSectionControls: React.FC<MultiAxisSectionControlsProps> = ({
  isOpen,
  onClose,
}) => {
  const {
    currentAssembly,
    sectionPlanes,
    setSectionPlane,
    sectionCombinedMode,
    setSectionCombinedMode,
    showSectionCaps,
    setShowSectionCaps,
    activeSectionResult,
    setActiveSectionResult,
    isComputingSection,
    setIsComputingSection,
    applySectionPreset,
  } = useAssemblyStore()

  const [activePlaneIdx, setActivePlaneIdx] = useState(0)
  const [showThreePointModal, setShowThreePointModal] = useState(false)
  const [pt1, setPt1] = useState<[number, number, number]>([0, 0, 0])
  const [pt2, setPt2] = useState<[number, number, number]>([10, 0, 0])
  const [pt3, setPt3] = useState<[number, number, number]>([0, 10, 0])

  if (!isOpen) return null

  const activePlane = sectionPlanes[activePlaneIdx]

  const handleToggleEnable = () => {
    setSectionPlane(activePlaneIdx, { enabled: !activePlane.enabled })
  }

  const handleFlip = () => {
    const [nx, ny, nz] = activePlane.normal
    setSectionPlane(activePlaneIdx, {
      normal: [-nx, -ny, -nz],
      offset: -activePlane.offset,
      flipped: !activePlane.flipped,
    })
  }

  const handleNormalChange = (axisIdx: number, val: number) => {
    const nextNormal: [number, number, number] = [...activePlane.normal]
    nextNormal[axisIdx] = isNaN(val) ? 0 : val
    // Normalize
    const mag = Math.sqrt(
      nextNormal[0] ** 2 + nextNormal[1] ** 2 + nextNormal[2] ** 2
    )
    if (mag > 1e-6) {
      setSectionPlane(activePlaneIdx, {
        normal: [nextNormal[0] / mag, nextNormal[1] / mag, nextNormal[2] / mag],
      })
    }
  }

  const handleOffsetChange = (val: number) => {
    setSectionPlane(activePlaneIdx, { offset: val })
  }

  // 3-Point Plane Calculation
  const applyThreePoints = () => {
    const v1 = [pt2[0] - pt1[0], pt2[1] - pt1[1], pt2[2] - pt1[2]]
    const v2 = [pt3[0] - pt1[0], pt3[1] - pt1[1], pt3[2] - pt1[2]]

    // Cross product v1 x v2
    const nx = v1[1] * v2[2] - v1[2] * v2[1]
    const ny = v1[2] * v2[0] - v1[0] * v2[2]
    const nz = v1[0] * v2[1] - v1[1] * v2[0]
    const mag = Math.sqrt(nx * nx + ny * ny + nz * nz)

    if (mag < 1e-6) {
      toast.error('Points are collinear; cannot define a unique plane.')
      return
    }

    const norm: [number, number, number] = [nx / mag, ny / mag, nz / mag]
    setSectionPlane(activePlaneIdx, {
      enabled: true,
      point: pt1,
      normal: norm,
      offset: 0,
      label: '3-Point Plane',
    })
    setShowThreePointModal(false)
    toast.success('3-Point section plane applied')
  }

  // Exact BREP section call to backend
  const handleComputeExactSection = async () => {
    if (!currentAssembly) return
    setIsComputingSection(true)
    try {
      const res = await getAssemblySection(currentAssembly.id, {
        point: activePlane.point,
        normal: activePlane.normal,
      })
      setActiveSectionResult(res)
      toast.success(
        `Exact section computed: ${res.component_sections.length} parts cut (${res.total_cut_area_mm2.toFixed(1)} mm²)`
      )
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to compute exact section')
    } finally {
      setIsComputingSection(false)
    }
  }

  return (
    <div className="absolute right-4 top-16 w-84 bg-slate-900/95 backdrop-blur-md border border-slate-700/80 rounded-xl shadow-2xl p-4 z-40 text-slate-200 text-xs flex flex-col gap-3 max-h-[85vh] overflow-y-auto">
      {/* Header */}
      <div className="flex items-center justify-between pb-2 border-b border-slate-800">
        <div className="flex items-center gap-1.5 font-semibold text-slate-100">
          <Scissors className="w-4 h-4 text-cyan-400" />
          <span>Multi-Axis Sectioning (D1-D4)</span>
        </div>
        <button
          onClick={onClose}
          className="text-slate-400 hover:text-white p-0.5 rounded transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* 3 Planes Tabs */}
      <div className="flex items-center gap-1 p-1 bg-slate-800/80 rounded-lg border border-slate-700/50">
        {sectionPlanes.map((p, idx) => (
          <button
            key={p.id}
            onClick={() => setActivePlaneIdx(idx)}
            className={`flex-1 py-1 px-2 rounded font-medium text-[11px] transition-colors flex items-center justify-center gap-1 ${
              activePlaneIdx === idx
                ? 'bg-blue-600 text-white shadow-sm'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/40'
            }`}
          >
            <span>Plane {idx + 1}</span>
            {p.enabled && (
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block" />
            )}
          </button>
        ))}
      </div>

      {/* Active Plane Controls */}
      <div className="space-y-3 bg-slate-800/40 p-2.5 rounded-lg border border-slate-700/40">
        <div className="flex items-center justify-between">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={activePlane.enabled}
              onChange={handleToggleEnable}
              className="rounded bg-slate-700 border-slate-600 text-blue-500 focus:ring-0"
            />
            <span className="font-semibold text-slate-200">
              Enable Plane {activePlaneIdx + 1}
            </span>
          </label>
          <button
            onClick={handleFlip}
            className="flex items-center gap-1 px-2 py-0.5 rounded bg-slate-700 hover:bg-slate-600 text-[10px] text-slate-300 font-medium transition-colors"
            title="Invert plane normal direction"
          >
            <RotateCw className="w-3 h-3 text-cyan-400" />
            <span>Flip</span>
          </button>
        </div>

        {/* Normal Vector Inputs */}
        <div className="space-y-1">
          <div className="flex justify-between text-[11px] text-slate-400">
            <span>Normal Vector (unit):</span>
            <span className="font-mono text-cyan-400">
              [{activePlane.normal.map((v) => v.toFixed(2)).join(', ')}]
            </span>
          </div>
          <div className="grid grid-cols-3 gap-1.5">
            {(['X', 'Y', 'Z'] as const).map((axis, i) => (
              <div key={axis} className="flex items-center bg-slate-900/80 rounded border border-slate-700 px-1.5 py-0.5">
                <span className="text-[10px] font-mono font-bold text-slate-400 mr-1">{axis}:</span>
                <input
                  type="number"
                  step="0.05"
                  value={parseFloat(activePlane.normal[i].toFixed(3))}
                  onChange={(e) => handleNormalChange(i, parseFloat(e.target.value))}
                  className="w-full bg-transparent font-mono text-[11px] text-slate-200 outline-none"
                />
              </div>
            ))}
          </div>
        </div>

        {/* Offset Slider & Numeric Input */}
        <div className="space-y-1">
          <div className="flex justify-between text-[11px] text-slate-400">
            <span>Offset Distance:</span>
            <span className="font-mono text-slate-200">{activePlane.offset.toFixed(1)} mm</span>
          </div>
          <input
            type="range"
            min={-150}
            max={150}
            step={0.5}
            value={activePlane.offset}
            onChange={(e) => handleOffsetChange(parseFloat(e.target.value))}
            className="w-full h-1.5 bg-slate-700 rounded appearance-none cursor-pointer accent-blue-500"
          />
        </div>
      </div>

      {/* Plane Presets */}
      <div className="space-y-1.5">
        <span className="text-[11px] font-semibold text-slate-400">Presets:</span>
        <div className="grid grid-cols-3 gap-1">
          <button
            onClick={() => applySectionPreset('XY')}
            className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 border border-slate-700 text-[10px] font-medium text-slate-300"
          >
            XY (Z)
          </button>
          <button
            onClick={() => applySectionPreset('XZ')}
            className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 border border-slate-700 text-[10px] font-medium text-slate-300"
          >
            XZ (Y)
          </button>
          <button
            onClick={() => applySectionPreset('YZ')}
            className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 border border-slate-700 text-[10px] font-medium text-slate-300"
          >
            YZ (X)
          </button>
          <button
            onClick={() => applySectionPreset('45_XZ')}
            className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 border border-slate-700 text-[10px] font-medium text-slate-300"
          >
            45° XZ
          </button>
          <button
            onClick={() => applySectionPreset('45_YZ')}
            className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 border border-slate-700 text-[10px] font-medium text-slate-300"
          >
            45° YZ
          </button>
          <button
            onClick={() => applySectionPreset('compound_45')}
            className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 border border-slate-700 text-[10px] font-medium text-slate-300"
          >
            Compound 45°
          </button>
        </div>

        <div className="grid grid-cols-2 gap-1 mt-1">
          <button
            onClick={() => applySectionPreset('removal_vector')}
            className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 border border-slate-700 text-[10px] font-medium text-cyan-300 truncate"
            title="Orient plane normal containing or along the component's removal vector"
          >
            Removal Vector Plane
          </button>
          <button
            onClick={() => setShowThreePointModal(true)}
            className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 border border-slate-700 text-[10px] font-medium text-amber-300 truncate"
          >
            3-Point Plane...
          </button>
        </div>
      </div>

      {/* Multi-Plane Combination & Stencil Caps */}
      <div className="pt-2 border-t border-slate-800 space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-slate-400">Combined Mode:</span>
          <div className="flex rounded bg-slate-800 p-0.5 border border-slate-700">
            <button
              onClick={() => setSectionCombinedMode('union')}
              className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                sectionCombinedMode === 'union'
                  ? 'bg-blue-600 text-white'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Union
            </button>
            <button
              onClick={() => setSectionCombinedMode('intersection')}
              className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                sectionCombinedMode === 'intersection'
                  ? 'bg-blue-600 text-white'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Intersection
            </button>
          </div>
        </div>

        <div className="flex items-center justify-between">
          <span className="text-[11px] text-slate-400">Solid Cut Cap Faces:</span>
          <button
            onClick={() => setShowSectionCaps(!showSectionCaps)}
            className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${
              showSectionCaps
                ? 'bg-emerald-950/80 text-emerald-300 border border-emerald-500/50'
                : 'bg-slate-800 text-slate-400 border border-slate-700'
            }`}
          >
            {showSectionCaps ? 'Solid Caps Active' : 'Hollow'}
          </button>
        </div>
      </div>

      {/* Backend Exact Analytical Section Button */}
      <div className="pt-2 border-t border-slate-800">
        <button
          onClick={handleComputeExactSection}
          disabled={isComputingSection || !currentAssembly}
          className="w-full flex items-center justify-center gap-1.5 py-1.5 rounded-lg font-medium text-xs bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-white shadow-md transition-colors"
        >
          {isComputingSection ? (
            <span>Computing Exact BREP Cut...</span>
          ) : (
            <>
              <Play className="w-3.5 h-3.5 fill-current" />
              <span>Compute Exact BREP Section</span>
            </>
          )}
        </button>

        {activeSectionResult && (
          <div className="mt-2 p-2 bg-slate-950/80 rounded border border-cyan-500/30 space-y-1 font-mono text-[10px]">
            <div className="flex justify-between text-cyan-300">
              <span>Cut Parts:</span>
              <span className="font-bold">{activeSectionResult.component_sections.length}</span>
            </div>
            <div className="flex justify-between text-slate-300">
              <span>Cut Area:</span>
              <span>{activeSectionResult.total_cut_area_mm2.toFixed(2)} mm²</span>
            </div>
            {activeSectionResult.clearance && (
              <div className="mt-1 pt-1 border-t border-slate-800 flex justify-between text-amber-300">
                <span>Section Clearance:</span>
                <span className="font-bold">
                  {activeSectionResult.clearance.clearance_mm.toFixed(3)} mm
                </span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Clear / Reset All Planes */}
      <button
        onClick={() => applySectionPreset('clear')}
        className="w-full py-1 text-center text-[10px] text-slate-400 hover:text-rose-400 transition-colors"
      >
        Clear All Section Planes
      </button>

      {/* 3-Point Modal */}
      {showThreePointModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-xl p-4 w-96 space-y-3 shadow-2xl">
            <div className="flex justify-between items-center pb-2 border-b border-slate-800">
              <span className="font-semibold text-slate-100 text-xs">Define Plane Through 3 Points</span>
              <button
                onClick={() => setShowThreePointModal(false)}
                className="text-slate-400 hover:text-white"
              >
                ✕
              </button>
            </div>
            <p className="text-[11px] text-slate-400">
              Specify three non-collinear 3D points in CAD assembly space to define the cutting plane.
            </p>
            {(['P1', 'P2', 'P3'] as const).map((pName, pIdx) => {
              const currentPt = pIdx === 0 ? pt1 : pIdx === 1 ? pt2 : pt3
              const setFn = pIdx === 0 ? setPt1 : pIdx === 1 ? setPt2 : setPt3
              return (
                <div key={pName} className="flex items-center gap-1.5 text-xs">
                  <span className="font-mono font-bold text-slate-300 w-6">{pName}:</span>
                  {(['X', 'Y', 'Z'] as const).map((ax, aIdx) => (
                    <input
                      key={ax}
                      type="number"
                      step="1"
                      value={currentPt[aIdx]}
                      onChange={(e) => {
                        const copy: [number, number, number] = [...currentPt]
                        copy[aIdx] = parseFloat(e.target.value) || 0
                        setFn(copy)
                      }}
                      className="w-full bg-slate-800 border border-slate-700 rounded px-1.5 py-0.5 text-slate-200 font-mono text-[11px]"
                      placeholder={ax}
                    />
                  ))}
                </div>
              )
            })}
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setShowThreePointModal(false)}
                className="px-3 py-1 rounded bg-slate-800 text-slate-300 hover:bg-slate-700 text-xs"
              >
                Cancel
              </button>
              <button
                onClick={applyThreePoints}
                className="px-3 py-1 rounded bg-blue-600 text-white hover:bg-blue-500 text-xs font-medium"
              >
                Apply Plane
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

import React, { useState } from 'react'
import {
  Maximize2,
  X,
  Grid3X3,
  Eye,
  EyeOff,
  Sparkles,
  Scissors,
  Split,
  Ghost,
  RotateCcw,
} from 'lucide-react'
import { useAssemblyStore } from '../../store/assemblyStore'

interface ViewerControlsProps {
  onFitView: () => void
  onToggleGrid: () => void
  showGrid: boolean
}

interface ToolButtonProps {
  icon: React.ReactNode
  label: string
  onClick: () => void
  active?: boolean
  disabled?: boolean
  title?: string
}

function ToolButton({ icon, label, onClick, active, disabled, title }: ToolButtonProps) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title || label}
      className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs font-medium transition-colors
        ${disabled ? 'opacity-40 cursor-not-allowed bg-slate-800 text-slate-500' : ''}
        ${
          active
            ? 'bg-blue-600 text-white shadow-sm shadow-blue-500/20'
            : !disabled
            ? 'bg-slate-700/80 text-slate-300 hover:bg-slate-700 hover:text-white'
            : ''
        }`}
    >
      {icon}
      <span className="hidden md:inline">{label}</span>
    </button>
  )
}

export default function ViewerControls({ onFitView, onToggleGrid, showGrid }: ViewerControlsProps) {
  const {
    selectComponent,
    setIsolated,
    clearHidden,
    isolatedComponentId,
    selectedComponentId,
    isXRayMode,
    toggleXRayMode,
    transparentComponentIds,
    toggleTransparentComponent,
    explodeFactor,
    setExplodeFactor,
    sectionPlaneAxis,
    setSectionPlaneAxis,
    sectionPlaneOffset,
    setSectionPlaneOffset,
    activeClearanceLine,
    activeAccessVector,
    obstructingComponentIds,
    clearVisualFindings,
  } = useAssemblyStore()

  const [showSectionOptions, setShowSectionOptions] = useState(false)

  const handleIsolate = () => {
    if (selectedComponentId != null) {
      setIsolated(isolatedComponentId === selectedComponentId ? null : selectedComponentId)
    }
  }

  const handleShowAll = () => {
    setIsolated(null)
    clearHidden()
  }

  const isSelectedTransparent =
    selectedComponentId != null && transparentComponentIds.has(selectedComponentId)

  const hasVisualFindings =
    obstructingComponentIds.size > 0 || activeClearanceLine != null || activeAccessVector != null

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 bg-slate-900 border-b border-slate-800 z-10">
      {/* Primary Navigation & Visibility Controls */}
      <div className="flex items-center gap-1.5 flex-wrap">
        <ToolButton
          icon={<Maximize2 className="w-3.5 h-3.5" />}
          label="Fit View"
          onClick={onFitView}
        />
        <ToolButton
          icon={<X className="w-3.5 h-3.5 text-slate-400" />}
          label="Reset"
          title="Clear component selection"
          onClick={() => selectComponent(null)}
          disabled={selectedComponentId == null}
        />
        <ToolButton
          icon={<Grid3X3 className="w-3.5 h-3.5" />}
          label="Grid"
          onClick={onToggleGrid}
          active={showGrid}
        />
        <div className="w-px h-4 bg-slate-700 mx-1" />
        <ToolButton
          icon={<Eye className="w-3.5 h-3.5" />}
          label="Isolate"
          onClick={handleIsolate}
          active={isolatedComponentId != null}
          disabled={selectedComponentId == null}
        />
        <ToolButton
          icon={<EyeOff className="w-3.5 h-3.5" />}
          label="Show All"
          onClick={handleShowAll}
        />
      </div>

      {/* Milestone 2 Phase 1: Inspection & Visualization Tools */}
      <div className="flex items-center gap-2 flex-wrap">
        {/* Exploded View Slider */}
        <div className="flex items-center gap-1.5 bg-slate-800/80 rounded px-2 py-1 border border-slate-700/60">
          <Split className="w-3.5 h-3.5 text-blue-400 shrink-0" />
          <span className="text-[11px] text-slate-300 font-medium">Explode:</span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.02}
            value={explodeFactor}
            onChange={(e) => setExplodeFactor(parseFloat(e.target.value))}
            className="w-16 h-1.5 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-blue-500"
            title={`Exploded displacement: ${Math.round(explodeFactor * 100)}%`}
          />
          <span className="text-[10px] text-slate-400 font-mono w-6 text-right">
            {Math.round(explodeFactor * 100)}%
          </span>
          {explodeFactor > 0 && (
            <button
              onClick={() => setExplodeFactor(0)}
              className="text-[10px] text-slate-400 hover:text-white px-1"
              title="Reset exploded view"
            >
              ✕
            </button>
          )}
        </div>

        {/* X-Ray Mode */}
        <ToolButton
          icon={<Ghost className="w-3.5 h-3.5" />}
          label="X-Ray Covers"
          title="Make housings and covers translucent to inspect interior gears and shafts"
          onClick={toggleXRayMode}
          active={isXRayMode}
        />

        {/* Transparent Selected */}
        <ToolButton
          icon={<Sparkles className="w-3.5 h-3.5" />}
          label="Translucent"
          title="Toggle translucency for currently selected component"
          onClick={() => selectedComponentId != null && toggleTransparentComponent(selectedComponentId)}
          active={isSelectedTransparent}
          disabled={selectedComponentId == null}
        />

        {/* Section View / Clipping Plane */}
        <div className="relative">
          <ToolButton
            icon={<Scissors className="w-3.5 h-3.5" />}
            label={`Section${sectionPlaneAxis !== 'off' ? ` (${sectionPlaneAxis})` : ''}`}
            title="Inspect internal geometry with cross-section clipping plane"
            onClick={() => setShowSectionOptions((o) => !o)}
            active={sectionPlaneAxis !== 'off'}
          />

          {showSectionOptions && (
            <div className="absolute right-0 top-full mt-1 w-64 bg-slate-900 border border-slate-700 rounded-lg p-3 shadow-2xl z-30 space-y-2">
              <div className="flex items-center justify-between pb-1 border-b border-slate-800">
                <span className="text-xs font-semibold text-slate-200">Section Clipping Plane</span>
                <button
                  onClick={() => setShowSectionOptions(false)}
                  className="text-slate-400 hover:text-white text-xs"
                >
                  ✕
                </button>
              </div>

              <div className="flex gap-1 flex-wrap">
                {(['off', '+X', '-X', '+Y', '-Y', '+Z', '-Z'] as const).map((axis) => (
                  <button
                    key={axis}
                    onClick={() => {
                      setSectionPlaneAxis(axis)
                      if (axis === 'off') setSectionPlaneOffset(0)
                    }}
                    className={`px-2 py-1 text-[11px] rounded font-mono font-medium transition-colors ${
                      sectionPlaneAxis === axis
                        ? 'bg-blue-600 text-white'
                        : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                    }`}
                  >
                    {axis}
                  </button>
                ))}
              </div>

              {sectionPlaneAxis !== 'off' && (
                <div className="pt-2">
                  <div className="flex justify-between text-[11px] text-slate-400 mb-1">
                    <span>Cut Offset:</span>
                    <span className="font-mono text-slate-200">{sectionPlaneOffset.toFixed(1)} mm</span>
                  </div>
                  <input
                    type="range"
                    min={-150}
                    max={150}
                    step={1}
                    value={sectionPlaneOffset}
                    onChange={(e) => setSectionPlaneOffset(parseFloat(e.target.value))}
                    className="w-full h-1.5 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-blue-500"
                  />
                </div>
              )}
            </div>
          )}
        </div>

        {/* Clear Visual Findings */}
        {hasVisualFindings && (
          <button
            onClick={clearVisualFindings}
            className="flex items-center gap-1 px-2.5 py-1.5 rounded text-xs font-medium bg-red-950/70 border border-red-500/40 text-red-300 hover:bg-red-900/80 transition-colors"
            title="Clear active 3D obstruction/clearance findings"
          >
            <RotateCcw className="w-3 h-3 text-red-400" />
            <span>Clear Highlights</span>
          </button>
        )}
      </div>
    </div>
  )
}

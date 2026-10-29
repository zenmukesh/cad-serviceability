import React, { useState } from 'react'
import {
  MousePointer,
  Rotate3d,
  Hand,
  ZoomIn,
  Eye,
  Maximize2,
  Settings,
  Sliders,
  X,
} from 'lucide-react'
import {
  useAssemblyStore,
  NavigationTool,
} from '../../store/assemblyStore'

interface NavigationBarProps {
  onFitAll: () => void
}

export const NavigationBar: React.FC<NavigationBarProps> = ({ onFitAll }) => {
  const {
    activeNavTool,
    setActiveNavTool,
    navSettings,
    setNavSettings,
    triggerFitSelection,
    selectedComponentId,
  } = useAssemblyStore()

  const [showSettings, setShowSettings] = useState(false)

  const tools: { id: NavigationTool; label: string; icon: React.ReactNode; tooltip: string }[] = [
    {
      id: 'select',
      label: 'Select',
      icon: <MousePointer className="w-4 h-4" />,
      tooltip: 'Normal selection (Fusion 360 mode: MMB Pan, Shift+MMB Orbit)',
    },
    {
      id: 'orbit',
      label: 'Orbit',
      icon: <Rotate3d className="w-4 h-4" />,
      tooltip: 'Left-drag free tumble orbit (or Shift+MMB in Fusion preset)',
    },
    {
      id: 'pan',
      label: 'Pan',
      icon: <Hand className="w-4 h-4" />,
      tooltip: 'Left-drag pan across the scene (or MMB in Fusion preset)',
    },
    {
      id: 'zoom',
      label: 'Zoom',
      icon: <ZoomIn className="w-4 h-4" />,
      tooltip: 'Left-drag or wheel to zoom toward cursor',
    },
    {
      id: 'lookAt',
      label: 'Look At',
      icon: <Eye className="w-4 h-4" />,
      tooltip: 'Click any planar face to orient camera perpendicular to it',
    },
  ]

  return (
    <div className="absolute bottom-4 left-4 z-30 flex items-center gap-1 bg-slate-900/90 backdrop-blur-md border border-slate-700/80 rounded-xl p-1 shadow-2xl">
      {tools.map((t) => (
        <button
          key={t.id}
          onClick={() => setActiveNavTool(t.id)}
          className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
            activeNavTool === t.id
              ? 'bg-blue-600 text-white shadow-md'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
          }`}
          title={t.tooltip}
          data-testid={`nav-tool-${t.id}`}
        >
          {t.icon}
          <span className="hidden sm:inline">{t.label}</span>
        </button>
      ))}

      <div className="w-px h-5 bg-slate-800 mx-1" />

      {/* Fit Button */}
      <button
        onClick={selectedComponentId != null ? triggerFitSelection : onFitAll}
        className="flex items-center gap-1 px-2 py-1.5 rounded-lg text-xs font-medium text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 transition-colors"
        title={selectedComponentId != null ? 'Fit Selected (F)' : 'Fit All (F)'}
        data-testid="nav-tool-fit"
      >
        <Maximize2 className="w-4 h-4" />
        <span className="hidden sm:inline">Fit</span>
      </button>

      {/* Navigation Settings Button */}
      <div className="relative">
        <button
          onClick={() => setShowSettings((o) => !o)}
          className={`p-1.5 rounded-lg text-xs transition-colors ${
            showSettings
              ? 'bg-slate-800 text-cyan-400'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
          }`}
          title="Navigation & Camera Settings"
          data-testid="nav-settings-btn"
        >
          <Settings className="w-4 h-4" />
        </button>

        {showSettings && (
          <div
            className="absolute bottom-full left-0 mb-2 w-72 bg-slate-900 border border-slate-700 rounded-xl p-3 shadow-2xl z-40 text-xs text-slate-200 space-y-3"
            data-testid="nav-settings-menu"
          >
            <div className="flex items-center justify-between pb-1.5 border-b border-slate-800">
              <span className="font-semibold text-slate-100 flex items-center gap-1.5">
                <Sliders className="w-3.5 h-3.5 text-cyan-400" />
                <span>Camera & Navigation Settings</span>
              </span>
              <button
                onClick={() => setShowSettings(false)}
                className="text-slate-400 hover:text-white"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>

            {/* Presets */}
            <div className="space-y-1.5">
              <span className="text-[11px] font-semibold text-slate-400 block">Preset:</span>
              <div className="grid grid-cols-2 gap-1.5">
                <button
                  onClick={() => setNavSettings({ preset: 'fusion' })}
                  className={`px-2 py-1.5 rounded-lg text-left text-[11px] border transition-colors ${
                    navSettings.preset === 'fusion'
                      ? 'bg-blue-600/30 border-blue-500 text-white font-medium'
                      : 'bg-slate-800/80 border-slate-700 text-slate-400 hover:text-slate-200'
                  }`}
                  data-testid="preset-fusion-btn"
                >
                  <div className="font-bold">Fusion 360</div>
                  <div className="text-[9px] text-slate-400 leading-tight">MMB Pan, Shift+MMB Orbit</div>
                </button>
                <button
                  onClick={() => setNavSettings({ preset: 'standard' })}
                  className={`px-2 py-1.5 rounded-lg text-left text-[11px] border transition-colors ${
                    navSettings.preset === 'standard'
                      ? 'bg-blue-600/30 border-blue-500 text-white font-medium'
                      : 'bg-slate-800/80 border-slate-700 text-slate-400 hover:text-slate-200'
                  }`}
                  data-testid="preset-standard-btn"
                >
                  <div className="font-bold">Left-Drag Orbit</div>
                  <div className="text-[9px] text-slate-400 leading-tight">LMB Orbit, MMB Pan</div>
                </button>
              </div>
            </div>

            {/* Orbit Speed Slider */}
            <div className="space-y-1">
              <div className="flex justify-between text-[11px] text-slate-400">
                <span>Orbit Speed:</span>
                <span className="font-mono text-cyan-400">{navSettings.orbitSpeed.toFixed(1)}x</span>
              </div>
              <input
                type="range"
                min={0.5}
                max={2.0}
                step={0.1}
                value={navSettings.orbitSpeed}
                onChange={(e) => setNavSettings({ orbitSpeed: parseFloat(e.target.value) })}
                className="w-full h-1.5 bg-slate-700 rounded appearance-none cursor-pointer accent-blue-500"
              />
            </div>

            {/* Constrained (Z-up) Toggle */}
            <label className="flex items-center justify-between cursor-pointer pt-1 border-t border-slate-800">
              <div>
                <span className="text-[11px] font-medium text-slate-200 block">Constrained (Z-Up)</span>
                <span className="text-[9px] text-slate-400">Turntable orbit; off = free tumble</span>
              </div>
              <input
                type="checkbox"
                checked={navSettings.constrainedZUp}
                onChange={(e) => setNavSettings({ constrainedZUp: e.target.checked })}
                className="rounded bg-slate-700 border-slate-600 text-blue-500 focus:ring-0"
                data-testid="toggle-constrained-zup"
              />
            </label>

            {/* Projection Mode */}
            <div className="pt-1 border-t border-slate-800 flex items-center justify-between">
              <span className="text-[11px] text-slate-400">Projection:</span>
              <div className="flex rounded bg-slate-800 p-0.5 border border-slate-700">
                <button
                  onClick={() => setNavSettings({ projection: 'perspective' })}
                  className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                    navSettings.projection === 'perspective'
                      ? 'bg-blue-600 text-white'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  Perspective
                </button>
                <button
                  onClick={() => setNavSettings({ projection: 'orthographic' })}
                  className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                    navSettings.projection === 'orthographic'
                      ? 'bg-blue-600 text-white'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  Orthographic
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
export default NavigationBar

import { useEffect, useState } from 'react'
import { Toaster } from 'react-hot-toast'
import {
  Layers,
  Upload,
  ChevronDown,
  Box,
  CheckCircle2,
  AlertCircle,
  Clock,
  RefreshCw,
  Wrench,
  FileText,
} from 'lucide-react'
import { listAssemblies, getAssemblyComponents } from './api/client'
import { useAssemblyStore } from './store/assemblyStore'
import AssemblyViewer from './components/viewer/AssemblyViewer'
import ViewerControls from './components/viewer/ViewerControls'
import ComponentTree from './components/panels/ComponentTree'
import PropertiesPanel from './components/panels/PropertiesPanel'
import ServiceabilityPanel from './components/panels/ServiceabilityPanel'
import UploadZone from './components/upload/UploadZone'
import { ErrorBanner } from './components/common/ErrorBanner'
import { ErrorBoundary } from './components/common/ErrorBoundary'
import type { Assembly } from './types/assembly'

export default function App() {
  const {
    assemblies,
    setAssemblies,
    currentAssembly,
    setCurrentAssembly,
    components,
    setComponents,
    selectedComponentId,
    serviceabilityReport,
    error,
    setError,
    setLoading,
  } = useAssemblyStore()

  const [showUploadModal, setShowUploadModal] = useState(false)
  const [showGrid, setShowGrid] = useState(true)
  const [fitViewTrigger, setFitViewTrigger] = useState(0)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [sidePanelTab, setSidePanelTab] = useState<'serviceability' | 'properties'>('serviceability')

  // Fetch initial assemblies list
  const loadAssemblies = async () => {
    try {
      setIsRefreshing(true)
      const data = await listAssemblies()
      setAssemblies(data)
      if (data.length > 0 && !currentAssembly) {
        // Select the most recent one
        selectAssembly(data[0])
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to load assemblies')
    } finally {
      setIsRefreshing(false)
    }
  }

  useEffect(() => {
    loadAssemblies()
  }, [])

  const selectAssembly = async (assembly: Assembly) => {
    try {
      setLoading(true)
      setCurrentAssembly(assembly)
      setError(null)

      if (assembly.status === 'ready') {
        const compRes = await getAssemblyComponents(assembly.id)
        setComponents(compRes.components)
      } else {
        setComponents([])
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to load components')
    } finally {
      setLoading(false)
    }
  }

  const handleFitView = () => {
    setFitViewTrigger((prev) => prev + 1)
  }

  const selectedComp = components.find((c) => c.id === selectedComponentId)

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-slate-950 text-slate-100 font-sans">
      <Toaster position="bottom-right" />

      {/* Top Header Bar */}
      <header className="h-14 bg-slate-900 border-b border-slate-800 flex items-center justify-between px-4 shrink-0 z-20">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded bg-blue-600 flex items-center justify-center shadow-lg shadow-blue-500/20">
            <Box className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-sm font-semibold tracking-wide flex items-center gap-2">
              CAD Serviceability Assessment
              <span className="text-[10px] uppercase font-bold px-1.5 py-0.5 rounded bg-blue-900/60 text-blue-400 border border-blue-700/50">
                Milestone 2
              </span>
            </h1>
            <p className="text-[11px] text-slate-400">
              Obstruction Detection • Clearance Measurement • Disassembly DAG • Explainable Scoring
            </p>
          </div>
        </div>

        {/* Assembly Selector / Actions */}
        <div className="flex items-center gap-3">
          {assemblies.length > 0 && (
            <div className="relative flex items-center">
              <select
                value={currentAssembly?.id ?? ''}
                onChange={(e) => {
                  const found = assemblies.find((a) => a.id === Number(e.target.value))
                  if (found) selectAssembly(found)
                }}
                className="bg-slate-800 text-xs text-slate-200 border border-slate-700 rounded-md py-1.5 pl-3 pr-8 appearance-none focus:outline-none focus:border-blue-500"
              >
                {assemblies.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.filename} ({a.component_count ?? 0} parts)
                  </option>
                ))}
              </select>
              <ChevronDown className="w-4 h-4 text-slate-400 absolute right-2 pointer-events-none" />
            </div>
          )}

          <button
            onClick={loadAssemblies}
            className="p-1.5 rounded text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
            title="Refresh assemblies"
          >
            <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
          </button>

          <button
            onClick={() => setShowUploadModal(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium transition-colors shadow-sm shadow-blue-500/20"
          >
            <Upload className="w-3.5 h-3.5" />
            <span>Upload STEP</span>
          </button>
        </div>
      </header>

      {/* Main Workspace Layout */}
      <div className="flex flex-1 overflow-hidden relative">
        {/* Left Side: Component Tree */}
        <aside className="w-72 bg-slate-900 border-r border-slate-800 flex flex-col shrink-0">
          <div className="p-3 border-b border-slate-800 flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              <Layers className="w-4 h-4 text-slate-500" />
              Components ({components.length})
            </span>
          </div>
          <div className="flex-1 overflow-y-auto">
            <ComponentTree />
          </div>
        </aside>

        {/* Center: 3D CAD Viewer */}
        <main className="flex-1 flex flex-col min-w-0 bg-slate-950 relative">
          {error && (
            <div className="absolute top-2 left-4 right-4 z-30">
              <ErrorBanner message={error} onDismiss={() => setError(null)} />
            </div>
          )}

          <ViewerControls
            onFitView={handleFitView}
            onToggleGrid={() => setShowGrid((g) => !g)}
            showGrid={showGrid}
          />

          <div className="flex-1 relative overflow-hidden">
            {components.length > 0 ? (
              <ErrorBoundary fallbackTitle="3D CAD Assembly Viewer Error">
                <AssemblyViewer
                  showGrid={showGrid}
                  onToggleGrid={() => setShowGrid((g) => !g)}
                  fitViewTrigger={fitViewTrigger}
                />
              </ErrorBoundary>
            ) : (
              <div className="w-full h-full flex flex-col items-center justify-center p-8 text-center bg-slate-950">
                <div className="max-w-md w-full">
                  <UploadZone />
                </div>
              </div>
            )}
          </div>
        </main>

        {/* Right Side: Engineering Analysis & Properties Panel */}
        <aside className="w-96 bg-slate-900 border-l border-slate-800 flex flex-col shrink-0">
          {/* Side Panel Tabs Header */}
          <div className="flex items-center border-b border-slate-800 bg-slate-950/60 p-1">
            <button
              onClick={() => setSidePanelTab('serviceability')}
              className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 text-xs font-medium rounded transition-colors ${
                sidePanelTab === 'serviceability'
                  ? 'bg-slate-800 text-white shadow-xs'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Wrench className="w-3.5 h-3.5 text-blue-400" />
              <span>Serviceability</span>
              {serviceabilityReport && (
                <span className="text-[10px] font-mono font-bold px-1.5 py-0.2 rounded bg-blue-900/60 text-blue-300">
                  {Math.round(serviceabilityReport.overall_score)}
                </span>
              )}
            </button>

            <button
              onClick={() => setSidePanelTab('properties')}
              className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 text-xs font-medium rounded transition-colors ${
                sidePanelTab === 'properties'
                  ? 'bg-slate-800 text-white shadow-xs'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <FileText className="w-3.5 h-3.5 text-slate-400" />
              <span>CAD Properties</span>
            </button>
          </div>

          <div className="flex-1 overflow-hidden flex flex-col">
            {sidePanelTab === 'serviceability' ? (
              <ServiceabilityPanel />
            ) : (
              <div className="flex-1 overflow-y-auto p-4">
                <PropertiesPanel />
              </div>
            )}
          </div>
        </aside>
      </div>

      {/* Bottom Status Bar */}
      <footer className="h-7 bg-slate-900 border-t border-slate-800 flex items-center justify-between px-4 text-[11px] text-slate-400 shrink-0">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1.5">
            <span className="text-slate-500">Selected:</span>
            <span className="text-slate-200 font-mono">
              {selectedComp ? selectedComp.display_name : 'None'}
            </span>
          </div>

          {selectedComp && selectedComp.volume_mm3 != null && (
            <div className="flex items-center gap-1.5">
              <span className="text-slate-500">Volume:</span>
              <span className="text-slate-300 font-mono">
                {selectedComp.volume_mm3.toLocaleString(undefined, { maximumFractionDigits: 1 })}{' '}
                mm³
              </span>
            </div>
          )}

          {serviceabilityReport && (
            <div className="flex items-center gap-1.5">
              <span className="text-slate-500">Assembly Score:</span>
              <span className="text-emerald-400 font-mono font-bold">
                {serviceabilityReport.overall_score} / 100 ({serviceabilityReport.overall_rating})
              </span>
            </div>
          )}
        </div>

        <div className="flex items-center gap-3">
          {currentAssembly && (
            <div className="flex items-center gap-1.5">
              <span className="text-slate-500">Assembly Status:</span>
              <span
                className={`flex items-center gap-1 font-medium ${
                  currentAssembly.status === 'ready'
                    ? 'text-emerald-400'
                    : currentAssembly.status === 'error'
                    ? 'text-red-400'
                    : 'text-amber-400'
                }`}
              >
                {currentAssembly.status === 'ready' && <CheckCircle2 className="w-3.5 h-3.5" />}
                {currentAssembly.status === 'error' && <AlertCircle className="w-3.5 h-3.5" />}
                {currentAssembly.status === 'processing' && (
                  <Clock className="w-3.5 h-3.5 animate-spin" />
                )}
                {currentAssembly.status}
              </span>
            </div>
          )}
          <span className="text-slate-600">|</span>
          <span className="text-slate-500 font-mono">OpenCASCADE / CadQuery Kernel</span>
        </div>
      </footer>

      {/* Upload Modal */}
      {showUploadModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-xs p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-lg max-w-lg w-full p-6 shadow-2xl relative">
            <div className="flex items-center justify-between pb-3 mb-4 border-b border-slate-800">
              <h3 className="text-sm font-semibold text-slate-100 flex items-center gap-2">
                <Upload className="w-4 h-4 text-blue-400" />
                Import CAD STEP Assembly
              </h3>
              <button
                onClick={() => setShowUploadModal(false)}
                className="text-slate-400 hover:text-slate-200 text-sm"
              >
                ✕
              </button>
            </div>
            <UploadZone />
            <div className="mt-4 flex justify-end">
              <button
                onClick={() => setShowUploadModal(false)}
                className="px-4 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs rounded transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

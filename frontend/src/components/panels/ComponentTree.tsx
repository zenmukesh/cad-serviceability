import { useState, useMemo } from 'react'
import { Eye, EyeOff, Box, Layers, Focus } from 'lucide-react'
import { useAssemblyStore } from '../../store/assemblyStore'
import type { Component } from '../../types/assembly'

function formatDim(v: number | null | undefined): string {
  if (v == null) return '—'
  return `${v.toFixed(2)} mm`
}

interface RowTooltipProps {
  component: Component
}

function BboxTooltip({ component }: RowTooltipProps) {
  const bb = component.bounding_box
  return (
    <div className="text-xs space-y-1">
      <div className="font-semibold text-slate-200">{component.display_name}</div>
      <div className="text-[11px] text-slate-400 font-mono">ID: {component.cad_entity_id}</div>
      {component.volume_mm3 != null && component.volume_mm3 > 0 && (
        <div className="text-[11px] text-blue-400">
          Vol: {component.volume_mm3.toLocaleString(undefined, { maximumFractionDigits: 1 })} mm³
        </div>
      )}
      {bb && (
        <div className="mt-1 pt-1 border-t border-slate-700/60">
          <div className="text-[10px] text-slate-400 font-semibold mb-0.5">Bounding Box:</div>
          <div className="grid grid-cols-3 gap-x-2 text-[11px] text-slate-300 font-mono">
            <span>X: {formatDim(bb.size_x)}</span>
            <span>Y: {formatDim(bb.size_y)}</span>
            <span>Z: {formatDim(bb.size_z)}</span>
          </div>
        </div>
      )}
    </div>
  )
}

interface ComponentRowProps {
  component: Component
  isSelected: boolean
  isHidden: boolean
  isIsolated: boolean
  onSelect: () => void
  onToggleHidden: () => void
  onToggleIsolate: () => void
}

function ComponentRow({
  component,
  isSelected,
  isHidden,
  isIsolated,
  onSelect,
  onToggleHidden,
  onToggleIsolate,
}: ComponentRowProps) {
  const [showTooltip, setShowTooltip] = useState(false)

  const isAssembly = component.component_type === 'assembly' || !component.is_leaf
  const isInferred = component.component_type?.includes('inferred')

  const typeColor = isAssembly
    ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30'
    : isInferred
    ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
    : 'bg-blue-500/20 text-blue-300 border border-blue-500/30'

  const typeLabel = isAssembly
    ? 'assembly'
    : isInferred
    ? 'inferred'
    : 'part'

  const Icon = isAssembly ? Layers : Box

  return (
    <div
      className={`group relative flex items-center gap-2 px-3 py-2 cursor-pointer select-none transition-colors border-l-2
        ${isSelected ? 'bg-blue-600/25 border-blue-500 shadow-xs' : 'border-transparent hover:bg-slate-800/60'}
        ${isHidden ? 'opacity-40' : ''}
        ${isIsolated ? 'bg-indigo-950/40 border-l-2 border-indigo-400' : ''}`}
      style={{ paddingLeft: `${12 + component.depth * 14}px` }}
      onClick={onSelect}
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
    >
      <Icon
        className={`w-4 h-4 shrink-0 ${
          isSelected ? 'text-blue-400' : isAssembly ? 'text-purple-400' : 'text-slate-400'
        }`}
      />

      <span
        className={`flex-1 text-xs truncate min-w-0 ${
          isSelected ? 'font-medium text-white' : isAssembly ? 'font-medium text-slate-200' : 'text-slate-300'
        }`}
      >
        {component.display_name}
      </span>

      <span className={`text-[9px] font-semibold tracking-wider uppercase px-1.5 py-0.5 rounded shrink-0 ${typeColor}`}>
        {typeLabel}
      </span>

      {/* Action buttons on row */}
      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          className={`p-1 rounded hover:bg-slate-700 transition-colors ${isIsolated ? 'text-indigo-400' : 'text-slate-400'}`}
          onClick={(e) => {
            e.stopPropagation()
            onToggleIsolate()
          }}
          title={isIsolated ? 'Cancel isolation' : 'Isolate component'}
        >
          <Focus className="w-3.5 h-3.5" />
        </button>
        <button
          className="p-1 rounded hover:bg-slate-700 transition-colors"
          onClick={(e) => {
            e.stopPropagation()
            onToggleHidden()
          }}
          title={isHidden ? 'Show in viewer' : 'Hide in viewer'}
        >
          {isHidden ? (
            <EyeOff className="w-3.5 h-3.5 text-slate-500" />
          ) : (
            <Eye className="w-3.5 h-3.5 text-slate-400" />
          )}
        </button>
      </div>

      {showTooltip && (
        <div className="absolute left-full top-0 z-50 ml-2 bg-slate-900 border border-slate-700 rounded-md p-2.5 shadow-2xl min-w-[190px] pointer-events-none">
          <BboxTooltip component={component} />
        </div>
      )}
    </div>
  )
}

export default function ComponentTree() {
  const {
    components,
    selectedComponentId,
    hiddenComponentIds,
    isolatedComponentId,
    selectComponent,
    toggleHidden,
    setIsolated,
  } = useAssemblyStore()
  const [filter, setFilter] = useState('')

  const filtered = useMemo(() => {
    if (!filter.trim()) return components
    const q = filter.toLowerCase()
    return components.filter(
      (c) =>
        c.display_name.toLowerCase().includes(q) ||
        c.name.toLowerCase().includes(q) ||
        (c.user_label ?? '').toLowerCase().includes(q) ||
        c.cad_entity_id.toLowerCase().includes(q)
    )
  }, [components, filter])

  if (components.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center p-4">
        <p className="text-slate-500 text-sm text-center">No components loaded</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-slate-900">
      <div className="px-3 py-2 border-b border-slate-800">
        <input
          type="text"
          placeholder="Filter components or assembly parts…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="w-full bg-slate-950 border border-slate-700 rounded px-2.5 py-1 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
        />
      </div>

      <div className="flex-1 overflow-y-auto divide-y divide-slate-800/40">
        {filtered.map((component) => (
          <ComponentRow
            key={component.id}
            component={component}
            isSelected={component.id === selectedComponentId}
            isHidden={hiddenComponentIds.has(component.id)}
            isIsolated={isolatedComponentId === component.id}
            onSelect={() => selectComponent(component.id)}
            onToggleHidden={() => toggleHidden(component.id)}
            onToggleIsolate={() =>
              setIsolated(isolatedComponentId === component.id ? null : component.id)
            }
          />
        ))}
        {filtered.length === 0 && (
          <div className="p-4 text-center text-slate-500 text-xs">No matching components found</div>
        )}
      </div>
    </div>
  )
}

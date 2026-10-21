import { useState, useEffect } from 'react'
import { useAssemblyStore } from '../../store/assemblyStore'
import { updateComponentLabel } from '../../api/client'
import toast from 'react-hot-toast'

function Row({ label, value }: { label: string; value: string | number | null | undefined }) {
  const display = value == null ? '—' : String(value)
  return (
    <div className="flex justify-between items-start gap-2 py-1.5 border-b border-slate-700/50 last:border-0">
      <span className="text-slate-500 text-xs shrink-0">{label}</span>
      <span className="text-slate-200 text-xs text-right font-mono break-all">{display}</span>
    </div>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h4 className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mt-4 mb-1">
      {children}
    </h4>
  )
}

export default function PropertiesPanel() {
  const { components, selectedComponentId } = useAssemblyStore()
  const component = components.find((c) => c.id === selectedComponentId) ?? null

  const [editingLabel, setEditingLabel] = useState('')
  const [isSaving, setIsSaving] = useState(false)

  useEffect(() => {
    setEditingLabel(component?.user_label ?? component?.display_name ?? '')
  }, [component])

  const handleLabelBlur = async () => {
    if (!component) return
    const trimmed = editingLabel.trim()
    if (trimmed === (component.user_label ?? '')) return
    setIsSaving(true)
    try {
      await updateComponentLabel(component.id, trimmed)
      // Update local store optimistically
      useAssemblyStore.getState().setComponents(
        useAssemblyStore.getState().components.map((c) =>
          c.id === component.id ? { ...c, user_label: trimmed, display_name: trimmed || c.name } : c
        )
      )
      toast.success('Label updated')
    } catch {
      toast.error('Failed to save label')
      setEditingLabel(component.user_label ?? component.display_name)
    } finally {
      setIsSaving(false)
    }
  }

  if (!component) {
    return (
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="text-center">
          <div className="w-10 h-10 rounded-full bg-slate-700 flex items-center justify-center mx-auto mb-3">
            <span className="text-slate-500 text-lg">?</span>
          </div>
          <p className="text-slate-500 text-sm">Select a component</p>
          <p className="text-slate-600 text-xs mt-1">to view its properties</p>
        </div>
      </div>
    )
  }

  const bb = component.bounding_box

  return (
    <div className="flex-1 overflow-y-auto p-4">
      {/* Label editor */}
      <div className="mb-4">
        <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1">
          Label
        </label>
        <div className="relative">
          <input
            type="text"
            value={editingLabel}
            onChange={(e) => setEditingLabel(e.target.value)}
            onBlur={handleLabelBlur}
            onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
            className="w-full bg-slate-900 border border-slate-600 rounded px-3 py-1.5 text-sm text-white focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/30"
          />
          {isSaving && (
            <div className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
          )}
        </div>
      </div>

      <SectionTitle>Identity</SectionTitle>
      <Row label="CAD Entity ID" value={component.cad_entity_id} />
      <Row label="Name" value={component.name} />
      <Row label="Type" value={component.component_type} />
      <Row label="Depth" value={component.depth} />
      <Row label="Is Leaf" value={component.is_leaf ? 'Yes' : 'No'} />

      <SectionTitle>Physical Properties</SectionTitle>
      <Row
        label="Volume"
        value={component.volume_mm3 != null ? `${component.volume_mm3.toFixed(3)} mm³` : null}
      />
      <Row
        label="Surface Area"
        value={component.surface_area_mm2 != null ? `${component.surface_area_mm2.toFixed(3)} mm²` : null}
      />

      {bb && (
        <>
          <SectionTitle>Bounding Box</SectionTitle>
          <Row label="Size X" value={`${bb.size_x.toFixed(3)} mm`} />
          <Row label="Size Y" value={`${bb.size_y.toFixed(3)} mm`} />
          <Row label="Size Z" value={`${bb.size_z.toFixed(3)} mm`} />
          <Row label="X min / max" value={`${bb.xmin.toFixed(2)} / ${bb.xmax.toFixed(2)}`} />
          <Row label="Y min / max" value={`${bb.ymin.toFixed(2)} / ${bb.ymax.toFixed(2)}`} />
          <Row label="Z min / max" value={`${bb.zmin.toFixed(2)} / ${bb.zmax.toFixed(2)}`} />
        </>
      )}
    </div>
  )
}

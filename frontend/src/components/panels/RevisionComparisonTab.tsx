import { useState, useEffect } from 'react'
import { GitCompare, Loader2, ArrowRight, PlusCircle, MinusCircle, AlertCircle, CheckCircle2 } from 'lucide-react'
import { useAssemblyStore } from '../../store/assemblyStore'
import { listAssemblies, compareAssemblies } from '../../api/client'
import type { Assembly, AssemblyComparisonResponse } from '../../types/assembly'

export default function RevisionComparisonTab() {
  const { currentAssembly } = useAssemblyStore()
  const [assemblies, setAssemblies] = useState<Assembly[]>([])
  const [targetAssemblyId, setTargetAssemblyId] = useState<number | null>(null)
  const [comparison, setComparison] = useState<AssemblyComparisonResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [filter, setFilter] = useState<'all' | 'added' | 'removed' | 'modified' | 'unchanged'>('all')

  useEffect(() => {
    listAssemblies()
      .then((data) => {
        setAssemblies(data)
        const other = data.find((a) => a.id !== currentAssembly?.id && a.status === 'ready')
        if (other) {
          setTargetAssemblyId(other.id)
        }
      })
      .catch((err) => console.error('Failed to load assemblies for comparison:', err))
  }, [currentAssembly?.id])

  useEffect(() => {
    if (!currentAssembly || !targetAssemblyId) {
      setComparison(null)
      return
    }
    setLoading(true)
    compareAssemblies(currentAssembly.id, targetAssemblyId)
      .then((res) => setComparison(res))
      .catch((err) => {
        console.error('Comparison error:', err)
        setComparison(null)
      })
      .finally(() => setLoading(false))
  }, [currentAssembly?.id, targetAssemblyId])

  if (!currentAssembly) {
    return <div className="p-4 text-sm text-slate-400">No assembly selected.</div>
  }

  const otherAssemblies = assemblies.filter((a) => a.id !== currentAssembly.id)

  const filteredChanges = comparison?.changes.filter((c) => {
    if (filter === 'all') return true
    return c.change_type === filter
  }) || []

  return (
    <div className="flex flex-col h-full overflow-y-auto p-4 space-y-4">
      {/* Target Selector */}
      <div className="bg-slate-800/80 rounded-lg p-3 border border-slate-700/60">
        <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2 flex items-center gap-1.5">
          <GitCompare className="w-3.5 h-3.5 text-blue-400" />
          Compare Revision Against
        </label>
        {otherAssemblies.length === 0 ? (
          <p className="text-xs text-slate-400">
            No other assemblies found in database. Upload a second revision to compare.
          </p>
        ) : (
          <select
            value={targetAssemblyId ?? ''}
            onChange={(e) => setTargetAssemblyId(Number(e.target.value))}
            className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-blue-500"
          >
            {otherAssemblies.map((a) => (
              <option key={a.id} value={a.id}>
                #{a.id} - {a.filename} ({a.component_count} parts)
              </option>
            ))}
          </select>
        )}
      </div>

      {loading && (
        <div className="flex items-center justify-center p-8 text-slate-400 gap-2">
          <Loader2 className="w-5 h-5 animate-spin text-blue-400" />
          <span className="text-xs">Computing revision diff...</span>
        </div>
      )}

      {!loading && comparison && (
        <>
          {/* Score & Summary Card */}
          <div className="grid grid-cols-2 gap-2">
            <div className="bg-slate-800/60 border border-slate-700/60 rounded p-2.5">
              <div className="text-[10px] text-slate-400 uppercase">Serviceability Score</div>
              <div className="flex items-center gap-2 mt-1">
                <span className="text-sm font-semibold text-slate-200">
                  {comparison.score_a !== null ? `${comparison.score_a}/100` : 'N/A'}
                </span>
                <ArrowRight className="w-3 h-3 text-slate-500" />
                <span className="text-sm font-semibold text-slate-200">
                  {comparison.score_b !== null ? `${comparison.score_b}/100` : 'N/A'}
                </span>
                {comparison.score_delta !== null && (
                  <span
                    className={`text-xs font-bold px-1.5 py-0.5 rounded ${
                      comparison.score_delta > 0
                        ? 'bg-emerald-950/80 text-emerald-400 border border-emerald-800'
                        : comparison.score_delta < 0
                        ? 'bg-rose-950/80 text-rose-400 border border-rose-800'
                        : 'bg-slate-800 text-slate-300'
                    }`}
                  >
                    {comparison.score_delta > 0 ? `+${comparison.score_delta}` : comparison.score_delta}
                  </span>
                )}
              </div>
            </div>

            <div className="bg-slate-800/60 border border-slate-700/60 rounded p-2.5">
              <div className="text-[10px] text-slate-400 uppercase">Parts Count</div>
              <div className="flex items-center gap-2 mt-1">
                <span className="text-sm font-semibold text-slate-200">{comparison.total_components_a}</span>
                <ArrowRight className="w-3 h-3 text-slate-500" />
                <span className="text-sm font-semibold text-slate-200">{comparison.total_components_b}</span>
                <span className="text-xs text-slate-400">
                  ({comparison.total_components_b - comparison.total_components_a >= 0 ? '+' : ''}
                  {comparison.total_components_b - comparison.total_components_a})
                </span>
              </div>
            </div>
          </div>

          {/* Counts Badges & Filter */}
          <div className="flex items-center gap-1.5 flex-wrap">
            <button
              onClick={() => setFilter('all')}
              className={`px-2 py-1 text-[11px] rounded transition-colors ${
                filter === 'all'
                  ? 'bg-blue-600 text-white font-medium'
                  : 'bg-slate-800 text-slate-400 hover:text-slate-200'
              }`}
            >
              All ({comparison.changes.length})
            </button>
            <button
              onClick={() => setFilter('added')}
              className={`flex items-center gap-1 px-2 py-1 text-[11px] rounded transition-colors ${
                filter === 'added'
                  ? 'bg-emerald-700 text-white font-medium'
                  : 'bg-slate-800 text-emerald-400 hover:bg-slate-700'
              }`}
            >
              <PlusCircle className="w-3 h-3" />+{comparison.added_count}
            </button>
            <button
              onClick={() => setFilter('removed')}
              className={`flex items-center gap-1 px-2 py-1 text-[11px] rounded transition-colors ${
                filter === 'removed'
                  ? 'bg-rose-700 text-white font-medium'
                  : 'bg-slate-800 text-rose-400 hover:bg-slate-700'
              }`}
            >
              <MinusCircle className="w-3 h-3" />-{comparison.removed_count}
            </button>
            <button
              onClick={() => setFilter('modified')}
              className={`flex items-center gap-1 px-2 py-1 text-[11px] rounded transition-colors ${
                filter === 'modified'
                  ? 'bg-amber-700 text-white font-medium'
                  : 'bg-slate-800 text-amber-400 hover:bg-slate-700'
              }`}
            >
              <AlertCircle className="w-3 h-3" />~{comparison.modified_count}
            </button>
            <button
              onClick={() => setFilter('unchanged')}
              className={`flex items-center gap-1 px-2 py-1 text-[11px] rounded transition-colors ${
                filter === 'unchanged'
                  ? 'bg-slate-600 text-white font-medium'
                  : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
              }`}
            >
              <CheckCircle2 className="w-3 h-3" />={comparison.unchanged_count}
            </button>
          </div>

          {/* Diff Table */}
          <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
            <div className="max-h-80 overflow-y-auto">
              <table className="w-full text-left border-collapse text-[11px]">
                <thead className="bg-slate-950/80 sticky top-0 border-b border-slate-800 text-slate-400 uppercase text-[10px]">
                  <tr>
                    <th className="p-2">Component</th>
                    <th className="p-2">Status</th>
                    <th className="p-2 text-right">Vol Δ (mm³)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {filteredChanges.length === 0 ? (
                    <tr>
                      <td colSpan={3} className="p-3 text-center text-slate-500">
                        No components match filter.
                      </td>
                    </tr>
                  ) : (
                    filteredChanges.map((c, idx) => (
                      <tr key={idx} className="hover:bg-slate-800/40">
                        <td className="p-2 font-medium text-slate-200 truncate max-w-[140px]" title={c.name}>
                          {c.name}
                        </td>
                        <td className="p-2">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase ${
                              c.change_type === 'added'
                                ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                                : c.change_type === 'removed'
                                ? 'bg-rose-950 text-rose-400 border border-rose-800'
                                : c.change_type === 'modified'
                                ? 'bg-amber-950 text-amber-400 border border-amber-800'
                                : 'bg-slate-800 text-slate-400'
                            }`}
                          >
                            {c.change_type}
                          </span>
                        </td>
                        <td className="p-2 text-right font-mono text-slate-300">
                          {c.volume_delta_mm3 !== null
                            ? (c.volume_delta_mm3 > 0 ? `+${c.volume_delta_mm3}` : `${c.volume_delta_mm3}`)
                            : '-'}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

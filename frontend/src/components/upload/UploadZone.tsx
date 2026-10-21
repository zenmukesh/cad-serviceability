import React, { useCallback, useState } from 'react'
import { Upload, FileBox, Loader2, AlertCircle } from 'lucide-react'
import { uploadStep, pollAssemblyStatus, getAssemblyComponents } from '../../api/client'
import { useAssemblyStore } from '../../store/assemblyStore'
import type { Assembly } from '../../types/assembly'

const ACCEPTED_EXTENSIONS = ['.step', '.stp']

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function UploadZone() {
  const [isDragging, setIsDragging] = useState(false)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [uploadStatus, setUploadStatus] = useState<
    'idle' | 'uploading' | 'processing' | 'done' | 'error'
  >('idle')
  const [statusMessage, setStatusMessage] = useState('')
  const [errorMessage, setErrorMessage] = useState('')

  const { setCurrentAssembly, setComponents, setAssemblies, assemblies, setLoading } =
    useAssemblyStore()

  const processFile = useCallback(
    async (file: File) => {
      const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
      if (!ACCEPTED_EXTENSIONS.includes(ext)) {
        setErrorMessage(`Invalid file type. Please upload a .step or .stp file.`)
        return
      }

      setSelectedFile(file)
      setErrorMessage('')
      setUploadStatus('uploading')
      setStatusMessage('Uploading file…')

      try {
        const uploadRes = await uploadStep(file)
        setUploadStatus('processing')
        setStatusMessage('Processing assembly…')

        const finalAssembly = await pollAssemblyStatus(
          uploadRes.assembly_id,
          (assembly: Assembly) => {
            setStatusMessage(`Status: ${assembly.status}`)
          }
        )

        if (finalAssembly.status === 'error') {
          throw new Error(finalAssembly.error_message ?? 'Processing failed')
        }

        const componentsRes = await getAssemblyComponents(finalAssembly.id)
        setCurrentAssembly(finalAssembly)
        setComponents(componentsRes.components)
        setAssemblies([...assemblies.filter((a) => a.id !== finalAssembly.id), finalAssembly])
        setLoading(false)
        setUploadStatus('done')
        setStatusMessage('Assembly ready')
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Upload failed'
        setErrorMessage(msg)
        setUploadStatus('error')
        setStatusMessage('')
      }
    },
    [assemblies, setAssemblies, setComponents, setCurrentAssembly, setLoading]
  )

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault()
      setIsDragging(false)
      const file = e.dataTransfer.files[0]
      if (file) processFile(file)
    },
    [processFile]
  )

  const handleFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (file) processFile(file)
    },
    [processFile]
  )

  const isProcessing = uploadStatus === 'uploading' || uploadStatus === 'processing'

  return (
    <div className="flex flex-col items-center justify-center w-full h-full gap-6 p-8">
      <div className="text-center">
        <h2 className="text-2xl font-semibold text-white mb-1">CAD Serviceability Assessment</h2>
        <p className="text-slate-400 text-sm">Upload a STEP file to begin assembly analysis</p>
      </div>

      <div
        className={`relative w-full max-w-xl border-2 border-dashed rounded-xl p-12 flex flex-col items-center gap-4 transition-colors cursor-pointer
          ${isDragging ? 'border-blue-400 bg-blue-500/10' : 'border-slate-600 bg-slate-800/50 hover:border-slate-500 hover:bg-slate-800'}
          ${isProcessing ? 'pointer-events-none opacity-70' : ''}`}
        onDragEnter={(e) => { e.preventDefault(); setIsDragging(true) }}
        onDragOver={(e) => { e.preventDefault(); setIsDragging(true) }}
        onDragLeave={(e) => { e.preventDefault(); setIsDragging(false) }}
        onDrop={handleDrop}
        onClick={() => !isProcessing && document.getElementById('file-input')?.click()}
      >
        <input
          id="file-input"
          type="file"
          accept=".step,.stp"
          className="hidden"
          onChange={handleFileInput}
        />

        {isProcessing ? (
          <Loader2 className="w-12 h-12 text-blue-400 animate-spin" />
        ) : (
          <div className="p-4 bg-slate-700 rounded-full">
            <Upload className="w-10 h-10 text-blue-400" />
          </div>
        )}

        {selectedFile && !isProcessing ? (
          <div className="flex items-center gap-3 bg-slate-700/60 rounded-lg px-4 py-2">
            <FileBox className="w-5 h-5 text-blue-400 shrink-0" />
            <div className="min-w-0">
              <p className="text-white text-sm font-medium truncate">{selectedFile.name}</p>
              <p className="text-slate-400 text-xs">{formatFileSize(selectedFile.size)}</p>
            </div>
          </div>
        ) : isProcessing && selectedFile ? (
          <div className="text-center">
            <p className="text-white font-medium">{selectedFile.name}</p>
            <p className="text-blue-400 text-sm mt-1">{statusMessage}</p>
          </div>
        ) : (
          <div className="text-center">
            <p className="text-white font-medium">Drop STEP file here</p>
            <p className="text-slate-400 text-sm mt-1">or click to browse</p>
            <p className="text-slate-500 text-xs mt-2">Supports .step, .stp</p>
          </div>
        )}

        {uploadStatus === 'done' && (
          <div className="flex items-center gap-2 text-green-400 text-sm">
            <span className="w-2 h-2 rounded-full bg-green-400 inline-block" />
            {statusMessage}
          </div>
        )}
      </div>

      {errorMessage && (
        <div className="w-full max-w-xl flex items-start gap-3 bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3">
          <AlertCircle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <p className="text-red-300 text-sm">{errorMessage}</p>
          </div>
          <button
            onClick={() => setErrorMessage('')}
            className="text-red-400 hover:text-red-300 text-lg leading-none shrink-0"
          >
            ×
          </button>
        </div>
      )}
    </div>
  )
}

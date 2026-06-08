import { useState, useRef, useCallback, useEffect } from 'react'
import { X, CheckCircle2, AlertCircle, Loader2, CloudUpload, Trash2 } from 'lucide-react'
import type { UploadJob, UploadStage } from '../types'
import * as api from '../api/client'

interface Props {
  onClose: () => void
  onContractAdded: (contractId: string, fileName: string) => void
}

const STAGES: { key: UploadStage; label: string }[] = [
  { key: 'uploading',     label: 'Uploading' },
  { key: 'parsing',      label: 'Reading document' },
  { key: 'embedding',    label: 'Processing content' },
  { key: 'indexing',     label: 'Preparing for search' },
  { key: 'extracting',   label: 'Extracting knowledge graph' },
  { key: 'graph_writing', label: 'Writing to graph DB' },
  { key: 'done',         label: 'Ready' },
]

const STAGE_ORDER: UploadStage[] = [
  'uploading', 'parsing', 'embedding', 'indexing',
  'extracting', 'graph_writing', 'done',
]

// Map backend stage strings to UploadStage type
function toUploadStage(backendStage: string): UploadStage {
  const map: Record<string, UploadStage> = {
    uploading:     'uploading',
    parsing:       'parsing',
    embedding:     'embedding',
    indexing:      'indexing',
    extracting:    'extracting',
    graph_writing: 'graph_writing',
    done:          'done',
    error:         'error',
  }
  return map[backendStage] ?? 'uploading'
}

function stageIndex(stage: UploadStage) {
  return STAGE_ORDER.indexOf(stage)
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1048576).toFixed(1)} MB`
}

function sanitizeId(name: string) {
  return name.replace(/\.[^.]+$/, '').replace(/[^a-zA-Z0-9_-]/g, '_').slice(0, 64)
}

// ─── Job row ──────────────────────────────────────────────────────────────────

function UploadJobRow({ job }: { job: UploadJob }) {
  const isDone   = job.stage === 'done'
  const isError  = job.stage === 'error'
  const isActive = !isDone && !isError

  const currentLabel = STAGES.find(s => s.key === job.stage)?.label ?? ''

  return (
    <div className="bg-ey-surface border border-ey-border rounded p-4">
      <div className="flex items-center gap-3 mb-3">
        <div className={`w-9 h-9 rounded flex items-center justify-center flex-shrink-0 ${
          isDone ? 'bg-emerald-500/15' : isError ? 'bg-red-500/15' : 'bg-ey-card'
        }`}>
          {isDone    ? <CheckCircle2 size={18} className="text-emerald-400" />
           : isError ? <AlertCircle  size={18} className="text-red-400" />
           :           <Loader2      size={18} className="text-ey-yellow animate-spin" />}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-white truncate">{job.fileName}</p>
          <p className="text-xs text-ey-muted">
            {job.fileSize}
            {isActive && <span className="ml-2 text-ey-yellow">{currentLabel}…</span>}
            {isDone   && <span className="ml-2 text-emerald-400">Ready to query</span>}
            {isError  && <span className="ml-2 text-red-400">Failed</span>}
          </p>
        </div>
      </div>

      {/* Progress bar */}
      {!isError && (
        <div>
          <div className="h-1 bg-ey-border rounded-full overflow-hidden mb-2">
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                isDone ? 'bg-emerald-400' : 'bg-ey-yellow'
              }`}
              style={{ width: `${job.progress}%` }}
            />
          </div>
          {/* Step dots */}
          <div className="flex items-center gap-1">
            {STAGES.filter(s => s.key !== 'idle').map((stage, i) => {
              const completed = isDone || stageIndex(job.stage) > i
              const active    = !isDone && job.stage === stage.key
              return (
                <div key={stage.key} className="flex items-center gap-1">
                  <div className={`w-1.5 h-1.5 rounded-full transition-colors ${
                    completed ? 'bg-emerald-400'
                    : active   ? 'bg-ey-yellow'
                    :            'bg-ey-border'
                  }`} />
                  {i < STAGES.length - 2 && (
                    <div className={`w-4 h-px ${completed ? 'bg-emerald-400/50' : 'bg-ey-border'}`} />
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {isError && (
        <p className="text-xs text-red-400">{job.error ?? 'Upload failed. Please try again.'}</p>
      )}
    </div>
  )
}

// ─── Drop zone ────────────────────────────────────────────────────────────────

function DropZone({ onFiles, disabled }: { onFiles: (files: File[]) => void; disabled?: boolean }) {
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    if (disabled) return
    const files = Array.from(e.dataTransfer.files).filter(
      f => f.type === 'application/pdf' || f.name.endsWith('.txt') || f.name.endsWith('.md')
    )
    if (files.length) onFiles(files)
  }, [onFiles, disabled])

  return (
    <div
      onDragEnter={e => { e.preventDefault(); if (!disabled) setDragging(true) }}
      onDragOver={e => { e.preventDefault(); if (!disabled) setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => !disabled && inputRef.current?.click()}
      className={`border-2 border-dashed rounded-lg p-10 text-center transition-all ${
        disabled
          ? 'border-ey-border opacity-50 cursor-not-allowed'
          : dragging
            ? 'border-ey-yellow bg-ey-yellow/5 cursor-pointer'
            : 'border-ey-border hover:border-ey-yellow/50 hover:bg-ey-surface/50 cursor-pointer'
      }`}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.txt,.md"
        multiple
        className="hidden"
        disabled={disabled}
        onChange={e => {
          const files = Array.from(e.target.files ?? [])
          if (files.length) onFiles(files)
          e.target.value = ''
        }}
      />
      <CloudUpload size={36} className={`mx-auto mb-3 ${dragging ? 'text-ey-yellow' : 'text-ey-muted'}`} />
      <p className="text-sm font-medium text-white mb-1">
        {dragging ? 'Drop to upload' : 'Drag & drop contracts here'}
      </p>
      <p className="text-xs text-ey-muted mb-4">or click to browse — multiple files supported</p>
      <p className="text-[11px] text-ey-muted">PDF, TXT, or MD · Max 50 MB per file</p>
    </div>
  )
}

// ─── Main panel ───────────────────────────────────────────────────────────────

export default function UploadPanel({ onClose, onContractAdded }: Props) {
  const [jobs, setJobs]         = useState<UploadJob[]>([])
  const [uploading, setUploading] = useState(false)
  const [apiError, setApiError] = useState<string | null>(null)

  // Map jobId → polling interval handle
  const pollers = useRef<Map<string, ReturnType<typeof setInterval>>>(new Map())

  const updateJob = (id: string, patch: Partial<UploadJob>) =>
    setJobs(prev => prev.map(j => j.id === id ? { ...j, ...patch } : j))

  // Start polling status for a job every 2.5s until done or failed
  const startPolling = useCallback((jobId: string, contractId: string, fileName: string) => {
    const handle = setInterval(async () => {
      try {
        const status = await api.getIngestStatus(jobId)
        const stage = toUploadStage(status.stage)

        updateJob(jobId, {
          stage,
          progress: status.progress,
          error: status.error ?? undefined,
        })

        if (status.status === 'done') {
          clearInterval(handle)
          pollers.current.delete(jobId)
          onContractAdded(contractId, fileName)
        } else if (status.status === 'failed') {
          clearInterval(handle)
          pollers.current.delete(jobId)
          updateJob(jobId, { stage: 'error', error: status.error ?? 'Ingestion failed.' })
        }
      } catch (err) {
        clearInterval(handle)
        pollers.current.delete(jobId)
        updateJob(jobId, { stage: 'error', error: 'Could not reach API.' })
      }
    }, 2500)

    pollers.current.set(jobId, handle)
  }, [onContractAdded])

  // Cleanup all pollers on unmount
  useEffect(() => {
    return () => {
      pollers.current.forEach(h => clearInterval(h))
    }
  }, [])

  const handleFiles = useCallback(async (files: File[]) => {
    setApiError(null)
    setUploading(true)

    // Create optimistic job rows immediately
    const localJobs: UploadJob[] = files.map(file => ({
      id: `tmp_${Date.now()}_${Math.random().toString(36).slice(2)}`,
      fileName: file.name,
      fileSize: formatBytes(file.size),
      stage: 'uploading' as UploadStage,
      progress: 2,
    }))
    setJobs(prev => [...prev, ...localJobs])

    try {
      const serverJobs = await api.uploadFiles(files)

      // Replace temporary job rows with real server job IDs
      setJobs(prev => {
        const updated = [...prev]
        serverJobs.forEach((sj, i) => {
          const tmpId = localJobs[i]?.id
          if (!tmpId) return
          const idx = updated.findIndex(j => j.id === tmpId)
          if (idx === -1) return
          updated[idx] = {
            ...updated[idx],
            id: sj.jobId,
            stage: toUploadStage(sj.stage),
            progress: sj.progress,
          }
        })
        return updated
      })

      // Begin polling for each job
      serverJobs.forEach(sj => {
        startPolling(sj.jobId, sj.contractId, sj.fileName)
      })
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Upload failed.'
      setApiError(msg)
      // Mark temporary jobs as errors
      setJobs(prev => prev.map(j =>
        localJobs.some(lj => lj.id === j.id)
          ? { ...j, stage: 'error' as UploadStage, error: msg }
          : j
      ))
    } finally {
      setUploading(false)
    }
  }, [startPolling])

  const removeJob = (id: string) => {
    // Stop polling if still active
    const handle = pollers.current.get(id)
    if (handle) {
      clearInterval(handle)
      pollers.current.delete(id)
    }
    setJobs(prev => prev.filter(j => j.id !== id))
  }

  const activeCount = jobs.filter(j => j.stage !== 'done' && j.stage !== 'error').length
  const doneCount   = jobs.filter(j => j.stage === 'done').length

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40 animate-fade-in"
        onClick={activeCount > 0 ? undefined : onClose}
      />

      {/* Panel */}
      <div className="fixed right-0 top-0 bottom-0 w-[460px] bg-ey-dark border-l border-ey-border
                      z-50 flex flex-col shadow-2xl animate-slide-in">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-5 border-b border-ey-border">
          <div>
            <h2 className="text-base font-semibold text-white">Upload Contracts</h2>
            <p className="text-xs text-ey-muted mt-0.5">
              Files are uploaded to Azure Blob and indexed asynchronously
            </p>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded
                       hover:bg-ey-surface transition-colors text-ey-muted hover:text-white"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          {apiError && (
            <div className="bg-red-900/40 border border-red-700/50 rounded p-3 text-xs text-red-300 flex items-start gap-2">
              <AlertCircle size={14} className="flex-shrink-0 mt-0.5" />
              <span>{apiError}</span>
            </div>
          )}

          <DropZone onFiles={handleFiles} disabled={uploading} />

          {jobs.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-3">
                <p className="text-xs font-medium text-ey-muted uppercase tracking-wider">
                  {activeCount > 0 && doneCount > 0
                    ? `${activeCount} processing · ${doneCount} ready`
                    : activeCount > 0
                      ? `Processing ${activeCount} file${activeCount !== 1 ? 's' : ''}…`
                      : `${doneCount} file${doneCount !== 1 ? 's' : ''} ready`}
                </p>
                {doneCount > 0 && (
                  <button
                    onClick={() => setJobs(prev => prev.filter(j => j.stage !== 'done'))}
                    className="text-[11px] text-ey-muted hover:text-ey-light transition-colors
                               flex items-center gap-1"
                  >
                    <Trash2 size={10} />
                    Clear done
                  </button>
                )}
              </div>
              <div className="space-y-3">
                {jobs.map(job => (
                  <div key={job.id} className="relative group">
                    <UploadJobRow job={job} />
                    {(job.stage === 'done' || job.stage === 'error') && (
                      <button
                        onClick={() => removeJob(job.id)}
                        className="absolute top-3 right-3 w-6 h-6 flex items-center justify-center
                                   rounded bg-ey-card hover:bg-ey-card-hover transition-colors
                                   text-ey-muted hover:text-white opacity-0 group-hover:opacity-100"
                      >
                        <X size={12} />
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-ey-border">
          <button
            onClick={onClose}
            className="w-full py-2.5 rounded bg-ey-surface border border-ey-border
                       text-sm text-ey-light hover:border-ey-yellow hover:text-ey-yellow transition-colors"
          >
            {activeCount > 0 ? 'Running in background — Close' : 'Done'}
          </button>
        </div>
      </div>
    </>
  )
}
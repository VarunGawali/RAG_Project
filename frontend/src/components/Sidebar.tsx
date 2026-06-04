import { useState } from 'react'
import {
  Plus, MessageSquare, FileText, ChevronDown, ChevronRight,
  Upload, CheckCircle2, PanelLeftClose, PanelLeftOpen, X,
} from 'lucide-react'
import type { ChatSession, Contract } from '../types'

interface Props {
  sessions: ChatSession[]
  activeSessionId: string | null
  contracts: Contract[]
  contractFilter: string | null
  collapsed: boolean
  mobileOpen: boolean
  onToggleCollapse: () => void
  onCloseMobile: () => void
  onNewChat: () => void
  onSelectSession: (id: string) => void
  onSelectContract: (id: string | null) => void
  onOpenUpload: () => void
}

function formatDate(iso: string) {
  const d = new Date(iso)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  if (diff < 86400000) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  if (diff < 604800000) return d.toLocaleDateString([], { weekday: 'short' })
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

// ─── Tooltip wrapper for collapsed icon-rail ──────────────────────────────────
function Tip({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="relative group/tip">
      {children}
      <div className="pointer-events-none absolute left-full top-1/2 -translate-y-1/2 ml-3 z-50
                      px-2 py-1 rounded bg-ey-card border border-ey-border text-xs text-white
                      whitespace-nowrap opacity-0 group-hover/tip:opacity-100 transition-opacity delay-150">
        {label}
      </div>
    </div>
  )
}

export default function Sidebar({
  sessions, activeSessionId, contracts, contractFilter,
  collapsed, mobileOpen,
  onToggleCollapse, onCloseMobile,
  onNewChat, onSelectSession, onSelectContract, onOpenUpload,
}: Props) {
  const [contractsExpanded, setContractsExpanded] = useState(true)

  return (
    <>
      {/* ── Desktop sidebar with smooth collapse animation ── */}
      <aside
        className={`
          hidden md:flex flex-col bg-ey-dark border-r border-ey-border flex-shrink-0 h-full
          transition-[width] duration-300 ease-in-out overflow-hidden
          ${collapsed ? 'w-16' : 'w-72'}
        `}
      >
        {collapsed ? (
          /* Icon rail */
          <div className="flex flex-col items-center py-3 gap-2 w-full h-full">
            <div className="w-8 h-8 bg-ey-yellow flex items-center justify-center flex-shrink-0">
              <span className="text-ey-dark font-bold text-sm leading-none">EY</span>
            </div>

            <Tip label="Expand sidebar">
              <button
                onClick={onToggleCollapse}
                className="w-9 h-9 flex items-center justify-center rounded
                           text-ey-muted hover:text-white hover:bg-ey-surface transition-colors mt-1"
              >
                <PanelLeftOpen size={16} />
              </button>
            </Tip>

            <div className="w-8 border-t border-ey-border my-1" />

            <Tip label="New conversation">
              <button
                onClick={onNewChat}
                className="w-9 h-9 flex items-center justify-center rounded
                           bg-ey-yellow text-ey-dark hover:bg-ey-yellow-dim transition-colors"
              >
                <Plus size={16} />
              </button>
            </Tip>

            <div className="flex-1 flex flex-col gap-1 overflow-hidden w-full items-center px-2 mt-1">
              {sessions.slice(0, 6).map(s => (
                <Tip key={s.id} label={s.title}>
                  <button
                    onClick={() => onSelectSession(s.id)}
                    className={`w-9 h-9 flex items-center justify-center rounded transition-colors ${
                      s.id === activeSessionId
                        ? 'bg-ey-card border border-ey-border text-ey-yellow'
                        : 'text-ey-muted hover:text-white hover:bg-ey-surface'
                    }`}
                  >
                    <MessageSquare size={14} />
                  </button>
                </Tip>
              ))}
            </div>

            <div className="w-8 border-t border-ey-border my-1" />

            <Tip label="Upload contract">
              <button
                onClick={onOpenUpload}
                className="w-9 h-9 flex items-center justify-center rounded
                           text-ey-muted hover:text-ey-yellow hover:bg-ey-surface transition-colors mb-1"
              >
                <Upload size={15} />
              </button>
            </Tip>
          </div>
        ) : (
          /* Full sidebar content */
          <SidebarContent
            sessions={sessions} activeSessionId={activeSessionId}
            contracts={contracts} contractFilter={contractFilter}
            contractsExpanded={contractsExpanded}
            onToggleContracts={() => setContractsExpanded(v => !v)}
            showCollapseBtn
            onToggleCollapse={onToggleCollapse}
            onNewChat={onNewChat}
            onSelectSession={onSelectSession}
            onSelectContract={onSelectContract}
            onOpenUpload={onOpenUpload}
          />
        )}
      </aside>

      {/* ── Mobile drawer ── */}
      <aside className={`
        md:hidden fixed inset-y-0 left-0 z-30 w-[280px] flex flex-col
        bg-ey-dark border-r border-ey-border
        transform transition-transform duration-300 ease-out
        ${mobileOpen ? 'translate-x-0' : '-translate-x-full'}
      `}>
        <SidebarContent
          sessions={sessions} activeSessionId={activeSessionId}
          contracts={contracts} contractFilter={contractFilter}
          contractsExpanded={contractsExpanded}
          onToggleContracts={() => setContractsExpanded(v => !v)}
          showCollapseBtn={false}
          showCloseBtn
          onCloseBtn={onCloseMobile}
          onToggleCollapse={onToggleCollapse}
          onNewChat={onNewChat}
          onSelectSession={onSelectSession}
          onSelectContract={onSelectContract}
          onOpenUpload={onOpenUpload}
        />
      </aside>
    </>
  )
}

// ─── Shared sidebar body ──────────────────────────────────────────────────────

function SidebarContent({
  sessions, activeSessionId, contracts, contractFilter,
  contractsExpanded, onToggleContracts,
  showCollapseBtn, showCloseBtn,
  onToggleCollapse, onCloseBtn,
  onNewChat, onSelectSession, onSelectContract, onOpenUpload,
}: {
  sessions: ChatSession[]
  activeSessionId: string | null
  contracts: Contract[]
  contractFilter: string | null
  contractsExpanded: boolean
  onToggleContracts: () => void
  showCollapseBtn?: boolean
  showCloseBtn?: boolean
  onToggleCollapse: () => void
  onCloseBtn?: () => void
  onNewChat: () => void
  onSelectSession: (id: string) => void
  onSelectContract: (id: string | null) => void
  onOpenUpload: () => void
}) {
  return (
    <>
      {/* Logo row */}
      <div className="flex items-center justify-between px-4 py-4 border-b border-ey-border flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-ey-yellow flex items-center justify-center flex-shrink-0">
            <span className="text-ey-dark font-bold text-sm leading-none">EY</span>
          </div>
          <div>
            <p className="text-white font-semibold text-sm leading-tight">Contract360</p>
            <p className="text-ey-muted text-xs">Intelligence Platform</p>
          </div>
        </div>

        {showCollapseBtn && (
          <button
            onClick={onToggleCollapse}
            title="Collapse sidebar"
            className="w-7 h-7 flex items-center justify-center rounded
                       text-ey-muted hover:text-white hover:bg-ey-surface transition-colors"
          >
            <PanelLeftClose size={15} />
          </button>
        )}
        {showCloseBtn && (
          <button
            onClick={onCloseBtn}
            className="w-7 h-7 flex items-center justify-center rounded
                       text-ey-muted hover:text-white hover:bg-ey-surface transition-colors"
          >
            <X size={15} />
          </button>
        )}
      </div>

      {/* New Chat */}
      <div className="px-3 py-3 flex-shrink-0">
        <button
          onClick={onNewChat}
          className="w-full flex items-center justify-center gap-2 px-3 py-2.5
                     bg-ey-yellow text-ey-dark font-semibold text-sm rounded
                     hover:bg-ey-yellow-dim transition-colors"
        >
          <Plus size={15} />
          New Conversation
        </button>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto min-h-0">
        <p className="px-4 pt-1 pb-2 text-xs font-medium text-ey-muted uppercase tracking-wider">
          Recent
        </p>

        {sessions.length === 0 ? (
          <p className="px-4 py-3 text-xs text-ey-muted">No conversations yet.</p>
        ) : (
          <div className="space-y-0.5 px-2">
            {sessions.map(session => {
              const isActive = session.id === activeSessionId
              return (
                <button
                  key={session.id}
                  onClick={() => onSelectSession(session.id)}
                  className={`w-full text-left px-3 py-2.5 rounded group transition-colors ${
                    isActive ? 'bg-ey-card border border-ey-border' : 'hover:bg-ey-surface'
                  }`}
                >
                  <div className="flex items-start gap-2">
                    <MessageSquare
                      size={13}
                      className={`mt-0.5 flex-shrink-0 ${isActive ? 'text-ey-yellow' : 'text-ey-muted'}`}
                    />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-1">
                        <p className={`text-xs font-medium truncate ${isActive ? 'text-white' : 'text-ey-light'}`}>
                          {session.title}
                        </p>
                        <span className="text-ey-muted text-[10px] flex-shrink-0">
                          {formatDate(session.updatedAt)}
                        </span>
                      </div>
                      <p className="text-ey-muted text-[11px] truncate mt-0.5">{session.previewText}</p>
                    </div>
                  </div>
                </button>
              )
            })}
          </div>
        )}

        {/* Contracts */}
        <div className="mt-4 border-t border-ey-border pt-3">
          <button
            onClick={onToggleContracts}
            className="w-full flex items-center justify-between px-4 py-1"
          >
            <p className="text-xs font-medium text-ey-muted uppercase tracking-wider">Contracts</p>
            {contractsExpanded
              ? <ChevronDown size={12} className="text-ey-muted" />
              : <ChevronRight size={12} className="text-ey-muted" />}
          </button>

          {contractsExpanded && (
            <div className="mt-1 space-y-0.5 px-2 animate-fade-in">
              <button
                onClick={() => onSelectContract(null)}
                className={`w-full text-left px-3 py-2 rounded transition-colors flex items-center gap-2 ${
                  contractFilter === null ? 'bg-ey-card border border-ey-border' : 'hover:bg-ey-surface'
                }`}
              >
                <div className="w-1.5 h-1.5 rounded-full bg-ey-yellow flex-shrink-0" />
                <p className="text-xs text-ey-light font-medium flex-1">All Contracts</p>
                {contractFilter === null && <CheckCircle2 size={12} className="text-ey-yellow flex-shrink-0" />}
              </button>

              {contracts.map(contract => (
                <button
                  key={contract.id}
                  onClick={() => onSelectContract(contract.id)}
                  className={`w-full text-left px-3 py-2 rounded transition-colors ${
                    contractFilter === contract.id ? 'bg-ey-card border border-ey-border' : 'hover:bg-ey-surface'
                  }`}
                >
                  <div className="flex items-start gap-2">
                    <FileText size={12} className="text-ey-muted mt-0.5 flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-xs text-ey-light font-medium truncate leading-snug">
                        {contract.displayName}
                      </p>
                      <p className="text-[10px] text-ey-muted mt-0.5">
                        {contract.pageCount > 0 ? `${contract.pageCount}p · ` : ''}{contract.fileSize}
                      </p>
                    </div>
                    {contractFilter === contract.id && (
                      <CheckCircle2 size={12} className="text-ey-yellow flex-shrink-0 mt-0.5" />
                    )}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Upload */}
      <div className="px-3 pb-4 pt-2 border-t border-ey-border flex-shrink-0">
        <button
          onClick={onOpenUpload}
          className="w-full flex items-center justify-center gap-2 px-3 py-2.5
                     border border-ey-border text-ey-light text-sm rounded
                     hover:border-ey-yellow hover:text-ey-yellow transition-colors"
        >
          <Upload size={14} />
          Upload Contract
        </button>
      </div>
    </>
  )
}
import { useState, useCallback, useEffect } from 'react'
import type { ChatSession, Contract, Message } from './types'
import { MOCK_CONTRACTS } from './data/mockData'
import Sidebar from './components/Sidebar'
import ChatArea from './components/ChatArea'
import UploadPanel from './components/UploadPanel'
import * as api from './api/client'

function sessionTitle(question: string): string {
  const q = question.trim()
  if (q.length <= 48) return q
  return q.slice(0, 45) + '…'
}

function generateLocalId() {
  return `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

export default function App() {
  const [sessions, setSessions]               = useState<ChatSession[]>([])
  const [activeSessionId, setActiveSession]   = useState<string | null>(null)
  const [contracts, setContracts]             = useState<Contract[]>(MOCK_CONTRACTS)
  const [contractFilter, setContractFilter]   = useState<string | null>(null)
  const [isLoading, setIsLoading]             = useState(false)
  const [uploadOpen, setUploadOpen]           = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const [apiError, setApiError]               = useState<string | null>(null)

  const activeSession = sessions.find(s => s.id === activeSessionId) ?? null

  // ── Load session list on mount ──────────────────────────────────────
  useEffect(() => {
    api.listSessions()
      .then(summaries => {
        // Convert summaries to ChatSession shape (no messages yet — lazy loaded)
        const loaded: ChatSession[] = summaries.map(s => ({
          id: s.id,
          title: s.title,
          createdAt: s.createdAt,
          updatedAt: s.updatedAt,
          messages: [],
          contractFilter: s.contractFilter,
          previewText: s.previewText ?? '',
        }))
        setSessions(loaded)
        if (loaded.length > 0) {
          setActiveSession(loaded[0].id)
          setContractFilter(loaded[0].contractFilter)
        }
      })
      .catch(() => {
        // Backend not reachable — stay on empty state; user can still create sessions
        setApiError('Could not reach the API. Check VITE_API_BASE_URL and that the backend is running.')
      })
  }, [])

  // ── Load full message history when switching sessions ───────────────
  useEffect(() => {
    if (!activeSessionId) return
    const session = sessions.find(s => s.id === activeSessionId)
    if (!session || session.messages.length > 0) return   // already loaded

    api.getHistory(activeSessionId)
      .then(messages => {
        setSessions(prev => prev.map(s =>
          s.id === activeSessionId ? { ...s, messages } : s
        ))
      })
      .catch(err => console.error('Failed to load history:', err))
  }, [activeSessionId])   // eslint-disable-line react-hooks/exhaustive-deps

  // ── New chat ────────────────────────────────────────────────────────
  const handleNewChat = useCallback(async () => {
    try {
      const session = await api.createSession({ contract_filter: contractFilter })
      setSessions(prev => [{ ...session, messages: [] }, ...prev])
      setActiveSession(session.id)
      setContractFilter(session.contractFilter)
    } catch {
      // Optimistic fallback: create a local-only session until API is available
      const localId = generateLocalId()
      const now = new Date().toISOString()
      setSessions(prev => [{
        id: localId,
        title: 'New Conversation',
        createdAt: now, updatedAt: now,
        messages: [], contractFilter, previewText: '',
      }, ...prev])
      setActiveSession(localId)
    }
    setMobileSidebarOpen(false)
  }, [contractFilter])

  const handleSelectSession = useCallback((id: string) => {
    setActiveSession(id)
    const session = sessions.find(s => s.id === id)
    if (session) setContractFilter(session.contractFilter)
    setMobileSidebarOpen(false)
  }, [sessions])

  const handleSelectContract = useCallback((id: string | null) => {
    setContractFilter(id)
  }, [])

  const handleDeleteSession = useCallback(async (id: string) => {
    await api.deleteSession(id).catch(() => {})
    setSessions(prev => prev.filter(s => s.id !== id))
    if (activeSessionId === id) {
      setActiveSession(null)
    }
  }, [activeSessionId])

  // ── Send message ────────────────────────────────────────────────────
  const handleSendMessage = useCallback(async (text: string) => {
    if (isLoading) return
    setApiError(null)

    // Ensure we have an active session
    let sessionId = activeSessionId
    if (!sessionId) {
      try {
        const session = await api.createSession({ contract_filter: contractFilter })
        setSessions(prev => [{ ...session, messages: [] }, ...prev])
        setActiveSession(session.id)
        setContractFilter(session.contractFilter)
        sessionId = session.id
      } catch (err) {
        setApiError('Failed to create session. Is the backend running?')
        return
      }
    }

    // Optimistically append the user message
    const tempUserMsg: Message = {
      id: `tmp_${generateLocalId()}`,
      role: 'user',
      content: text,
      timestamp: new Date().toISOString(),
    }
    setSessions(prev => prev.map(s =>
      s.id === sessionId ? {
        ...s,
        title: s.messages.length === 0 ? sessionTitle(text) : s.title,
        messages: [...s.messages, tempUserMsg],
        updatedAt: new Date().toISOString(),
      } : s
    ))

    // Optimistically add a streaming placeholder for the assistant
    const streamingId = `streaming_${generateLocalId()}`
    setIsLoading(true)
    setSessions(prev => prev.map(s =>
      s.id === sessionId ? {
        ...s,
        messages: [...s.messages, {
          id: streamingId,
          role: 'assistant' as const,
          content: '',
          timestamp: new Date().toISOString(),
          isStreaming: true,
        }],
      } : s
    ))

    try {
      const result = await api.askQuestion(sessionId!, {
        question: text,
        route_override: 'auto',
      })

      // Simulate word-by-word streaming from the returned answer
      const words = result.answer.split(' ')
      let streamedContent = ''

      await new Promise<void>(resolve => {
        let idx = 0
        const interval = setInterval(() => {
          idx = Math.min(idx + Math.floor(Math.random() * 3) + 1, words.length)
          streamedContent = words.slice(0, idx).join(' ')
          setSessions(prev => prev.map(s =>
            s.id === sessionId ? {
              ...s,
              messages: s.messages.map(m =>
                m.id === streamingId ? { ...m, content: streamedContent } : m
              ),
            } : s
          ))
          if (idx >= words.length) { clearInterval(interval); resolve() }
        }, 28)
      })

      // Finalize: replace streaming placeholder with real message data
      setSessions(prev => prev.map(s =>
        s.id === sessionId ? {
          ...s,
          messages: s.messages.map(m =>
            m.id === streamingId ? {
              id: result.message_id,
              role: 'assistant' as const,
              content: result.answer,
              timestamp: new Date().toISOString(),
              route: result.route as Message['route'],
              isStreaming: false,
            } : m
          ),
          previewText: result.answer.slice(0, 80) + (result.answer.length > 80 ? '…' : ''),
          updatedAt: new Date().toISOString(),
        } : s
      ))
    } catch (err) {
      const errorText = err instanceof Error ? err.message : 'An error occurred.'
      setApiError(errorText)
      // Remove the streaming placeholder on error
      setSessions(prev => prev.map(s =>
        s.id === sessionId ? {
          ...s,
          messages: s.messages.filter(m => m.id !== streamingId),
        } : s
      ))
    } finally {
      setIsLoading(false)
    }
  }, [activeSessionId, contractFilter, isLoading])

  const handleContractAdded = useCallback((contractId: string, fileName: string) => {
    setContracts(prev => {
      if (prev.find(c => c.id === contractId)) return prev
      return [...prev, {
        id: contractId,
        displayName: fileName.replace(/\.[^.]+$/, '').replace(/_/g, ' '),
        fileName, status: 'search_only' as const,
        uploadedAt: new Date().toISOString().split('T')[0],
        pageCount: 0, fileSize: '', graphReady: false,
      }]
    })
  }, [])

  return (
    <div className="flex h-screen bg-ey-darker overflow-hidden">

      {/* Mobile backdrop */}
      {mobileSidebarOpen && (
        <div
          className="fixed inset-0 bg-black/60 z-20 md:hidden"
          onClick={() => setMobileSidebarOpen(false)}
        />
      )}

      <Sidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        contracts={contracts}
        contractFilter={contractFilter}
        collapsed={sidebarCollapsed}
        mobileOpen={mobileSidebarOpen}
        onToggleCollapse={() => setSidebarCollapsed(v => !v)}
        onCloseMobile={() => setMobileSidebarOpen(false)}
        onNewChat={handleNewChat}
        onSelectSession={handleSelectSession}
        onSelectContract={handleSelectContract}
        onOpenUpload={() => setUploadOpen(true)}
        onDeleteSession={handleDeleteSession}
      />

      <div className="flex flex-col flex-1 min-w-0">
        {apiError && (
          <div className="bg-red-900/60 text-red-200 text-sm px-4 py-2 flex items-center justify-between">
            <span>{apiError}</span>
            <button onClick={() => setApiError(null)} className="ml-4 text-red-300 hover:text-white">✕</button>
          </div>
        )}
        <ChatArea
          session={activeSession}
          contracts={contracts}
          contractFilter={contractFilter}
          isLoading={isLoading}
          onSendMessage={handleSendMessage}
          onOpenMobileSidebar={() => setMobileSidebarOpen(true)}
        />
      </div>

      {uploadOpen && (
        <UploadPanel
          onClose={() => setUploadOpen(false)}
          onContractAdded={handleContractAdded}
        />
      )}
    </div>
  )
}

import { useEffect, useRef, useState } from 'react'
import {
  Send, ChevronDown, ChevronUp,
  FileText, Copy, Check, Bot, User, ArrowRight, Menu,
} from 'lucide-react'
import type { Message, Citation, ChatSession, Contract } from '../types'

// ─── Citation card ────────────────────────────────────────────────────────────

function CitationCard({ citation, index }: { citation: Citation; index: number }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="border border-ey-border rounded bg-ey-darker overflow-hidden">
      <button
        onClick={() => setExpanded(v => !v)}
        className="w-full flex items-start gap-3 p-3 text-left hover:bg-ey-surface/50 transition-colors"
      >
        <span className="w-5 h-5 rounded bg-ey-border flex items-center justify-center text-[10px] font-bold text-ey-muted flex-shrink-0 mt-0.5">
          {index + 1}
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium text-white truncate">{citation.clauseTitle}</p>
          <p className="text-[11px] text-ey-muted mt-0.5 truncate">{citation.sectionTitle}</p>
          <p className="text-[11px] text-ey-muted">
            {citation.contractName} · pp. {citation.pageRange}
          </p>
        </div>
        {expanded
          ? <ChevronUp size={12} className="text-ey-muted mt-1 flex-shrink-0" />
          : <ChevronDown size={12} className="text-ey-muted mt-1 flex-shrink-0" />}
      </button>
      {expanded && (
        <div className="px-3 pb-3 pt-0 border-t border-ey-border animate-fade-in">
          <p className="text-[11px] text-ey-muted mb-1.5 font-medium">Clause text</p>
          <blockquote className="text-xs text-ey-light italic border-l-2 border-ey-yellow pl-3 leading-relaxed">
            "{citation.evidenceQuote}"
          </blockquote>
          <p className="text-[10px] text-ey-muted mt-2">
            <FileText size={9} className="inline mr-1" />
            {citation.sourcePath}
          </p>
        </div>
      )}
    </div>
  )
}

// ─── Render markdown-ish content ──────────────────────────────────────────────

function renderContent(text: string): React.ReactNode {
  const lines = text.split('\n')
  const elements: React.ReactNode[] = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]

    // Table
    if (line.startsWith('|') && lines[i + 1]?.startsWith('|---')) {
      const rows: string[][] = []
      while (i < lines.length && lines[i].startsWith('|')) {
        const cells = lines[i].split('|').slice(1, -1).map(c => c.trim())
        rows.push(cells)
        i++
      }
      const [header, , ...body] = rows
      elements.push(
        <div key={i} className="overflow-x-auto my-3">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="border-b border-ey-border">
                {header?.map((h, j) => (
                  <th key={j} className="text-left py-1.5 pr-4 text-ey-yellow font-semibold">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {body.map((row, ri) => (
                <tr key={ri} className="border-b border-ey-border/50 hover:bg-ey-surface/30 transition-colors">
                  {row.map((cell, ci) => (
                    <td key={ci} className="py-1.5 pr-4 text-ey-light align-top">{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
      continue
    }

    // Bold heading line
    if (line.startsWith('**') && line.endsWith('**') && line.slice(2, -2).indexOf('**') === -1) {
      elements.push(
        <p key={i} className="font-semibold text-white mt-3 mb-1 first:mt-0">
          {line.slice(2, -2)}
        </p>
      )
      i++; continue
    }

    // Blockquote
    if (line.startsWith('> ')) {
      elements.push(
        <div key={i} className="border-l-2 border-ey-yellow/50 pl-3 my-2">
          <p className="text-xs text-ey-muted italic">{renderInline(line.slice(2))}</p>
        </div>
      )
      i++; continue
    }

    // Unordered list
    if (line.startsWith('- ') || line.startsWith('* ')) {
      const items: string[] = []
      while (i < lines.length && (lines[i].startsWith('- ') || lines[i].startsWith('* '))) {
        items.push(lines[i].slice(2))
        i++
      }
      elements.push(
        <ul key={i} className="space-y-1 my-2 pl-4">
          {items.map((item, j) => (
            <li key={j} className="text-sm text-ey-light flex gap-2">
              <span className="text-ey-yellow mt-1.5 text-[6px] flex-shrink-0">●</span>
              <span>{renderInline(item)}</span>
            </li>
          ))}
        </ul>
      )
      continue
    }

    // Ordered list — preserve the REAL number from each line and tolerate a
    // blank line between consecutive numbered items (so they don't each
    // become a separate list restarting at "1").
    if (/^\d+\.\s/.test(line)) {
      const items: { num: string; text: string }[] = []
      while (i < lines.length) {
        const m = lines[i].match(/^(\d+)\.\s+(.*)/)
        if (m) {
          items.push({ num: m[1], text: m[2] })
          i++
        } else if (lines[i].trim() === '' && /^\d+\.\s/.test(lines[i + 1] || '')) {
          i++ // skip a blank line that just separates two numbered items
        } else {
          break
        }
      }
      elements.push(
        <ol key={i} className="space-y-1 my-2 pl-4">
          {items.map((it, j) => (
            <li key={j} className="text-sm text-ey-light flex gap-2">
              <span className="text-ey-yellow font-medium w-5 flex-shrink-0 text-right">{it.num}.</span>
              <span>{renderInline(it.text)}</span>
            </li>
          ))}
        </ol>
      )
      continue
    }

    // Empty line
    if (line.trim() === '') { elements.push(<div key={i} className="h-2" />); i++; continue }

    // Paragraph
    elements.push(
      <p key={i} className="text-sm text-ey-light leading-relaxed">
        {renderInline(line)}
      </p>
    )
    i++
  }

  return <>{elements}</>
}

function renderInline(text: string): React.ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\(§[^)]+\))/g)
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**'))
      return <strong key={i} className="text-white font-semibold">{part.slice(2, -2)}</strong>
    if (part.startsWith('`') && part.endsWith('`'))
      return <code key={i} className="bg-ey-darker border border-ey-border px-1 py-0.5 rounded text-[11px] text-ey-yellow font-mono">{part.slice(1, -1)}</code>
    if (part.startsWith('(§'))
      return <span key={i} className="text-ey-yellow/70 text-xs">{part}</span>
    return part
  })
}

// ─── Follow-up suggestions ────────────────────────────────────────────────────

function FollowUpSuggestions({
  suggestions,
  onSelect,
}: {
  suggestions: string[]
  onSelect: (q: string) => void
}) {
  return (
    <div className="mt-4 animate-slide-up">
      <p className="text-[11px] text-ey-muted mb-2 pl-10">Continue this conversation</p>
      <div className="pl-10 flex flex-col gap-1.5">
        {suggestions.map((q, i) => (
          <button
            key={i}
            onClick={() => onSelect(q)}
            className="flex items-center gap-2 w-fit max-w-full px-3 py-2
                       border border-ey-border rounded text-left
                       hover:border-ey-yellow/60 hover:bg-ey-card transition-all group"
          >
            <ArrowRight size={11} className="text-ey-muted group-hover:text-ey-yellow transition-colors flex-shrink-0" />
            <span className="text-xs text-ey-muted group-hover:text-ey-light transition-colors">{q}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

// ─── Individual message ───────────────────────────────────────────────────────

function MessageBubble({
  message,
  isLast,
  onFollowUp,
}: {
  message: Message
  isLast: boolean
  onFollowUp: (q: string) => void
}) {
  const [showCitations, setShowCitations] = useState(false)
  const [copied, setCopied] = useState(false)
  const isUser = message.role === 'user'

  const handleCopy = () => {
    navigator.clipboard.writeText(message.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className={`flex gap-3 animate-slide-up ${isUser ? 'flex-row-reverse' : ''}`}>
      {/* Avatar */}
      <div className={`w-7 h-7 rounded flex items-center justify-center flex-shrink-0 mt-0.5 ${
        isUser ? 'bg-ey-yellow' : 'bg-ey-card border border-ey-border'
      }`}>
        {isUser
          ? <User size={14} className="text-ey-dark" />
          : <Bot size={14} className="text-ey-yellow" />}
      </div>

      <div className={`flex-1 max-w-[82%] ${isUser ? 'flex flex-col items-end' : ''}`}>
        {/* Bubble */}
        <div className={`rounded px-4 py-3 ${
          isUser
            ? 'bg-ey-yellow text-ey-dark'
            : 'bg-ey-card border border-ey-border'
        }`}>
          {isUser ? (
            <p className="text-sm font-medium">{message.content}</p>
          ) : message.isStreaming ? (
            <p className="text-sm text-ey-light typing-cursor">{message.content}</p>
          ) : (
            <div className="ai-prose">{renderContent(message.content)}</div>
          )}
        </div>

        {/* Action bar — assistant only, after streaming */}
        {!isUser && !message.isStreaming && (
          <div className="flex items-center gap-3 mt-2 px-1 flex-wrap">
            <button
              onClick={handleCopy}
              className="flex items-center gap-1 text-[11px] text-ey-muted hover:text-ey-light transition-colors"
            >
              {copied ? <Check size={10} /> : <Copy size={10} />}
              {copied ? 'Copied' : 'Copy'}
            </button>

            {message.citations && message.citations.length > 0 && (
              <button
                onClick={() => setShowCitations(v => !v)}
                className="flex items-center gap-1 text-[11px] text-ey-muted hover:text-ey-yellow transition-colors"
              >
                <FileText size={10} />
                {showCitations ? 'Hide' : 'Show'} {message.citations.length} source{message.citations.length !== 1 ? 's' : ''}
                {showCitations ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
              </button>
            )}
          </div>
        )}

        {/* Citations */}
        {showCitations && message.citations && (
          <div className="mt-2 space-y-2 w-full animate-fade-in">
            {message.citations.map((cit, i) => (
              <CitationCard key={cit.id} citation={cit} index={i} />
            ))}
          </div>
        )}

        {/* Follow-up suggestions — only on last assistant message */}
        {!isUser && !message.isStreaming && isLast && message.followUpSuggestions && message.followUpSuggestions.length > 0 && (
          <FollowUpSuggestions
            suggestions={message.followUpSuggestions}
            onSelect={onFollowUp}
          />
        )}
      </div>
    </div>
  )
}

// ─── Typing indicator ─────────────────────────────────────────────────────────

function TypingIndicator() {
  return (
    <div className="flex gap-3 animate-fade-in">
      <div className="w-7 h-7 rounded bg-ey-card border border-ey-border flex items-center justify-center flex-shrink-0">
        <Bot size={14} className="text-ey-yellow" />
      </div>
      <div className="bg-ey-card border border-ey-border rounded px-4 py-3">
        <div className="flex items-center gap-1.5">
          {[0, 1, 2].map(i => (
            <span
              key={i}
              className="w-1.5 h-1.5 rounded-full bg-ey-yellow animate-pulse-soft"
              style={{ animationDelay: `${i * 0.2}s` }}
            />
          ))}
          <span className="text-xs text-ey-muted ml-1">Analysing contracts…</span>
        </div>
      </div>
    </div>
  )
}

// ─── Scope label helper ───────────────────────────────────────────────────────

function scopeLabel(selectedContracts: string[], contracts: Contract[]): string {
  if (selectedContracts.length === 0) return 'All contracts'
  if (selectedContracts.length === 1) {
    const c = contracts.find(c => c.id === selectedContracts[0])
    return c?.displayName ?? selectedContracts[0]
  }
  return `${selectedContracts.length} contracts selected`
}

// ─── Welcome / empty state ────────────────────────────────────────────────────

function WelcomeScreen({
  selectedContracts,
  contracts,
}: {
  selectedContracts: string[]
  contracts: Contract[]
}) {
  const label = scopeLabel(selectedContracts, contracts)

  return (
    <div className="flex-1 flex flex-col items-center justify-center px-8 py-16">
      <div className="w-10 h-10 bg-ey-yellow flex items-center justify-center mb-6">
        <span className="text-ey-dark font-bold text-base">EY</span>
      </div>
      <h1 className="text-xl font-semibold text-white mb-3">
        What would you like to know?
      </h1>
      <p className="text-ey-muted text-sm text-center max-w-sm leading-relaxed">
        {selectedContracts.length === 0
          ? 'Ask questions across any of your contracts, or select a specific contract from the sidebar.'
          : <>Querying <span className="text-ey-light font-medium">{label}</span>.</>}
      </p>
    </div>
  )
}

// ─── Chat input ───────────────────────────────────────────────────────────────

function ChatInput({
  onSend,
  disabled,
  selectedContracts,
  contracts,
}: {
  onSend: (text: string) => void
  disabled: boolean
  selectedContracts: string[]
  contracts: Contract[]
}) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const submit = () => {
    const trimmed = value.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setValue('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() }
  }

  const handleInput = () => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 160) + 'px'
  }

  return (
    <div className="border-t border-ey-border bg-ey-dark px-3 md:px-4 py-3 md:py-4">
      {/* Scope pill */}
      <div className="flex items-center gap-2 mb-2">
        <div className="flex items-center gap-1.5 px-2 py-1 bg-ey-surface rounded">
          <FileText size={10} className="text-ey-muted" />
          <span className="text-[11px] text-ey-muted">
            {scopeLabel(selectedContracts, contracts)}
          </span>
        </div>
      </div>

      <div className="flex gap-3 items-end">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={e => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          onInput={handleInput}
          rows={1}
          placeholder="Ask a question about your contracts…"
          disabled={disabled}
          className="flex-1 bg-ey-surface border border-ey-border rounded px-4 py-3
                     text-sm text-white placeholder-ey-muted resize-none
                     focus:outline-none focus:border-ey-yellow/50 transition-colors
                     disabled:opacity-50 disabled:cursor-not-allowed"
          style={{ minHeight: '44px', maxHeight: '160px' }}
        />
        <button
          onClick={submit}
          disabled={disabled || !value.trim()}
          className="w-11 h-11 flex items-center justify-center rounded
                     bg-ey-yellow text-ey-dark flex-shrink-0
                     hover:bg-ey-yellow-dim transition-colors
                     disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Send size={16} />
        </button>
      </div>
    </div>
  )
}

// ─── Main ChatArea ────────────────────────────────────────────────────────────

interface ChatAreaProps {
  session: ChatSession | null
  contracts: Contract[]
  contractFilter: string | null
  selectedContracts: string[]
  isLoading: boolean
  onSendMessage: (text: string) => void
  onOpenMobileSidebar: () => void
}

export default function ChatArea({
  session, contracts, contractFilter, selectedContracts, isLoading, onSendMessage, onOpenMobileSidebar,
}: ChatAreaProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [session?.messages, isLoading])

  const showWelcome = !session || session.messages.length === 0
  const messages = session?.messages ?? []

  let lastAssistantIdx = -1
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === 'assistant') { lastAssistantIdx = i; break }
  }

  return (
    <div className="flex-1 flex flex-col h-full min-w-0 bg-ey-darker">

      {/* ── Header ── */}
      <div className="flex items-center gap-3 px-4 md:px-6 py-4 border-b border-ey-border bg-ey-dark flex-shrink-0">
        {/* Mobile hamburger */}
        <button
          onClick={onOpenMobileSidebar}
          className="md:hidden w-8 h-8 flex items-center justify-center rounded
                     text-ey-muted hover:text-white hover:bg-ey-surface transition-colors flex-shrink-0"
        >
          <Menu size={18} />
        </button>

        <div className="flex-1 min-w-0">
          <h2 className="text-sm font-semibold text-white truncate">
            {session ? session.title : 'New Conversation'}
          </h2>
          <p className="text-[11px] text-ey-muted mt-0.5 truncate">
            {scopeLabel(selectedContracts, contracts)}
          </p>
        </div>
      </div>

      {/* ── Messages ── */}
      <div className="flex-1 overflow-y-auto">
        {showWelcome ? (
          <WelcomeScreen selectedContracts={selectedContracts} contracts={contracts} />
        ) : (
          <div className="max-w-3xl mx-auto px-4 md:px-6 py-6 space-y-6">
            {messages.map((msg, idx) => {
              // Don't render the streaming placeholder until the first token
              // arrives — the TypingIndicator stands in for it, otherwise the
              // user sees two boxes (an empty bubble + the indicator).
              if (msg.isStreaming && msg.content === '') return null
              return (
                <MessageBubble
                  key={`${msg.id}-${idx}`}
                  message={msg}
                  isLast={idx === lastAssistantIdx && !isLoading}
                  onFollowUp={onSendMessage}
                />
              )
            })}
            {isLoading && !messages.some(m => m.isStreaming && m.content !== '') && <TypingIndicator />}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* ── Input ── */}
      <ChatInput
        onSend={onSendMessage}
        disabled={isLoading}
        selectedContracts={selectedContracts}
        contracts={contracts}
      />
    </div>
  )
}
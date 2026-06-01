import { useEffect, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import type { SessionMessage } from '../api/types'

const S: Record<string, React.CSSProperties> = {
  root: { display: 'flex', flexDirection: 'column', height: '100%', minHeight: 400 },
  messages: {
    flex: 1, overflowY: 'auto', padding: '12px 0', display: 'flex',
    flexDirection: 'column', gap: 12,
  },
  msgUser: {
    alignSelf: 'flex-end', maxWidth: '75%', background: 'var(--accent)',
    color: '#fff', padding: '8px 14px', borderRadius: '10px 10px 2px 10px',
    fontSize: 12, lineHeight: 1.6,
  },
  msgAssistant: {
    alignSelf: 'flex-start', maxWidth: '80%', background: 'var(--bg-surface)',
    border: '1px solid var(--border)', color: 'var(--text-primary)',
    padding: '8px 14px', borderRadius: '10px 10px 10px 2px',
    fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap',
  },
  toolBadge: {
    fontSize: 10, background: 'rgba(59,130,246,0.12)', border: '1px solid var(--border)',
    borderRadius: 4, padding: '2px 8px', color: 'var(--accent-bright)',
    marginBottom: 4, display: 'inline-block',
  },
  inputRow: { display: 'flex', gap: 8, marginTop: 12 },
  input: {
    flex: 1, padding: '10px 14px', background: 'var(--bg-base)',
    border: '1px solid var(--border)', borderRadius: 6,
    color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontSize: 12,
    resize: 'none',
  },
  sendBtn: {
    padding: '10px 18px', background: 'var(--accent)', border: 'none', borderRadius: 6,
    color: '#fff', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 600,
    alignSelf: 'flex-end',
  },
}

interface ChatMsg { role: 'user' | 'assistant'; content: string; toolCalls?: number }

export function ChatPanel({ modelId }: { modelId: string }) {
  const [msgs, setMsgs] = useState<ChatMsg[]>([])
  const [input, setInput] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [msgs])

  const send = useMutation({
    mutationFn: (messages: SessionMessage[]) =>
      api.testSession({ model_id: modelId, messages }),
    onSuccess: data => {
      setMsgs(prev => [
        ...prev,
        { role: 'assistant', content: data.response || '(no response)', toolCalls: data.tool_calls_made },
      ])
    },
    onError: err => {
      setMsgs(prev => [
        ...prev,
        { role: 'assistant', content: `Error: ${(err as Error).message}` },
      ])
    },
  })

  const handleSend = () => {
    if (!input.trim() || send.isPending) return
    const userMsg: ChatMsg = { role: 'user', content: input }
    const history: SessionMessage[] = [...msgs, userMsg].map(m => ({
      role: m.role,
      content: m.content,
    }))
    setMsgs(prev => [...prev, userMsg])
    setInput('')
    send.mutate(history)
  }

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  return (
    <div style={S.root}>
      <div style={S.messages} data-testid="chat-messages">
        {msgs.length === 0 && (
          <p style={{ color: 'var(--text-dim)', fontSize: 12, textAlign: 'center', marginTop: 40 }}>
            Send a message to test this model's tools against Claude
          </p>
        )}
        {msgs.map((m, i) => (
          <div key={i}>
            {m.toolCalls != null && m.toolCalls > 0 && (
              <div style={{ textAlign: 'left', marginBottom: 4 }}>
                <span style={S.toolBadge}>🔧 {m.toolCalls} tool call{m.toolCalls !== 1 ? 's' : ''}</span>
              </div>
            )}
            <div style={m.role === 'user' ? S.msgUser : S.msgAssistant}>
              {m.content}
            </div>
          </div>
        ))}
        {send.isPending && (
          <div style={{ ...S.msgAssistant, color: 'var(--text-dim)' }}>⟳ thinking...</div>
        )}
        <div ref={bottomRef} />
      </div>

      <div style={S.inputRow}>
        <textarea
          style={S.input}
          rows={2}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKey}
          placeholder="Ask something... (Enter to send, Shift+Enter for newline)"
          data-testid="chat-input"
        />
        <button
          style={{ ...S.sendBtn, opacity: send.isPending ? 0.6 : 1 }}
          onClick={handleSend}
          disabled={send.isPending || !input.trim()}
          data-testid="chat-send"
        >
          send
        </button>
      </div>
    </div>
  )
}

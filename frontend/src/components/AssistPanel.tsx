import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '../api/client'

const S: Record<string, React.CSSProperties> = {
  root: { display: 'flex', flexDirection: 'column', gap: 16 },
  label: { fontSize: 10, letterSpacing: '0.1em', color: 'var(--text-dim)', textTransform: 'uppercase', marginBottom: 6 },
  textarea: {
    width: '100%', padding: '10px 12px', background: 'var(--bg-base)',
    border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text-primary)',
    fontFamily: 'var(--font-mono)', fontSize: 12, resize: 'vertical', minHeight: 80,
    lineHeight: 1.6,
  },
  btn: {
    padding: '8px 18px', background: 'var(--accent)', border: 'none', borderRadius: 5,
    color: '#fff', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 600,
  },
  btnGhost: {
    padding: '8px 18px', background: 'transparent', border: '1px solid var(--border-bright)',
    borderRadius: 5, color: 'var(--text-secondary)', cursor: 'pointer',
    fontFamily: 'var(--font-mono)', fontSize: 12,
  },
  rationale: {
    background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: 6,
    padding: '10px 14px', fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.7,
  },
  summary: {
    fontSize: 11, color: 'var(--text-dim)', cursor: 'pointer', letterSpacing: '0.06em',
    textTransform: 'uppercase',
  },
}

export function AssistPanel({
  modelId,
  currentPrompt,
  onAccept,
}: {
  modelId: string
  currentPrompt: string
  onAccept: (prompt: string) => void
}) {
  const [prompt, setPrompt] = useState(currentPrompt)
  const [intent, setIntent] = useState('')
  const [feedback, setFeedback] = useState('')
  const [draft, setDraft] = useState<{ system_prompt: string; rationale: string } | null>(null)
  const [showRationale, setShowRationale] = useState(false)
  const isRefine = !!draft

  const assist = useMutation({
    mutationFn: () =>
      api.assist.systemPrompt({
        model_id: modelId,
        intent,
        ...(isRefine && feedback ? { prior_draft: draft!.system_prompt, feedback } : {}),
      }),
    onSuccess: data => {
      setDraft(data)
      setShowRationale(false)
    },
  })

  const accept = () => {
    if (!draft) return
    setPrompt(draft.system_prompt)
    onAccept(draft.system_prompt)
    setDraft(null)
    setFeedback('')
  }

  return (
    <div style={S.root}>
      {/* Current system prompt */}
      <div>
        <div style={S.label}>system prompt</div>
        <textarea
          style={{ ...S.textarea, minHeight: 140 }}
          value={prompt}
          onChange={e => { setPrompt(e.target.value); onAccept(e.target.value) }}
          placeholder="Describe what this model's LLM client should understand and do..."
          data-testid="system-prompt"
        />
      </div>

      {/* AI assist */}
      <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 8, padding: 16 }}>
        <div style={{ ...S.label, color: 'var(--accent-bright)' }}>✦ AI assist</div>
        <div style={S.label}>your intent</div>
        <textarea
          style={{ ...S.textarea, minHeight: 60 }}
          value={intent}
          onChange={e => setIntent(e.target.value)}
          placeholder="e.g. Help users analyse org readiness across divisions and run what-if scenarios"
          data-testid="assist-intent"
        />
        <div style={{ height: 10 }} />
        <button
          style={{ ...S.btn, opacity: assist.isPending ? 0.6 : 1 }}
          onClick={() => assist.mutate()}
          disabled={assist.isPending || !intent.trim()}
          data-testid="assist-btn"
        >
          {assist.isPending ? '⟳ drafting...' : isRefine ? '↺ refine prompt' : '✦ draft prompt'}
        </button>

        {assist.error && (
          <p style={{ color: 'var(--red)', fontSize: 12, marginTop: 8 }}>
            {String((assist.error as Error).message)}
          </p>
        )}

        {/* Draft result */}
        {draft && (
          <div style={{ marginTop: 16 }}>
            <div style={S.label}>draft</div>
            <div style={{ ...S.rationale, color: 'var(--text-primary)', marginBottom: 10, whiteSpace: 'pre-wrap' }}>
              {draft.system_prompt}
            </div>

            <details onToggle={e => setShowRationale((e.target as HTMLDetailsElement).open)}>
              <summary style={S.summary}>▸ rationale</summary>
              {showRationale && <p style={{ ...S.rationale, marginTop: 8 }}>{draft.rationale}</p>}
            </details>

            <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
              <button style={S.btn} onClick={accept} data-testid="accept-prompt">accept</button>
              <button style={S.btnGhost} onClick={() => { setDraft(null); setFeedback('') }}>discard</button>
            </div>

            {/* Refine */}
            <div style={{ marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--border)' }}>
              <div style={S.label}>feedback for refinement</div>
              <textarea
                style={{ ...S.textarea, minHeight: 50 }}
                value={feedback}
                onChange={e => setFeedback(e.target.value)}
                placeholder="e.g. Make it more specific about the scenario tools..."
                data-testid="assist-feedback"
              />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

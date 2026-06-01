import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { JsonSchemaEditor } from '../components/JsonSchemaEditor'
import { AssistPanel } from '../components/AssistPanel'
import { ChatPanel } from '../components/ChatPanel'
import { StatusBadge } from '../components/StatusBadge'
import { ConnectionSnippet } from '../components/ConnectionSnippet'
import type { ToolClass } from '../api/types'

const TOOL_CLASSES: ToolClass[] = ['schema_only', 'crud', 'scenario']

type EditorTab = 'schema' | 'prompt' | 'test'

const S: Record<string, React.CSSProperties> = {
  root: { display: 'flex', flexDirection: 'column', height: '100%', padding: '20px 24px', gap: 20, overflow: 'auto' },
  header: { display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' },
  title: { fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 600, margin: 0 },
  btnPrimary: {
    padding: '7px 16px', background: 'var(--accent)', border: 'none', borderRadius: 5,
    color: '#fff', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 600,
  },
  btnGhost: {
    padding: '7px 16px', background: 'transparent', border: '1px solid var(--border-bright)',
    borderRadius: 5, color: 'var(--text-secondary)', cursor: 'pointer',
    fontFamily: 'var(--font-mono)', fontSize: 12,
  },
  tabs: { display: 'flex', borderBottom: '1px solid var(--border)', gap: 0 },
  tab: {
    padding: '8px 20px', cursor: 'pointer', fontSize: 12, background: 'none', border: 'none',
    color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)',
    borderBottom: '2px solid transparent', marginBottom: -1,
  },
  tabActive: { color: 'var(--text-primary)', borderBottomColor: 'var(--accent)' },
  panel: { flex: 1 },
  field: { marginBottom: 16 },
  label: { fontSize: 10, letterSpacing: '0.1em', color: 'var(--text-dim)', textTransform: 'uppercase', marginBottom: 6, display: 'block' },
  input: {
    width: '100%', padding: '8px 12px', background: 'var(--bg-base)',
    border: '1px solid var(--border)', borderRadius: 5, color: 'var(--text-primary)',
    fontFamily: 'var(--font-mono)', fontSize: 12,
  },
  toolCheck: { display: 'flex', gap: 16, flexWrap: 'wrap' },
  modal: {
    position: 'fixed', inset: 0, background: 'rgba(8,12,22,0.85)', display: 'flex',
    alignItems: 'center', justifyContent: 'center', zIndex: 100, padding: 24,
  },
  modalBox: {
    background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 10,
    padding: 28, maxWidth: 580, width: '100%',
  },
}

export function ModelEdit({ modelId, onBack }: { modelId: string; onBack: () => void }) {
  const qc = useQueryClient()
  const [tab, setTab] = useState<EditorTab>('schema')
  const [showPublishModal, setShowPublishModal] = useState(false)
  const [publishResult, setPublishResult] = useState<{ version: number; endpoint: string } | null>(null)
  const [dirty, setDirty] = useState(false)

  const { data: model, isLoading } = useQuery({
    queryKey: ['model', modelId],
    queryFn: () => api.models.get(modelId),
  })

  // Local edits
  const [name, setName] = useState('')
  const [schema, setSchema] = useState<Record<string, unknown>>({})
  const [prompt, setPrompt] = useState('')
  const [toolClasses, setToolClasses] = useState<ToolClass[]>([])

  // Sync from server on load
  const [synced, setSynced] = useState(false)
  if (model && !synced) {
    setName(model.name)
    setSchema(model.json_schema)
    setPrompt(model.system_prompt ?? '')
    setToolClasses(model.enabled_tool_classes)
    setSynced(true)
  }

  const save = useMutation({
    mutationFn: () =>
      api.models.update(modelId, {
        name, json_schema: schema, system_prompt: prompt, enabled_tool_classes: toolClasses,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['model', modelId] })
      qc.invalidateQueries({ queryKey: ['models'] })
      setDirty(false)
    },
  })

  const publish = useMutation({
    mutationFn: () => api.models.publish(modelId),
    onSuccess: data => {
      qc.invalidateQueries({ queryKey: ['model', modelId] })
      qc.invalidateQueries({ queryKey: ['models'] })
      setPublishResult({ version: data.version, endpoint: data.mcp_endpoint })
      setShowPublishModal(true)
    },
  })

  const unpublish = useMutation({
    mutationFn: () => api.models.unpublish(modelId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['model', modelId] })
      qc.invalidateQueries({ queryKey: ['models'] })
    },
  })

  const toggleTool = (tc: ToolClass) => {
    setToolClasses(prev =>
      prev.includes(tc) ? prev.filter(x => x !== tc) : [...prev, tc]
    )
    setDirty(true)
  }

  if (isLoading) return <div style={{ padding: 40, color: 'var(--text-dim)' }}>loading...</div>
  if (!model) return <div style={{ padding: 40, color: 'var(--red)' }}>Model not found</div>

  const isPublished = model.status === 'published'
  const canEdit = model.status !== 'published'

  return (
    <div style={S.root}>
      {/* Header */}
      <div style={S.header}>
        <button style={{ ...S.btnGhost, padding: '4px 10px', fontSize: 11 }} onClick={onBack}>
          ← back
        </button>
        <h1 style={S.title}>{name || model.id}</h1>
        <StatusBadge status={model.status} />
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          {dirty && canEdit && (
            <button style={S.btnPrimary} onClick={() => save.mutate()} disabled={save.isPending} data-testid="save-btn">
              {save.isPending ? 'saving...' : 'save'}
            </button>
          )}
          {!isPublished ? (
            <button
              style={S.btnPrimary}
              onClick={() => { if (dirty) save.mutate(); else publish.mutate() }}
              disabled={publish.isPending}
              data-testid="publish-btn"
            >
              {publish.isPending ? 'publishing...' : 'publish'}
            </button>
          ) : (
            <button style={S.btnGhost} onClick={() => unpublish.mutate()} disabled={unpublish.isPending} data-testid="unpublish-btn">
              {unpublish.isPending ? '...' : 'unpublish'}
            </button>
          )}
        </span>
      </div>

      {/* Meta */}
      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <div style={{ flex: 1, minWidth: 220 }}>
          <label style={S.label}>model name</label>
          <input style={S.input} value={name} onChange={e => { setName(e.target.value); setDirty(true) }} disabled={!canEdit} data-testid="model-name" />
        </div>
        <div>
          <label style={S.label}>tools enabled</label>
          <div style={S.toolCheck}>
            {TOOL_CLASSES.map(tc => (
              <label key={tc} style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: canEdit ? 'pointer' : 'default', fontSize: 12 }}>
                <input
                  type="checkbox"
                  checked={toolClasses.includes(tc)}
                  onChange={() => canEdit && toggleTool(tc)}
                  style={{ accentColor: 'var(--accent)' }}
                  disabled={!canEdit}
                />
                {tc}
              </label>
            ))}
          </div>
        </div>
      </div>

      {/* Editor tabs */}
      <div style={S.tabs}>
        {(['schema', 'prompt', 'test'] as EditorTab[]).map(t => (
          <button
            key={t}
            style={{ ...S.tab, ...(tab === t ? S.tabActive : {}) }}
            onClick={() => setTab(t)}
            data-testid={`tab-${t}`}
          >
            {t === 'schema' ? '⊞ schema' : t === 'prompt' ? '✦ prompt' : '▶ test'}
          </button>
        ))}
      </div>

      {/* Panel content */}
      <div style={S.panel}>
        {tab === 'schema' && (
          <JsonSchemaEditor
            schema={schema}
            onChange={s => { setSchema(s); setDirty(true) }}
          />
        )}
        {tab === 'prompt' && (
          <AssistPanel
            modelId={modelId}
            currentPrompt={prompt}
            onAccept={p => { setPrompt(p); setDirty(true) }}
          />
        )}
        {tab === 'test' && <ChatPanel modelId={modelId} />}
      </div>

      {/* Publish modal */}
      {showPublishModal && publishResult && (
        <div style={S.modal} onClick={() => setShowPublishModal(false)}>
          <div style={S.modalBox} onClick={e => e.stopPropagation()}>
            <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 16, marginTop: 0, color: 'var(--green)' }}>
              ✓ Published successfully
            </h2>
            <ConnectionSnippet
              modelId={modelId}
              version={publishResult.version}
              endpoint={publishResult.endpoint}
            />
            <div style={{ marginTop: 16, textAlign: 'right' }}>
              <button style={S.btnGhost} onClick={() => setShowPublishModal(false)} data-testid="close-publish-modal">close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

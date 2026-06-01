import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { StatusBadge } from '../components/StatusBadge'
import type { ToolClass } from '../api/types'

const TOOL_CLASSES: ToolClass[] = ['schema_only', 'crud', 'scenario']

const S: Record<string, React.CSSProperties> = {
  root: { padding: '24px 28px', maxWidth: 900, width: '100%' },
  header: { display: 'flex', alignItems: 'center', marginBottom: 24 },
  title: { fontFamily: 'var(--font-display)', fontSize: 22, fontWeight: 700, margin: 0, flex: 1 },
  newBtn: {
    padding: '8px 18px', background: 'var(--accent)', border: 'none', borderRadius: 5,
    color: '#fff', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 600,
  },
  table: { width: '100%', borderCollapse: 'collapse' },
  th: {
    textAlign: 'left', padding: '8px 14px', fontSize: 10,
    letterSpacing: '0.1em', color: 'var(--text-dim)', borderBottom: '1px solid var(--border)',
    textTransform: 'uppercase',
  },
  tr: { borderBottom: '1px solid var(--border)', cursor: 'pointer', transition: 'background 0.1s' },
  td: { padding: '11px 14px', fontSize: 12 },
  idCell: { color: 'var(--accent-bright)', fontFamily: 'var(--font-mono)' },
  actions: { display: 'flex', gap: 6 },
  editBtn: {
    padding: '4px 12px', background: 'transparent', border: '1px solid var(--border-bright)',
    borderRadius: 4, color: 'var(--text-secondary)', cursor: 'pointer',
    fontFamily: 'var(--font-mono)', fontSize: 11,
  },
  empty: { textAlign: 'center', padding: '60px 0', color: 'var(--text-dim)', fontSize: 13 },
  form: {
    background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 8,
    padding: 20, marginBottom: 24,
  },
  formTitle: { fontFamily: 'var(--font-display)', fontSize: 14, marginTop: 0, marginBottom: 16, color: 'var(--text-primary)' },
  input: {
    width: '100%', padding: '8px 12px', background: 'var(--bg-base)',
    border: '1px solid var(--border)', borderRadius: 5, color: 'var(--text-primary)',
    fontFamily: 'var(--font-mono)', fontSize: 12, marginBottom: 12,
  },
  label: { fontSize: 10, letterSpacing: '0.1em', color: 'var(--text-dim)', textTransform: 'uppercase', marginBottom: 6, display: 'block' },
  formRow: { display: 'flex', gap: 8, marginTop: 8 },
  cancelBtn: {
    padding: '7px 14px', background: 'transparent', border: '1px solid var(--border)',
    borderRadius: 5, color: 'var(--text-secondary)', cursor: 'pointer',
    fontFamily: 'var(--font-mono)', fontSize: 12,
  },
}

export function ModelList({ onSelect }: { onSelect: (id: string) => void }) {
  const qc = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [newName, setNewName] = useState('')
  const [newTools, setNewTools] = useState<ToolClass[]>(['schema_only'])

  const { data: models = [], isLoading } = useQuery({
    queryKey: ['models'],
    queryFn: () => api.models.list(),
  })

  const create = useMutation({
    mutationFn: () => api.models.create({
      name: newName,
      enabled_tool_classes: newTools,
      json_schema: {},
    }),
    onSuccess: data => {
      qc.invalidateQueries({ queryKey: ['models'] })
      setShowForm(false)
      setNewName('')
      setNewTools(['schema_only'])
      onSelect(data.id)
    },
  })

  const toggleTool = (tc: ToolClass) =>
    setNewTools(prev => prev.includes(tc) ? prev.filter(x => x !== tc) : [...prev, tc])

  return (
    <div style={S.root}>
      <div style={S.header}>
        <h1 style={S.title}>FORGE</h1>
        <button style={S.newBtn} onClick={() => setShowForm(v => !v)} data-testid="new-model-btn">
          {showForm ? '× cancel' : '+ new model'}
        </button>
      </div>

      {/* Create form */}
      {showForm && (
        <div style={S.form}>
          <h2 style={S.formTitle}>new model</h2>
          <label style={S.label}>name</label>
          <input
            style={S.input}
            value={newName}
            onChange={e => setNewName(e.target.value)}
            placeholder="e.g. Org Readiness"
            data-testid="new-model-name"
            autoFocus
            onKeyDown={e => e.key === 'Enter' && newName.trim() && create.mutate()}
          />
          <label style={S.label}>tools</label>
          <div style={{ display: 'flex', gap: 14, marginBottom: 16 }}>
            {TOOL_CLASSES.map(tc => (
              <label key={tc} style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 12 }}>
                <input type="checkbox" checked={newTools.includes(tc)} onChange={() => toggleTool(tc)}
                  style={{ accentColor: 'var(--accent)' }} />
                {tc}
              </label>
            ))}
          </div>
          <div style={S.formRow}>
            <button
              style={{ ...S.newBtn, opacity: create.isPending || !newName.trim() ? 0.6 : 1 }}
              onClick={() => create.mutate()}
              disabled={create.isPending || !newName.trim()}
              data-testid="create-model-submit"
            >
              {create.isPending ? 'creating...' : 'create →'}
            </button>
            <button style={S.cancelBtn} onClick={() => setShowForm(false)}>cancel</button>
          </div>
          {create.error && (
            <p style={{ color: 'var(--red)', fontSize: 11, marginTop: 8 }}>
              {String((create.error as Error).message)}
            </p>
          )}
        </div>
      )}

      {/* Model table */}
      {isLoading ? (
        <p style={{ color: 'var(--text-dim)' }}>loading...</p>
      ) : models.length === 0 ? (
        <div style={S.empty}>
          <p>no models yet</p>
          <p style={{ fontSize: 11, marginTop: 4 }}>create one to get started</p>
        </div>
      ) : (
        <table style={S.table}>
          <thead>
            <tr>
              <th style={S.th}>id / slug</th>
              <th style={S.th}>name</th>
              <th style={S.th}>status</th>
              <th style={S.th}>version</th>
              <th style={S.th}>updated</th>
              <th style={S.th} />
            </tr>
          </thead>
          <tbody>
            {models.map(m => (
              <tr
                key={m.id}
                style={S.tr}
                onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
                onMouseLeave={e => (e.currentTarget.style.background = '')}
                onClick={() => onSelect(m.id)}
                data-testid={`model-row-${m.id}`}
              >
                <td style={{ ...S.td, ...S.idCell }}>{m.id}</td>
                <td style={S.td}>{m.name}</td>
                <td style={S.td}><StatusBadge status={m.status} /></td>
                <td style={{ ...S.td, color: 'var(--text-secondary)' }}>v{m.current_version}</td>
                <td style={{ ...S.td, color: 'var(--text-dim)', fontSize: 11 }}>
                  {new Date(m.updated_at).toLocaleDateString()}
                </td>
                <td style={S.td}>
                  <div style={S.actions}>
                    <button
                      style={S.editBtn}
                      onClick={e => { e.stopPropagation(); onSelect(m.id) }}
                      data-testid={`edit-${m.id}`}
                    >
                      edit →
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

import { useState } from 'react'
import Editor from '@monaco-editor/react'
import { FieldBuilder } from './FieldBuilder'

const TABS = ['visual', 'json'] as const
type Tab = (typeof TABS)[number]

const S: Record<string, React.CSSProperties> = {
  root: { display: 'flex', flexDirection: 'column', height: '100%' },
  tabs: { display: 'flex', borderBottom: '1px solid var(--border)', marginBottom: 16 },
  tab: {
    padding: '6px 16px', cursor: 'pointer', fontSize: 12, background: 'none', border: 'none',
    color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', borderBottom: '2px solid transparent',
    marginBottom: -1,
  },
  tabActive: { color: 'var(--accent-bright)', borderBottomColor: 'var(--accent)' },
  editorWrap: { flex: 1, border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden', minHeight: 320 },
}

export function JsonSchemaEditor({
  schema,
  onChange,
}: {
  schema: Record<string, unknown>
  onChange: (s: Record<string, unknown>) => void
}) {
  const [tab, setTab] = useState<Tab>('visual')
  const [jsonError, setJsonError] = useState('')

  const handleJsonChange = (value: string | undefined) => {
    try {
      const parsed = JSON.parse(value ?? '{}')
      setJsonError('')
      onChange(parsed)
    } catch {
      setJsonError('invalid JSON')
    }
  }

  return (
    <div style={S.root}>
      <div style={S.tabs}>
        {TABS.map(t => (
          <button
            key={t}
            style={{ ...S.tab, ...(tab === t ? S.tabActive : {}) }}
            onClick={() => setTab(t)}
          >
            {t === 'visual' ? '⊞ visual builder' : '{ } json editor'}
          </button>
        ))}
      </div>

      {tab === 'visual' ? (
        <FieldBuilder schema={schema} onChange={onChange} />
      ) : (
        <>
          <div style={S.editorWrap}>
            <Editor
              height="320px"
              language="json"
              theme="vs-dark"
              value={JSON.stringify(schema, null, 2)}
              onChange={handleJsonChange}
              options={{
                minimap: { enabled: false },
                fontSize: 12,
                fontFamily: "'Geist Mono', 'JetBrains Mono', monospace",
                scrollBeyondLastLine: false,
                lineNumbers: 'on',
                renderLineHighlight: 'none',
                tabSize: 2,
              }}
            />
          </div>
          {jsonError && (
            <p style={{ color: 'var(--red)', fontSize: 11, margin: '6px 0 0' }}>⚠ {jsonError}</p>
          )}
        </>
      )}
    </div>
  )
}

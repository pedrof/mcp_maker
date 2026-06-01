import { useState } from 'react'

type FieldType = 'string' | 'number' | 'integer' | 'boolean' | 'object' | 'array'

interface Field { name: string; type: FieldType; required: boolean }

function schemaToFields(schema: Record<string, unknown>): Field[] {
  const props = (schema.properties ?? {}) as Record<string, { type?: string }>
  const req = new Set((schema.required ?? []) as string[])
  return Object.entries(props).map(([name, def]) => ({
    name,
    type: (def.type ?? 'string') as FieldType,
    required: req.has(name),
  }))
}

function fieldsToSchema(fields: Field[]): Record<string, unknown> {
  const properties: Record<string, { type: string }> = {}
  const required: string[] = []
  for (const f of fields) {
    if (!f.name.trim()) continue
    properties[f.name] = { type: f.type }
    if (f.required) required.push(f.name)
  }
  return {
    $schema: 'https://json-schema.org/draft/2020-12/schema',
    type: 'object',
    properties,
    ...(required.length ? { required } : {}),
  }
}

const S: Record<string, React.CSSProperties> = {
  table: { width: '100%', borderCollapse: 'collapse' },
  th: {
    textAlign: 'left', padding: '6px 10px', fontSize: 10,
    letterSpacing: '0.1em', color: 'var(--text-dim)',
    borderBottom: '1px solid var(--border)', textTransform: 'uppercase',
  },
  td: { padding: '4px 6px', borderBottom: '1px solid var(--border)' },
  input: {
    background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: 4,
    padding: '4px 8px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)',
    fontSize: 12, width: '100%',
  },
  select: {
    background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: 4,
    padding: '4px 8px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)',
    fontSize: 12, width: '100%',
  },
  addBtn: {
    marginTop: 12, padding: '6px 14px', background: 'transparent',
    border: '1px dashed var(--border-bright)', borderRadius: 4,
    color: 'var(--text-secondary)', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: 12,
  },
  delBtn: {
    padding: '2px 8px', background: 'transparent', border: 'none',
    color: 'var(--text-dim)', cursor: 'pointer', fontSize: 14, lineHeight: 1,
  },
}

export function FieldBuilder({
  schema,
  onChange,
}: {
  schema: Record<string, unknown>
  onChange: (s: Record<string, unknown>) => void
}) {
  const [fields, setFields] = useState<Field[]>(() => schemaToFields(schema))

  const update = (updated: Field[]) => {
    setFields(updated)
    onChange(fieldsToSchema(updated))
  }

  const setField = (i: number, patch: Partial<Field>) => {
    const next = fields.map((f, idx) => idx === i ? { ...f, ...patch } : f)
    update(next)
  }

  const addField = () =>
    update([...fields, { name: '', type: 'string', required: false }])

  const removeField = (i: number) =>
    update(fields.filter((_, idx) => idx !== i))

  return (
    <div>
      <table style={S.table}>
        <thead>
          <tr>
            <th style={S.th}>field name</th>
            <th style={S.th}>type</th>
            <th style={{ ...S.th, textAlign: 'center' }}>req</th>
            <th style={S.th} />
          </tr>
        </thead>
        <tbody>
          {fields.map((f, i) => (
            <tr key={i}>
              <td style={S.td}>
                <input
                  style={S.input}
                  value={f.name}
                  placeholder="field_name"
                  onChange={e => setField(i, { name: e.target.value })}
                />
              </td>
              <td style={S.td}>
                <select style={S.select} value={f.type} onChange={e => setField(i, { type: e.target.value as FieldType })}>
                  {(['string', 'number', 'integer', 'boolean', 'object', 'array'] as FieldType[]).map(t => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
              </td>
              <td style={{ ...S.td, textAlign: 'center' }}>
                <input
                  type="checkbox"
                  checked={f.required}
                  onChange={e => setField(i, { required: e.target.checked })}
                  style={{ accentColor: 'var(--accent)' }}
                />
              </td>
              <td style={S.td}>
                <button style={S.delBtn} onClick={() => removeField(i)} title="remove field">×</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button style={S.addBtn} onClick={addField}>+ add field</button>
    </div>
  )
}

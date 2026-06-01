import type { ModelStatus } from '../api/types'

const cfg: Record<ModelStatus, { label: string; color: string; dot: string }> = {
  draft:       { label: 'draft',       color: '#484f58', dot: '#6e7681' },
  published:   { label: 'published',   color: '#1a3a27', dot: '#3fb950' },
  unpublished: { label: 'unpublished', color: '#3a2a08', dot: '#d29922' },
}

export function StatusBadge({ status }: { status: ModelStatus }) {
  const { label, color, dot } = cfg[status]
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      padding: '2px 8px', borderRadius: 4, fontSize: 11,
      background: color, color: 'var(--text-primary)',
      fontFamily: 'var(--font-mono)', letterSpacing: '0.05em',
    }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: dot, flexShrink: 0 }} />
      {label}
    </span>
  )
}

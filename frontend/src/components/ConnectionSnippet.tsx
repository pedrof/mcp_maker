import { useState } from 'react'

const S: Record<string, React.CSSProperties> = {
  wrap: { background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 8, padding: 20 },
  label: { fontSize: 10, letterSpacing: '0.12em', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: 6 },
  code: {
    display: 'block', background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: 6,
    padding: '10px 14px', fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--accent-bright)',
    whiteSpace: 'pre-wrap', wordBreak: 'break-all', margin: '0 0 12px',
  },
  btn: {
    padding: '4px 12px', background: 'transparent', border: '1px solid var(--border-bright)',
    borderRadius: 4, color: 'var(--text-secondary)', cursor: 'pointer', fontSize: 11,
    fontFamily: 'var(--font-mono)',
  },
  copied: { color: 'var(--green)', borderColor: 'var(--green)' },
}

function CopyBtn({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard.writeText(text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 2000) })
  }
  return (
    <button style={{ ...S.btn, ...(copied ? S.copied : {}) }} onClick={copy}>
      {copied ? '✓ copied' : 'copy'}
    </button>
  )
}

export function ConnectionSnippet({ modelId, version, endpoint }: {
  modelId: string; version: number; endpoint: string
}) {
  const origin = window.location.origin
  const fullEndpoint = `${origin}${endpoint}`
  const snippet = JSON.stringify({
    mcpServers: {
      [modelId]: {
        command: 'npx',
        args: ['-y', '@modelcontextprotocol/inspector'],
        env: { MCP_SERVER_URL: fullEndpoint },
      },
    },
  }, null, 2)

  return (
    <div style={S.wrap}>
      <p style={{ ...S.label, marginBottom: 16, fontSize: 11, color: 'var(--green)' }}>
        ✓ Published · version {version}
      </p>

      <div style={S.label}>MCP endpoint</div>
      <code style={S.code}>{fullEndpoint}</code>
      <CopyBtn text={fullEndpoint} />

      <div style={{ height: 16 }} />

      <div style={S.label}>claude_desktop_config.json snippet</div>
      <code style={S.code}>{snippet}</code>
      <CopyBtn text={snippet} />
    </div>
  )
}

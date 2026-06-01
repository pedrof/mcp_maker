import { useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ModelList } from './pages/ModelList'
import { ModelEdit } from './pages/ModelEdit'

const qc = new QueryClient({ defaultOptions: { queries: { staleTime: 10_000 } } })

const S: Record<string, React.CSSProperties> = {
  app: { display: 'flex', height: '100vh', overflow: 'hidden', background: 'var(--bg-base)' },
  sidebar: {
    width: 220, background: 'var(--bg-sidebar)', borderRight: '1px solid var(--border)',
    display: 'flex', flexDirection: 'column', flexShrink: 0,
  },
  logo: {
    padding: '18px 20px 14px', borderBottom: '1px solid var(--border)',
    fontFamily: 'var(--font-display)', fontSize: 15, fontWeight: 700,
    color: 'var(--accent-bright)', letterSpacing: '0.05em',
  },
  logoSub: { fontSize: 9, color: 'var(--text-dim)', display: 'block', letterSpacing: '0.15em', marginTop: 2 },
  navItem: {
    padding: '9px 20px', fontSize: 12, cursor: 'pointer', color: 'var(--text-secondary)',
    display: 'flex', alignItems: 'center', gap: 8,
    borderLeft: '2px solid transparent', transition: 'all 0.1s',
  },
  navActive: { color: 'var(--text-primary)', background: 'var(--bg-hover)', borderLeftColor: 'var(--accent)' },
  main: { flex: 1, overflow: 'auto', display: 'flex', flexDirection: 'column' },
}

function App() {
  const [selectedId, setSelectedId] = useState<string | null>(null)

  return (
    <QueryClientProvider client={qc}>
      <div style={S.app}>
        <aside style={S.sidebar}>
          <div style={S.logo}>
            FORGE
            <span style={S.logoSub}>MCP AUTHORING</span>
          </div>
          <nav style={{ paddingTop: 8 }}>
            <div
              style={{ ...S.navItem, ...(!selectedId ? S.navActive : {}) }}
              onClick={() => setSelectedId(null)}
              data-testid="nav-models"
            >
              <span>⊞</span> models
            </div>
            {selectedId && (
              <div style={{ ...S.navItem, ...S.navActive, cursor: 'default' }}>
                <span style={{ color: 'var(--accent)' }}>›</span>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 11 }}>
                  {selectedId}
                </span>
              </div>
            )}
          </nav>
          <div style={{ flex: 1 }} />
          <div style={{ padding: '12px 20px', fontSize: 10, color: 'var(--text-dim)', borderTop: '1px solid var(--border)' }}>
            forge · mcp platform
          </div>
        </aside>
        <main style={S.main}>
          {selectedId ? (
            <ModelEdit modelId={selectedId} onBack={() => setSelectedId(null)} />
          ) : (
            <ModelList onSelect={id => setSelectedId(id)} />
          )}
        </main>
      </div>
    </QueryClientProvider>
  )
}

export default App

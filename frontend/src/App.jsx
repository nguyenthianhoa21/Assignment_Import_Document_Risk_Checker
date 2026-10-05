import { useEffect, useState } from ''react''
import { api } from ''./api''

export default function App() {
  const [health, setHealth] = useState(null)
  const [db, setDb] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.get(''/health'')
      .then((r) => {
        setHealth(r.data)
        return api.get(''/health/db'')
      })
      .then((r) => setDb(r.data))
      .catch((e) => setError(e.message))
  }, [])

  return (
    <main className="shell">
      <header className="topbar">
        <h1>Import Document Risk Checker</h1>
        <span className="version">v{health?.version ?? ''0.1.0''}</span>
      </header>

      <section className="hero">
        <h2>AI-assisted cross-document risk checking</h2>
        <p>
          Upload a shipment document set (Commercial Invoice, Packing List, Bill of
          Lading). The system classifies each document, extracts key fields and runs
          cross-document consistency checks.
        </p>
        <div className={'status ' + (error ? 'err' : health ? 'ok' : '')}>
          {error
            ? 'Backend offline: ' + error
            : health
              ? 'Backend online · ' + db?.database + ' (' + db?.dialect + ') · AI: ' + health.ai_provider
              : 'Checking backend...'}
        </div>
      </section>

      <section className="cards">
        <div className="card">
          <h3>Planned modules</h3>
          <ol>
            <li>Upload &amp; document classification</li>
            <li>AI extraction with confidence</li>
            <li>Cross-document validation &amp; risk flags</li>
            <li>History of processed shipments</li>
          </ol>
        </div>
      </section>
    </main>
  )
}

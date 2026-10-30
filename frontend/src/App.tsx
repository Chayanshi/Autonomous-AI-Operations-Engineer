import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import { AiWidget } from './components/AiWidget'
import { ApprovalCard, DetailTabs, OutcomeBanner } from './components/Details'
import { Pipeline } from './components/Pipeline'
import { Guardrails, RunForm } from './components/Sidebar'
import { formatElapsed } from './format'
import type { AiSettings, Status } from './types'
import { useRun } from './useRun'

export default function App() {
  const [status, setStatus] = useState<Status | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [now, setNow] = useState(Date.now())
  const [settings, setSettings] = useState<AiSettings | null>(null)
  const [panelOpen, setPanelOpen] = useState(false)

  const refresh = useCallback(() => {
    api
      .status()
      .then((next) => {
        setStatus(next)
        setStatusError(null)
      })
      .catch(() => setStatusError('Backend unreachable — start it with: uvicorn server:app --port 8001'))
    api.settings().then(setSettings).catch(() => undefined)
  }, [])
  const { view, error, start, decide, clear } = useRun(refresh)

  useEffect(refresh, [refresh])
  const active = view.state !== 'idle' && view.state !== 'completed'
  useEffect(() => {
    if (!active) return
    const timer = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(timer)
  }, [active])

  const reset = async () => {
    try {
      await api.reset()
      clear()
      refresh()
    } catch (caught) {
      setStatusError((caught as Error).message)
    }
  }

  const isLive = view.model !== null && view.model.provider !== 'mock'
  const runProvider = settings?.providers.find((item) => item.name === view.model?.provider)
  const modified = status?.targets.filter((target) => target.baseline_clean === false) ?? []
  const runTarget = status?.targets.find((target) => target.name === view.request?.target)
  const elapsed = view.startedAt ? formatElapsed((view.finishedAt ?? now) - view.startedAt) : null

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <div className="logo">◆</div>
          <div>
            <div className="brand-name">OpsPilot</div>
            <div className="brand-sub">Autonomous AI Operations Engineer</div>
          </div>
        </div>
        <div className="topbar-right">
          {status && (
            <span
              className={`pill ${modified.length ? 'warn' : 'neutral'}`}
              title="Whether each target's app.py still contains its original bug (compared with git)"
            >
              {modified.length
                ? `Fixed, not reset: ${modified.map((target) => target.name).join(', ')}`
                : `${status.targets.length} targets · all bugs in place`}
            </span>
          )}
          <button className="ghost small" onClick={reset} disabled={active || !status} title="Restore every target's app.py from git">
            ⟲ Reset targets
          </button>
        </div>
      </header>

      {(statusError || error) && <div className="alert">{statusError ?? error}</div>}

      <main className="layout">
        <aside className="sidebar">
          <RunForm status={status} settings={settings} busy={active} onRun={start} onOpenSettings={() => setPanelOpen(true)} />
          <Guardrails status={status} counters={view.counters} usage={view.usage} tokenBudget={view.tokenBudget} />
        </aside>

        <section className="main">
          {view.state === 'idle' ? (
            <div className="card empty-state">
              <h1>Give the agent an objective, not a ticket.</h1>
              <p className="muted">
                OpsPilot explores the repository with bounded tools, reproduces the failure, diagnoses the root cause and proposes a
                minimal patch. You approve it. The patch is applied and the full test suite runs again. The result is only marked
                verified if those tests pass; otherwise the change is rolled back.
              </p>
              <Pipeline view={view} />
            </div>
          ) : (
            <>
              <div className="run-head">
                <div>
                  <div className="eyebrow">
                    Run {view.runId} · {runTarget?.title ?? view.request?.target}
                  </div>
                  <div className="objective">{view.request?.objective}</div>
                </div>
                <div className="run-meta">
                  <span className={`pill ${isLive ? 'ok' : 'mock'}`}>
                    {isLive ? `LIVE · ${runProvider?.label ?? view.model?.provider} · ${view.model?.model}` :`MOCK · scripted policy${view.request?.scenario === 'bad-patch' ? ' · wrong-fix scenario' : ''}`}
                  </span>
                  {elapsed && <span className="mono muted">{elapsed}</span>}
                </div>
              </div>
              <div className="card">
                <Pipeline view={view} />
              </div>
              <OutcomeBanner view={view} />
              {(view.state === 'awaiting_approval' || view.state === 'verifying') && <ApprovalCard view={view} onDecide={decide} />}
              <DetailTabs view={view} />
            </>
          )}
        </section>
      </main>

      <footer className="footer">
        Tools, tests, patching and rollback are real in both modes. Mock mode replaces only the model's decisions with a labelled
        scripted policy.
      </footer>

      <AiWidget
        settings={settings}
        open={panelOpen}
        locked={active}
        runUsage={view.usage}
        onToggle={setPanelOpen}
        onSaved={setSettings}
      />
    </div>
  )
}

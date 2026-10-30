import { useEffect, useState } from 'react'
import { describeStep, testPassed, testSummary } from '../format'
import type { RunView } from '../useRun'
import type { TestRun } from '../types'

export function DiffView({ diff }: { diff: string }) {
  return (
    <pre className="diff">
      {diff.split('\n').map((line, index) => {
        const kind = line.startsWith('+++') || line.startsWith('---') ? 'meta' : line.startsWith('@@') ? 'hunk' : line[0] === '+' ? 'add' : line[0] === '-' ? 'del' : ''
        return (
          <div key={index} className={kind}>
            {line || ' '}
          </div>
        )
      })}
    </pre>
  )
}

export function ApprovalCard({ view, onDecide }: { view: RunView; onDecide: (decision: 'approve' | 'reject') => void }) {
  if (!view.proposal || !view.diff) return null
  const deciding = view.state !== 'awaiting_approval'
  return (
    <section className="card approval">
      <div className="approval-head">
        <div>
          <div className="eyebrow warn">{deciding ? 'Approved · verifying' : 'Approval required'}</div>
          <h2>
            {deciding ? 'Applying' : 'The agent proposes'} a change to {view.proposal.relative_path}
          </h2>
          <p className="muted">
            {deciding
              ? 'This exact diff is being written and the full test suite is running. If any test fails, the original file is restored.'
              : 'Nothing has been written yet. Approving applies exactly this diff, then runs the full test suite. If any test fails, the original file is restored.'}
          </p>
        </div>
      </div>
      <DiffView diff={view.diff} />
      <div className="actions">
        <button className="ghost" onClick={() => onDecide('reject')} disabled={deciding}>
          Reject
        </button>
        <button className="primary" onClick={() => onDecide('approve')} disabled={deciding}>
          Approve &amp; verify →
        </button>
      </div>
    </section>
  )
}

const OUTCOME_COPY = {
  verified: { title: 'Verified', tone: 'ok' },
  not_verified: { title: 'Not verified', tone: 'bad' },
  rejected: { title: 'Rejected', tone: 'neutral' },
  error: { title: 'Error', tone: 'bad' },
} as const

export function OutcomeBanner({ view }: { view: RunView }) {
  if (!view.outcome) return null
  const copy = OUTCOME_COPY[view.outcome.status]
  const result = view.outcome.patch_result
  return (
    <section className={`banner ${copy.tone}`}>
      <div className="banner-title">{copy.title}</div>
      <div>
        <div>{view.outcome.message}</div>
        {result && (
          <div className="mono small">
            {result.patch.relative_path} sha256 {result.patch.original_sha256.slice(0, 10)} → {result.patch.updated_sha256.slice(0, 10)}
            {result.rolled_back ? ' · rolled back' : ''}
          </div>
        )}
      </div>
    </section>
  )
}

function TestBlock({ title, run }: { title: string; run: TestRun | undefined }) {
  if (!run) {
    return (
      <div className="test-block empty">
        <div className="test-title">{title}</div>
        <div className="muted">Not run</div>
      </div>
    )
  }
  return (
    <div className={`test-block ${testPassed(run) ? 'ok' : 'bad'}`}>
      <div className="test-title">
        {title}
        <span className="chip">{testPassed(run) ? 'passed' : run.timed_out ? 'timed out' : 'failed'}</span>
      </div>
      <div className="mono">{testSummary(run)}</div>
      <details>
        <summary>pytest output</summary>
        <pre className="output">{run.stdout || run.stderr || '(empty)'}</pre>
      </details>
    </div>
  )
}

type Tab = 'activity' | 'diagnosis' | 'patch' | 'tests' | 'raw'

export function DetailTabs({ view }: { view: RunView }) {
  const [tab, setTab] = useState<Tab>('activity')
  useEffect(() => {
    if (view.outcome) setTab(view.outcome.patch_result ? 'tests' : 'diagnosis')
  }, [view.outcome])
  useEffect(() => setTab('activity'), [view.runId])

  const report = view.report
  const before = report?.test_command.runs[0]
  const after = view.outcome?.patch_result?.verification
  const tabs: [Tab, string][] = [
    ['activity', `Agent activity (${view.steps.length})`],
    ['diagnosis', 'Diagnosis'],
    ['patch', 'Patch'],
    ['tests', 'Tests'],
    ['raw', 'Raw evidence'],
  ]

  return (
    <section className="card tabs">
      <nav>
        {tabs.map(([key, label]) => (
          <button key={key} className={tab === key ? 'on' : ''} onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </nav>

      {tab === 'activity' && (
        <ol className="log">
          {view.steps.map((step) => {
            const info = describeStep(step.entry)
            return (
              <li key={step.id} className={info.tone}>
                <span className="eid">{step.id}</span>
                <span className="mono">{info.label}</span>
                <span className="outcome">{info.outcome}</span>
              </li>
            )
          })}
          {view.pending.map((call) => (
            <li key={call.id} className="running">
              <span className="eid">…</span>
              <span className="mono">{call.name}()</span>
              <span className="outcome">running{call.name === 'run_tests' ? ' pytest (takes a few seconds)' : ''}</span>
            </li>
          ))}
          {view.state === 'verifying' && (
            <li className="running">
              <span className="eid">…</span>
              <span className="mono">apply approved patch</span>
              <span className="outcome">writing file and running full pytest suite</span>
            </li>
          )}
          {!view.steps.length && !view.pending.length && <li className="muted">Waiting for the model's first tool call…</li>}
        </ol>
      )}

      {tab === 'diagnosis' &&
        (report ? (
          <div className="diagnosis">
            <div className="eyebrow">Model hypothesis · not a verified fact</div>
            <p className="hypothesis">{report.likely_root_cause.hypothesis ?? report.likely_root_cause.raw_response ?? 'No diagnosis returned.'}</p>
            <div className="eyebrow">Observed evidence</div>
            <ul>
              {report.verified_facts.map((fact) => (
                <li key={fact} className="mono small">
                  {fact}
                </li>
              ))}
              <li className="small">Files inspected: {report.files_inspected.join(', ') || 'none'}</li>
            </ul>
            <div className="eyebrow">Recommended next action</div>
            <p>{report.recommended_next_action}</p>
          </div>
        ) : (
          <p className="muted">The diagnosis appears when the investigation finishes.</p>
        ))}

      {tab === 'patch' &&
        (view.diff ? <DiffView diff={view.diff} /> : <p className="muted">{report ? 'No patch was proposed in this run.' : 'No patch yet.'}</p>)}

      {tab === 'tests' && (
        <div className="tests">
          <TestBlock title="Before patch" run={before} />
          <TestBlock title="After patch" run={after} />
        </div>
      )}

      {tab === 'raw' &&
        (report ? (
          <div>
            <button
              className="ghost small"
              onClick={() => {
                const blob = new Blob([JSON.stringify({ report, outcome: view.outcome }, null, 2)], { type: 'application/json' })
                const link = document.createElement('a')
                link.href = URL.createObjectURL(blob)
                link.download = `opspilot-run-${view.runId}.json`
                link.click()
                URL.revokeObjectURL(link.href)
              }}
            >
              Download report JSON
            </button>
            <pre className="output raw">{JSON.stringify({ outcome: view.outcome, ...report }, null, 2)}</pre>
          </div>
        ) : (
          <p className="muted">Available when the investigation finishes.</p>
        ))}
    </section>
  )
}

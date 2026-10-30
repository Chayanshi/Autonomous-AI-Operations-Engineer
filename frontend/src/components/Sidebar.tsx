import { useState } from 'react'
import { formatTokens } from '../format'
import type { AiSettings, Counters, RunRequest, Status, Usage } from '../types'

// Plain-language explanations for people who don't know the internals.
const MOCK_NOTE =
  'Mock: a pre-written script plays the role of the AI so the demo works without an AI service. Everything else is real: the files are really read, the tests really run, and changes are really applied and checked.'

const SCENARIO_NOTES: Record<RunRequest['scenario'], string> = {
  fix: 'Correct fix: the agent finds the bug and proposes the right change. After you approve it, the tests run again and pass, so the result is marked Verified.',
  'bad-patch':
    'Wrong fix: the agent deliberately proposes a change that does not solve the problem. After you approve it, the tests still fail, so the change is automatically undone. This shows the system never keeps a fix it cannot prove.',
}

type FormProps = {
  status: Status | null
  settings: AiSettings | null
  busy: boolean
  onRun: (request: RunRequest) => void
  onOpenSettings: () => void
}

export function RunForm({ status, settings, busy, onRun, onOpenSettings }: FormProps) {
  const [objective, setObjective] = useState('')
  const [scenario, setScenario] = useState<RunRequest['scenario']>('fix')
  const [allowPatch, setAllowPatch] = useState(true)
  const [targetName, setTargetName] = useState<string | null>(null)
  const provider = settings?.providers.find((item) => item.name === settings.provider)
  const isMock = settings?.provider === 'mock'
  const targets = status?.targets ?? []
  const target = targets.find((item) => item.name === (targetName ?? status?.default_target)) ?? targets[0]
  const text = objective || target?.objective || ''

  return (
    <form
      className="card form"
      onSubmit={(event) => {
        event.preventDefault()
        if (target) onRun({ target: target.name, objective: text, scenario, allow_patch: allowPatch })
      }}
    >
      <div className="eyebrow">New investigation</div>
      <label className="field">
        <span>Target app (what is broken)</span>
        <select
          value={target?.name ?? ''}
          onChange={(event) => {
            setTargetName(event.target.value)
            setObjective('') // use the new target's own objective
          }}
          disabled={busy || !targets.length}
        >
          {targets.map((item) => (
            <option key={item.name} value={item.name}>
              {item.title}
            </option>
          ))}
        </select>
        {target && (
          <p className="note">
            {target.symptom}
            {target.baseline_clean === false && <strong> This app has already been fixed; click Reset targets to bring the bug back.</strong>}
          </p>
        )}
      </label>

      <label className="field">
        <span>Engineering objective</span>
        <textarea
          rows={4}
          maxLength={500}
          value={text}
          onChange={(event) => setObjective(event.target.value)}
          disabled={busy}
        />
      </label>

      <div className="field">
        <span>AI provider</span>
        <div className="provider-line">
          <span>
            <strong>{provider?.label ?? '…'}</strong>
            {provider?.model && <code>{provider.model}</code>}
          </span>
          <button type="button" className="ghost small" onClick={onOpenSettings} disabled={busy}>
            Change
          </button>
        </div>
        <p className="note">
          {isMock ? MOCK_NOTE : `${provider?.label}: a real AI model decides what to look at and what to fix, step by step, using your API key.`}
        </p>
        {provider && !provider.ready && <small className="hint warn-text">No API key yet: open AI settings to add one.</small>}
      </div>

      {isMock && (
        <label className="field">
          <span>Mock scenario</span>
          <select value={scenario} onChange={(event) => setScenario(event.target.value as RunRequest['scenario'])} disabled={busy}>
            <option value="fix">Correct fix → verified</option>
            <option value="bad-patch">Wrong fix → rollback demo</option>
          </select>
          <p className="note">{SCENARIO_NOTES[scenario]}</p>
        </label>
      )}

      <label className="check">
        <input type="checkbox" checked={allowPatch} onChange={(event) => setAllowPatch(event.target.checked)} disabled={busy} />
        <span>
          Allow a patch proposal for <code>{status?.patch_path ?? 'app.py'}</code>
          <small>
            {allowPatch
              ? 'On: the agent may suggest a code change. You see it first and decide; nothing is changed without your approval.'
              : 'Off: the agent only investigates and explains the problem. It cannot suggest or make any change.'}
          </small>
        </span>
      </label>

      <button className="primary" type="submit" disabled={busy || !status || !text.trim() || !provider?.ready}>
        {busy ? 'Run in progress…' : 'Run investigation →'}
      </button>
    </form>
  )
}

type GuardrailProps = { status: Status | null; counters: Counters | null; usage: Usage | null; tokenBudget: number | null }

const COUNTER_LABELS: [keyof Counters, string][] = [
  ['model_turns', 'Model turns'],
  ['tool_calls', 'Tool calls'],
  ['tool_errors', 'Tool errors'],
  ['patch_attempts', 'Patch attempts'],
]

export function Guardrails({ status, counters, usage, tokenBudget }: GuardrailProps) {
  const tokens = usage ? usage.input_tokens + usage.output_tokens : 0
  return (
    <section className="card guardrails">
      <div className="eyebrow">Guardrails</div>
      {tokenBudget !== null && (
        <div className="meter">
          <div className="meter-row">
            <span>Tokens (this run)</span>
            <span className="mono">
              {usage && !usage.usage_reported ? 'not reported' : `${formatTokens(tokens)} / ${formatTokens(tokenBudget)}`}
            </span>
          </div>
          <div className="bar">
            <div style={{ width: `${Math.min(100, (tokens / tokenBudget) * 100)}%` }} />
          </div>
        </div>
      )}
      {status &&
        COUNTER_LABELS.map(([key, label]) => {
          const used = counters?.[key] ?? 0
          const limit = status.limits[key]
          return (
            <div className="meter" key={key}>
              <div className="meter-row">
                <span>{label}</span>
                <span className="mono">
                  {used} / {limit}
                </span>
              </div>
              <div className="bar">
                <div style={{ width: `${Math.min(100, (used / limit) * 100)}%` }} />
              </div>
            </div>
          )
        })}
      <ul className="rules">
        <li>Allowlisted tools only — no shell, no network</li>
        <li>Reads confined to the repository; secrets never sent to the model</li>
        <li>
          Only <code>{status?.patch_path ?? 'app.py'}</code> may change, one exact-text edit
        </li>
        <li>Human approval before any write</li>
        <li>Full pytest run after the patch; automatic rollback on failure</li>
      </ul>
    </section>
  )
}

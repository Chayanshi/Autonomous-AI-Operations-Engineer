import { useEffect, useState } from 'react'
import { api } from '../api'
import { formatTokens } from '../format'
import type { AiSettings, ProviderName, SettingsUpdate, Usage } from '../types'

type Props = {
  settings: AiSettings | null
  open: boolean
  locked: boolean
  runUsage: Usage | null
  onToggle: (open: boolean) => void
  onSaved: (settings: AiSettings) => void
}

const KEY_SOURCE_COPY = {
  user: 'Using the key you entered (kept in server memory only)',
  environment: 'Using the key from backend/.env',
} as const

const total = (usage: Usage | null | undefined) => (usage ? usage.input_tokens + usage.output_tokens : 0)

export function AiWidget({ settings, open, locked, runUsage, onToggle, onSaved }: Props) {
  const [provider, setProvider] = useState<ProviderName>('mock')
  const [model, setModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [maxOutput, setMaxOutput] = useState(2048)
  const [budget, setBudget] = useState(100_000)
  const [message, setMessage] = useState<{ tone: 'ok' | 'bad' | 'neutral'; text: string } | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open || !settings) return
    setProvider(settings.provider)
    setModel('')
    setApiKey('')
    setMaxOutput(settings.max_output_tokens)
    setBudget(settings.run_token_budget)
    setMessage(null)
    // Only when the panel opens: refreshing settings after a save must not wipe the form or its message.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  if (!settings) return null
  const current = settings.providers.find((item) => item.name === settings.provider)
  const selected = settings.providers.find((item) => item.name === provider)
  const isLive = provider !== 'mock'
  const sessionTokens = total(settings.session_usage) + (locked ? total(runUsage) : 0)

  const save = async (): Promise<boolean> => {
    const body: SettingsUpdate = { provider, max_output_tokens: maxOutput, run_token_budget: budget }
    if (isLive && model.trim()) body.model = model.trim()
    if (isLive && apiKey.trim()) body.api_key = apiKey.trim()
    setSaving(true)
    try {
      const next = await api.updateSettings(body)
      onSaved(next)
      setApiKey('')
      setModel('')
      setMessage({ tone: 'ok', text: 'Saved.' })
      return true
    } catch (caught) {
      setMessage({ tone: 'bad', text: (caught as Error).message })
      return false
    } finally {
      setSaving(false)
    }
  }

  const test = async () => {
    if (!(await save())) return
    setMessage({ tone: 'neutral', text: 'Testing connection…' })
    try {
      const result = await api.testConnection()
      setMessage({ tone: result.ok ? 'ok' : 'bad', text: result.ok ? `${result.message} (${result.model})` : `Failed: ${explain(result.message)}` })
      onSaved(await api.settings())
    } catch (caught) {
      setMessage({ tone: 'bad', text: (caught as Error).message })
    }
  }

  const removeKey = async () => {
    try {
      onSaved(await api.updateSettings({ provider, clear_key: true }))
      setMessage({ tone: 'neutral', text: 'Your key was removed from server memory.' })
    } catch (caught) {
      setMessage({ tone: 'bad', text: (caught as Error).message })
    }
  }

  return (
    <div className="ai-widget">
      {open && (
        <section className="ai-panel card" role="dialog" aria-label="AI provider settings">
          <header className="ai-panel-head">
            <div>
              <h2>AI provider</h2>
              <p className="muted small">Choose who drives the agent, bring your own key, and cap token use.</p>
            </div>
            <button className="ghost small" onClick={() => onToggle(false)} aria-label="Close">
              ✕
            </button>
          </header>
          {locked && <p className="note">A run is in progress. Settings are locked until it finishes.</p>}

          <fieldset className="providers" disabled={locked || saving}>
            {settings.providers.map((item) => (
              <label key={item.name} className={`provider-option ${provider === item.name ? 'on' : ''}`}>
                <input type="radio" name="provider" checked={provider === item.name} onChange={() => setProvider(item.name)} />
                <span>
                  <span className="provider-title">
                    {item.label}
                    <span className={`chip ${item.ready ? 'ok' : 'warn'}`}>{item.name === 'mock' ? 'offline' : item.ready ? 'key ready' : 'needs key'}</span>
                  </span>
                  <small>{item.note}</small>
                </span>
              </label>
            ))}
          </fieldset>

          {isLive && selected && (
            <fieldset className="ai-fields" disabled={locked || saving}>
              <label className="field">
                <span>Model</span>
                <input value={model} onChange={(event) => setModel(event.target.value)} placeholder={selected.model ?? selected.default_model ?? ''} />
                <small className="hint">Leave empty to keep {selected.model}. Default: {selected.default_model}.</small>
              </label>
              <label className="field">
                <span>API key</span>
                <input
                  type="password"
                  autoComplete="off"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  placeholder={selected.key_source ? '•••••••• (saved, hidden)' : `Paste your ${selected.label} key`}
                />
                <small className="hint">
                  {selected.key_source ? KEY_SOURCE_COPY[selected.key_source] : `Or set ${selected.key_variable} in backend/.env.`} The key is
                  never shown again, saved to disk, or sent to the browser.
                </small>
              </label>
              {selected.key_source === 'user' && (
                <button type="button" className="ghost small" onClick={removeKey}>
                  Remove my key
                </button>
              )}
            </fieldset>
          )}

          <fieldset className="ai-fields" disabled={locked || saving}>
            <div className="field">
              <span className="meter-row">
                <span>Max output tokens per model call</span>
                <span className="mono">{maxOutput.toLocaleString()}</span>
              </span>
              <input
                type="range"
                min={settings.bounds.max_output_tokens[0]}
                max={settings.bounds.max_output_tokens[1]}
                step={256}
                value={maxOutput}
                onChange={(event) => setMaxOutput(Number(event.target.value))}
              />
              <small className="hint">How long each AI reply may be. Raise it if answers get cut off.</small>
            </div>
            <div className="field">
              <span className="meter-row">
                <span>Token budget per run</span>
                <span className="mono">{formatTokens(budget)}</span>
              </span>
              <input
                type="range"
                min={settings.bounds.run_token_budget[0]}
                max={settings.bounds.run_token_budget[1]}
                step={10_000}
                value={budget}
                onChange={(event) => setBudget(Number(event.target.value))}
              />
              <small className="hint">The server stops the agent once a run has used this many tokens (input + output).</small>
            </div>
          </fieldset>

          <div className="actions">
            {isLive && (
              <button className="ghost" onClick={test} disabled={locked || saving || (!selected?.ready && !apiKey.trim())}>
                Test connection
              </button>
            )}
            <button className="primary" onClick={save} disabled={locked || saving}>
              Save
            </button>
          </div>
          {message && <p className={`ai-message ${message.tone}`}>{message.text}</p>}

          <div className="usage">
            <div className="eyebrow">Usage</div>
            <UsageRow label="This run" usage={locked ? runUsage : settings.last_run_usage} />
            <UsageRow label={`Session · ${settings.session_usage.runs} runs`} usage={settings.session_usage} />
            <small className="hint">
              Counted from what the provider reports. Mock uses no tokens. Totals reset when the backend restarts.
            </small>
          </div>
        </section>
      )}

      <button className={`ai-fab ${current?.ready ? '' : 'warn'}`} onClick={() => onToggle(!open)} aria-expanded={open}>
        <span className="ai-fab-icon">✦</span>
        <span>
          <strong>{current?.label ?? 'AI'}</strong>
          <small>{settings.provider === 'mock' ? 'no tokens used' : `${formatTokens(sessionTokens)} tokens this session`}</small>
        </span>
      </button>
    </div>
  )
}

function UsageRow({ label, usage }: { label: string; usage: Usage | null | undefined }) {
  return (
    <div className="usage-row">
      <span>{label}</span>
      <span className="mono">
        {!usage
          ? '—'
          : !usage.usage_reported
            ? 'not reported by provider'
            : `${formatTokens(usage.input_tokens)} in · ${formatTokens(usage.output_tokens)} out · ${usage.model_calls} calls`}
      </span>
    </div>
  )
}

function explain(errorType: string): string {
  const hints: Record<string, string> = {
    AuthenticationError: 'the API key was rejected',
    PermissionDeniedError: 'access refused. For Gemini this usually means the Google project has no free tier and needs billing enabled in AI Studio',
    NotFoundError: 'model name not found for this provider',
    RateLimitError: 'rate limit or quota exceeded',
    APIConnectionError: 'could not reach the provider',
    APITimeoutError: 'the provider took too long',
    BadRequestError: 'the provider rejected the request (often the model name)',
  }
  return hints[errorType] ? `${hints[errorType]} (${errorType})` : errorType
}

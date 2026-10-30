import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import type { Counters, EvidenceEntry, Outcome, Proposal, Report, RunEvent, RunModel, RunRequest, RunState, Usage } from './types'

export type ToolStep = { id: string; entry: EvidenceEntry }
export type PendingCall = { id: string; name: string; arguments: string }

export type RunView = {
  runId: string | null
  request: RunRequest | null
  state: RunState | 'idle'
  steps: ToolStep[]
  pending: PendingCall[]
  counters: Counters | null
  report: Report | null
  proposal: Proposal | null
  diff: string | null
  outcome: Outcome | null
  startedAt: number | null
  finishedAt: number | null
  model: RunModel | null
  usage: Usage | null
  tokenBudget: number | null
}

const EMPTY: RunView = {
  runId: null,
  request: null,
  state: 'idle',
  steps: [],
  pending: [],
  counters: null,
  report: null,
  proposal: null,
  diff: null,
  outcome: null,
  startedAt: null,
  finishedAt: null,
  model: null,
  usage: null,
  tokenBudget: null,
}

function applyEvent(view: RunView, event: RunEvent): RunView {
  switch (event.type) {
    case 'run_started':
      return { ...view, request: event.request, state: 'running', model: event.model, tokenBudget: event.token_budget }
    case 'model_turn':
      return { ...view, pending: event.tool_calls, usage: event.usage }
    case 'tool_result':
      return {
        ...view,
        steps: [...view.steps, { id: event.evidence_id, entry: event.entry }],
        pending: view.pending.slice(1),
        counters: event.counters,
      }
    case 'report':
      return { ...view, report: event.report, pending: [], usage: event.report.token_usage }
    case 'state':
      return {
        ...view,
        state: event.state,
        proposal: event.proposal ?? view.proposal,
        diff: event.diff ?? view.diff,
        finishedAt: event.state === 'completed' ? Date.now() : view.finishedAt,
      }
    case 'outcome':
      return { ...view, outcome: { status: event.status, message: event.message, patch_result: event.patch_result } }
  }
}

/** Starts runs and mirrors the backend's server-sent event stream into view state. */
export function useRun(onFinished: () => void) {
  const [view, setView] = useState<RunView>(EMPTY)
  const [error, setError] = useState<string | null>(null)
  const source = useRef<EventSource | null>(null)
  const finished = useRef(onFinished)
  finished.current = onFinished

  const close = () => {
    source.current?.close()
    source.current = null
  }
  useEffect(() => close, [])

  const subscribe = (id: string) => {
    close()
    const stream = new EventSource(api.eventsUrl(id))
    source.current = stream
    stream.onmessage = (message) => {
      const event = JSON.parse(message.data) as RunEvent
      setView((current) => applyEvent(current, event))
      if (event.type === 'state' && (event.state === 'completed' || event.state === 'awaiting_approval')) {
        finished.current()
      }
    }
    stream.addEventListener('end', close)
  }

  const start = useCallback(async (request: RunRequest) => {
    setError(null)
    try {
      const run = await api.startRun(request)
      setView({ ...EMPTY, runId: run.id, request, state: 'running', startedAt: Date.now() })
      subscribe(run.id)
    } catch (caught) {
      setError((caught as Error).message)
    }
  }, [])

  const decide = useCallback(
    async (decision: 'approve' | 'reject') => {
      if (!view.runId) return
      setError(null)
      try {
        await (decision === 'approve' ? api.approve(view.runId) : api.reject(view.runId))
      } catch (caught) {
        setError((caught as Error).message)
      }
    },
    [view.runId],
  )

  const clear = useCallback(() => {
    close()
    setView(EMPTY)
  }, [])

  return { view, error, start, decide, clear }
}

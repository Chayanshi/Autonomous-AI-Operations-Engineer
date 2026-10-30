import { testPassed, testSummary } from '../format'
import type { RunView } from '../useRun'
import type { TestRun } from '../types'

type StageState = 'pending' | 'active' | 'done' | 'failed' | 'waiting' | 'skipped'
type Stage = { title: string; state: StageState; detail: string }

function stages(view: RunView): Stage[] {
  const tools = view.steps.map((step) => step.entry)
  const pendingNames = view.pending.map((call) => call.name)
  const running = view.state === 'running'
  const explored = tools.filter((entry) => entry.tool === 'list_files' || entry.tool === 'read_file')
  const reads = tools.filter((entry) => entry.tool === 'read_file' && !entry.error).map((entry) => entry.arguments.relative_path)
  const testRun = tools.find((entry) => entry.tool === 'run_tests' && !entry.error)?.result as TestRun | undefined
  const allowPatch = view.request?.allow_patch ?? true
  const outcome = view.outcome
  const verification = outcome?.patch_result?.verification

  const explore: Stage = {
    title: 'Explore repository',
    state: explored.length ? (running && !testRun && !pendingNames.includes('run_tests') ? 'active' : 'done') : running ? 'active' : 'pending',
    detail: reads.length ? `Read ${reads.join(', ')}` : 'List and read relevant files',
  }
  const reproduce: Stage = {
    title: 'Reproduce failure',
    state: testRun ? 'done' : pendingNames.includes('run_tests') ? 'active' : 'pending',
    detail: testRun ? `${testPassed(testRun) ? '' : 'Failure reproduced · '}${testSummary(testRun)}` : 'Run the fixed pytest command',
  }
  const diagnose: Stage = {
    title: 'Diagnose root cause',
    state: view.report ? (view.report.likely_root_cause.hypothesis ? 'done' : 'failed') : running && testRun ? 'active' : 'pending',
    detail: view.report ? (view.report.likely_root_cause.hypothesis ? 'Hypothesis linked to evidence' : 'No structured diagnosis') : 'Form an evidence-backed hypothesis',
  }
  const propose: Stage = !allowPatch
    ? { title: 'Propose patch', state: 'skipped', detail: 'Read-only run' }
    : view.proposal
      ? { title: 'Propose patch', state: 'done', detail: `Minimal edit to ${view.proposal.relative_path}` }
      : view.report
        ? { title: 'Propose patch', state: 'skipped', detail: 'No patch proposed' }
        : { title: 'Propose patch', state: 'pending', detail: 'One exact-text edit, not written' }
  const approve: Stage =
    view.state === 'awaiting_approval'
      ? { title: 'Human approval', state: 'waiting', detail: 'Review the diff' }
      : outcome?.status === 'rejected'
        ? { title: 'Human approval', state: 'failed', detail: 'Rejected · nothing written' }
        : view.proposal && (view.state === 'verifying' || outcome)
          ? { title: 'Human approval', state: 'done', detail: 'Approved by reviewer' }
          : { title: 'Human approval', state: view.report && !view.proposal ? 'skipped' : 'pending', detail: 'Required before any write' }
  const verify: Stage =
    view.state === 'verifying'
      ? { title: 'Verify', state: 'active', detail: 'Applying patch · running full pytest suite' }
      : verification
        ? {
            title: 'Verify',
            state: testPassed(verification) ? 'done' : 'failed',
            detail: testPassed(verification) ? testSummary(verification) : `${testSummary(verification)} · rolled back`,
          }
        : { title: 'Verify', state: outcome ? 'skipped' : 'pending', detail: 'Fresh pytest run after the patch' }

  return [explore, reproduce, diagnose, propose, approve, verify]
}

const ICONS: Record<StageState, string> = {
  pending: '',
  active: '',
  done: '✓',
  failed: '✕',
  waiting: '!',
  skipped: '–',
}

export function Pipeline({ view }: { view: RunView }) {
  return (
    <ol className="pipeline">
      {stages(view).map((stage, index) => (
        <li key={stage.title} className={`stage ${stage.state}`}>
          <div className="dot">{ICONS[stage.state] || index + 1}</div>
          <div>
            <div className="stage-title">{stage.title}</div>
            <div className="stage-detail">{stage.detail}</div>
          </div>
        </li>
      ))}
    </ol>
  )
}

import type { EvidenceEntry, TestRun } from './types'

export function testSummary(run: TestRun): string {
  if (run.timed_out) return 'timed out'
  const lines = run.stdout.split('\n').map((line) => line.trim()).filter(Boolean)
  return lines.at(-1) ?? `exit code ${run.exit_code}`
}

export const testPassed = (run: TestRun) => !run.timed_out && run.exit_code === 0

export function describeStep(entry: EvidenceEntry): { label: string; outcome: string; tone: 'ok' | 'bad' | 'neutral' } {
  const target = entry.arguments.relative_path
  const label = target ? `${entry.tool}(${target})` : `${entry.tool}()`
  if (entry.error) return { label, outcome: `rejected: ${entry.error.message}`, tone: 'bad' }
  const result = entry.result
  switch (entry.tool) {
    case 'list_files':
      return { label, outcome: `${(result as string[]).length} files`, tone: 'neutral' }
    case 'read_file':
      return { label, outcome: `${(result as string).trimEnd().split('\n').length} lines`, tone: 'neutral' }
    case 'run_tests': {
      const run = result as TestRun
      return { label, outcome: testSummary(run), tone: testPassed(run) ? 'ok' : 'bad' }
    }
    case 'apply_text_replacement':
      return { label, outcome: 'patch proposed · not written', tone: 'neutral' }
    default:
      return { label, outcome: 'done', tone: 'neutral' }
  }
}

export function formatTokens(count: number): string {
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`
  if (count >= 1_000) return `${(count / 1_000).toFixed(count >= 10_000 ? 0 : 1)}k`
  return String(count)
}

export function formatElapsed(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000))
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
}

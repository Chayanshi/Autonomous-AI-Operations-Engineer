// Shapes returned by backend/server.py and investigation_loop.py.

export type Limits = { model_turns: number; tool_calls: number; tool_errors: number; patch_attempts: number }
export type Counters = Limits

export type Target = {
  name: string
  title: string
  symptom: string
  objective: string
  baseline_clean: boolean | null
}

export type Status = {
  mock_label: string
  patch_path: string
  default_target: string
  targets: Target[]
  active_run_id: string | null
  limits: Limits
}

export type ProviderName = 'mock' | 'nebius' | 'gemini'

export type Usage = { input_tokens: number; output_tokens: number; model_calls: number; usage_reported: boolean }

export type AiProvider = {
  name: ProviderName
  label: string
  note: string
  model: string | null
  default_model: string | null
  key_source: 'user' | 'environment' | null
  key_variable: string | null
  ready: boolean
}

export type AiSettings = {
  provider: ProviderName
  providers: AiProvider[]
  max_output_tokens: number
  run_token_budget: number
  bounds: { max_output_tokens: [number, number]; run_token_budget: [number, number] }
  session_usage: Usage & { runs: number }
  last_run_usage: (Usage & { token_budget: number | null; run_id: string }) | null
}

export type SettingsUpdate = Partial<{
  provider: ProviderName
  model: string
  api_key: string
  clear_key: boolean
  max_output_tokens: number
  run_token_budget: number
}>

export type RunModel = { provider: ProviderName; model: string | null }

export type RunRequest = {
  target: string
  objective: string
  scenario: 'fix' | 'bad-patch'
  allow_patch: boolean
}

export type TestRun = { stdout: string; stderr: string; exit_code: number | null; timed_out: boolean }

export type EvidenceEntry = {
  tool: string
  arguments: Record<string, string>
  result: unknown
  error: { type: string; message: string } | null
}

export type Proposal = {
  relative_path: string
  expected_text: string
  replacement_text: string
  original_sha256: string
  updated_sha256: string
}

export type PatchResult = {
  patch: { relative_path: string; original_sha256: string; updated_sha256: string }
  verification: TestRun
  verified: boolean
  rolled_back: boolean
  rollback_error: string | null
}

export type Report = {
  objective: string
  files_inspected: string[]
  test_command: { argv: string[]; status: string; runs: TestRun[] }
  observed_failures: string[]
  verified_facts: string[]
  likely_root_cause: { hypothesis: string | null; raw_response?: string | null; verified: boolean }
  recommended_next_action: string
  stop_reason: string
  model_error: { type: string; message: string } | null
  patch_proposal: Proposal | null
  token_usage: Usage
  token_budget: number | null
  verification_status: string
  tool_evidence: EvidenceEntry[]
}

export type RunState = 'running' | 'awaiting_approval' | 'verifying' | 'rejecting' | 'completed'

export type Outcome = {
  status: 'verified' | 'not_verified' | 'rejected' | 'error'
  message: string
  patch_result: PatchResult | null
}

export type RunEvent =
  | { seq: number; type: 'run_started'; request: RunRequest; model: RunModel; token_budget: number | null }
  | {
      seq: number
      type: 'model_turn'
      iteration: number
      content: string
      tool_calls: { id: string; name: string; arguments: string }[]
      usage: Usage
    }
  | { seq: number; type: 'tool_result'; evidence_id: string; entry: EvidenceEntry; counters: Counters }
  | { seq: number; type: 'report'; report: Report }
  | { seq: number; type: 'state'; state: RunState; proposal?: Proposal; diff?: string }
  | ({ seq: number; type: 'outcome' } & Outcome)

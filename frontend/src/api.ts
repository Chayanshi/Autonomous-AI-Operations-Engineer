import type { AiSettings, RunRequest, SettingsUpdate, Status } from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    const detail = typeof body.detail === 'string' ? body.detail : `Request failed (${response.status})`
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export const api = {
  status: () => request<Status>('/api/status'),
  startRun: (body: RunRequest) => request<{ id: string }>('/api/runs', { method: 'POST', body: JSON.stringify(body) }),
  approve: (id: string) => request(`/api/runs/${id}/approve`, { method: 'POST' }),
  reject: (id: string) => request(`/api/runs/${id}/reject`, { method: 'POST' }),
  reset: () => request<{ restored: string[] }>('/api/reset', { method: 'POST' }),
  eventsUrl: (id: string) => `/api/runs/${id}/events`,
  settings: () => request<AiSettings>('/api/settings'),
  updateSettings: (body: SettingsUpdate) => request<AiSettings>('/api/settings', { method: 'PUT', body: JSON.stringify(body) }),
  testConnection: () => request<{ ok: boolean; provider: string; model?: string; message: string }>('/api/settings/test', { method: 'POST' }),
}

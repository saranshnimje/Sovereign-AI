/**
 * Artifacts API — manage agent-generated files.
 */

// Keep the production API usable even if Vercel is missing the optional env var.
// VITE_API_BASE_URL still overrides this for local/staging environments.
const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? 'https://sovereign-ai-backend-ciy8.onrender.com').replace(/\/$/, '')

export interface Artifact {
  id: string
  filename: string
  relative_path: string
  mime_type: string | null
  size_bytes: number
  checksum: string | null
  conversation_id: string | null
  run_id: string | null
  created_at: string | null
}

function authHeaders(): HeadersInit {
  const token = localStorage.getItem('access_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export const artifactsApi = {
  async listArtifacts(conversationId?: string, runId?: string): Promise<Artifact[]> {
    const params = new URLSearchParams()
    if (conversationId) params.set('conversation_id', conversationId)
    if (runId) params.set('run_id', runId)
    const qs = params.toString()
    const res = await fetch(`${API_BASE}/api/v1/artifacts${qs ? '?' + qs : ''}`, {
      headers: authHeaders(),
    })
    if (!res.ok) throw res
    return res.json()
  },

  async getArtifact(artifactId: string): Promise<Artifact> {
    const res = await fetch(`${API_BASE}/api/v1/artifacts/${artifactId}`, {
      headers: authHeaders(),
    })
    if (!res.ok) throw res
    return res.json()
  },

  async downloadUrl(artifactId: string): Promise<string> {
    const res = await fetch(`${API_BASE}/api/v1/artifacts/${artifactId}/download`, {
      headers: authHeaders(),
    })
    if (!res.ok) throw res

    // Downloads are authenticated by the Authorization header. Returning a
    // blob URL avoids leaking access tokens into browser URLs/history/logs.
    const blob = await res.blob()
    return URL.createObjectURL(blob)
  },

  async previewArtifact(artifactId: string): Promise<{ content: string; filename: string; mime_type: string }> {
    const res = await fetch(`${API_BASE}/api/v1/artifacts/${artifactId}/preview`, {
      headers: authHeaders(),
    })
    if (!res.ok) throw res
    return res.json()
  },

  async deleteArtifact(artifactId: string): Promise<void> {
    const res = await fetch(`${API_BASE}/api/v1/artifacts/${artifactId}`, {
      method: 'DELETE',
      headers: authHeaders(),
    })
    if (!res.ok) throw res
  },
}

/**
 * Artifacts API — manage agent-generated files.
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

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

export const artifactsApi = {
  async listArtifacts(conversationId?: string, runId?: string): Promise<Artifact[]> {
    const params = new URLSearchParams()
    if (conversationId) params.set('conversation_id', conversationId)
    if (runId) params.set('run_id', runId)
    const qs = params.toString()
    const token = localStorage.getItem('access_token')
    const res = await fetch(`${API_BASE}/api/v1/artifacts${qs ? '?' + qs : ''}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) throw res
    return res.json()
  },

  async getArtifact(artifactId: string): Promise<Artifact> {
    const token = localStorage.getItem('access_token')
    const res = await fetch(`${API_BASE}/api/v1/artifacts/${artifactId}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) throw res
    return res.json()
  },

  async downloadUrl(artifactId: string): Promise<string> {
    const token = localStorage.getItem('access_token')
    return `${API_BASE}/api/v1/artifacts/${artifactId}/download?token=${token}`
  },

  async previewArtifact(artifactId: string): Promise<{ content: string; filename: string; mime_type: string }> {
    const token = localStorage.getItem('access_token')
    const res = await fetch(`${API_BASE}/api/v1/artifacts/${artifactId}/preview`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) throw res
    return res.json()
  },

  async deleteArtifact(artifactId: string): Promise<void> {
    const token = localStorage.getItem('access_token')
    const res = await fetch(`${API_BASE}/api/v1/artifacts/${artifactId}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) throw res
  },
}

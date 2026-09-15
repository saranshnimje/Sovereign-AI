/**
 * Artifacts API — manage agent-generated files.
 */
import api from './client'

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

function normalizeError(error: unknown): Error {
  if (error instanceof Error) return error
  return new Error('Artifact request failed')
}

export const artifactsApi = {
  async listArtifacts(conversationId?: string, runId?: string): Promise<Artifact[]> {
    try {
      const response = await api.get<Artifact[]>('/artifacts', {
        params: {
          ...(conversationId ? { conversation_id: conversationId } : {}),
          ...(runId ? { run_id: runId } : {}),
        },
      })
      return Array.isArray(response.data) ? response.data : []
    } catch (error) {
      throw normalizeError(error)
    }
  },

  async getArtifact(artifactId: string): Promise<Artifact> {
    const response = await api.get<Artifact>(`/artifacts/${artifactId}`)
    return response.data
  },

  async downloadUrl(artifactId: string): Promise<string> {
    const response = await api.get<Blob>(`/artifacts/${artifactId}/download`, {
      responseType: 'blob',
    })
    return URL.createObjectURL(response.data)
  },

  async previewArtifact(artifactId: string): Promise<{ content: string; filename: string; mime_type: string }> {
    const response = await api.get(`/artifacts/${artifactId}/preview`)
    return response.data
  },

  async deleteArtifact(artifactId: string): Promise<void> {
    await api.delete(`/artifacts/${artifactId}`)
  },
}

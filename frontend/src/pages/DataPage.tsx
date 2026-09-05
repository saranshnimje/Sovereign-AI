import { useEffect, useState, useRef } from 'react'
import { dataApi, Organization, DataSource, SensorAnalysis } from '../api/data'
import { useUIStore } from '../stores/uiStore'
import Badge from '../components/ui/Badge'

export default function DataPage() {
  const { addToast } = useUIStore()
  const [orgs, setOrgs] = useState<Organization[]>([])
  const [analyses, setAnalyses] = useState<SensorAnalysis[]>([])
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<'organizations' | 'sensor'>('organizations')
  const [showCreateOrg, setShowCreateOrg] = useState(false)
  const [newOrgName, setNewOrgName] = useState('')
  const [newOrgDesc, setNewOrgDesc] = useState('')
  const [newOrgIndustry, setNewOrgIndustry] = useState('')
  const [newOrgLocation, setNewOrgLocation] = useState('')
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const load = async () => {
      const [o, s] = await Promise.allSettled([dataApi.listOrgs(), dataApi.listSensorAnalyses()])
      if (o.status === 'fulfilled') setOrgs(o.value)
      if (s.status === 'fulfilled') setAnalyses(s.value)
      setLoading(false)
    }
    load()
  }, [])

  const handleCreateOrg = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      const org = await dataApi.createOrg({
        name: newOrgName,
        description: newOrgDesc || undefined,
        industry: newOrgIndustry || undefined,
        location: newOrgLocation || undefined,
      })
      setOrgs(prev => [...prev, org])
      setShowCreateOrg(false); setNewOrgName(''); setNewOrgDesc(''); setNewOrgIndustry(''); setNewOrgLocation('')
      addToast({ type: 'success', title: 'Organization created' })
    } catch { addToast({ type: 'error', title: 'Create failed' }) }
  }

  const handleUploadSensor = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      const analysis = await dataApi.uploadSensorData(file)
      setAnalyses(prev => [analysis, ...prev])
      addToast({ type: 'success', title: 'Uploaded', message: file.name })
    } catch { addToast({ type: 'error', title: 'Upload failed' }) }
    setUploading(false)
    if (fileRef.current) fileRef.current.value = ''
  }

  const statusColors: Record<string, 'success' | 'warning' | 'danger' | 'info' | 'default'> = {
    completed: 'success', processing: 'warning', pending: 'info', failed: 'danger',
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg md:text-2xl font-bold text-white">Data</h1>
        <p className="text-xs md:text-sm text-neutral-400 mt-1">Manage organizations, data sources, and sensor analytics.</p>
      </div>

      <div className="flex gap-2">
        <button onClick={() => setTab('organizations')}
          className={`px-4 py-2 text-sm rounded-lg border transition-colors ${tab === 'organizations' ? 'bg-cyan-600 text-white border-cyan-600' : 'border-surface-border text-neutral-400 hover:bg-surface-muted'}`}>
          Organizations
        </button>
        <button onClick={() => setTab('sensor')}
          className={`px-4 py-2 text-sm rounded-lg border transition-colors ${tab === 'sensor' ? 'bg-cyan-600 text-white border-cyan-600' : 'border-surface-border text-neutral-400 hover:bg-surface-muted'}`}>
          Sensor Data
        </button>
      </div>

      {loading ? (
        <div className="space-y-3">{[...Array(3)].map((_, i) => <div key={i} className="skeleton h-20" />)}</div>
      ) : tab === 'organizations' ? (
        <div className="space-y-4">
          <div className="flex justify-end">
            <button onClick={() => setShowCreateOrg(true)} className="px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-medium hover:bg-cyan-500">
              + Create Organization
            </button>
          </div>
          {showCreateOrg && (
            <div className="bg-surface-raised border border-surface-border rounded-xl p-6">
              <form onSubmit={handleCreateOrg} className="space-y-4">
                <input type="text" value={newOrgName} onChange={e => setNewOrgName(e.target.value)} required placeholder="Organization name"
                  className="w-full rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm text-neutral-200 focus:outline-none focus:ring-2 focus:ring-cyan-500" />
                <input type="text" value={newOrgDesc} onChange={e => setNewOrgDesc(e.target.value)} placeholder="Description (optional)"
                  className="w-full rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm text-neutral-200 focus:outline-none focus:ring-2 focus:ring-cyan-500" />
                <div className="grid grid-cols-2 gap-3">
                  <input type="text" value={newOrgIndustry} onChange={e => setNewOrgIndustry(e.target.value)} placeholder="Industry (e.g. Technology)"
                    className="w-full rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm text-neutral-200 focus:outline-none focus:ring-2 focus:ring-cyan-500" />
                  <input type="text" value={newOrgLocation} onChange={e => setNewOrgLocation(e.target.value)} placeholder="Location (e.g. Mumbai, India)"
                    className="w-full rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm text-neutral-200 focus:outline-none focus:ring-2 focus:ring-cyan-500" />
                </div>
                <div className="flex gap-2">
                  <button type="submit" disabled={!newOrgName.trim()} className="px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-medium hover:bg-cyan-500 disabled:opacity-50">Create</button>
                  <button type="button" onClick={() => setShowCreateOrg(false)} className="px-4 py-2 border border-surface-border text-neutral-300 rounded-lg text-sm hover:bg-surface-muted">Cancel</button>
                </div>
              </form>
            </div>
          )}
          {orgs.length === 0 ? (
            <div className="bg-surface-raised border border-surface-border rounded-xl p-12 text-center">
              <h3 className="text-lg font-semibold text-white mb-2">No Organizations</h3>
              <p className="text-sm text-neutral-400">Create an organization to manage data sources.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {orgs.map(org => (
                <div key={org.id} className="bg-surface-raised border border-surface-border rounded-xl p-5 hover:border-cyan-700/50 transition-all">
                  <h3 className="font-semibold text-white text-sm mb-1">{org.name}</h3>
                  {org.industry && <p className="text-[10px] text-cyan-400 uppercase tracking-wider mb-1">{org.industry}</p>}
                  {org.description && <p className="text-xs text-neutral-400 mb-2">{org.description}</p>}
                  <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-neutral-500">
                    {org.location && <span>📍 {org.location}</span>}
                    {org.ceo && <span>👤 {org.ceo}</span>}
                    {org.employee_count && <span>👥 {org.employee_count}</span>}
                    {org.revenue && <span>💰 {org.revenue}</span>}
                  </div>
                  {org.details && (
                    <div className="mt-3 pt-3 border-t border-surface-border">
                      <div className="flex gap-4 text-[10px] text-neutral-500">
                        {Array.isArray(org.details.employees) && <span>{org.details.employees.length} employees</span>}
                        {Array.isArray(org.details.departments) && <span>{org.details.departments.length} departments</span>}
                        {Array.isArray(org.details.infrastructure) && <span>{org.details.infrastructure.length} assets</span>}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex justify-end">
            <input ref={fileRef} type="file" className="hidden" onChange={handleUploadSensor} accept=".csv" />
            <button onClick={() => fileRef.current?.click()} disabled={uploading}
              className="px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-medium hover:bg-cyan-500 disabled:opacity-50">
              {uploading ? 'Uploading...' : '+ Upload CSV'}
            </button>
          </div>
          {analyses.length === 0 ? (
            <div className="bg-surface-raised border border-surface-border rounded-xl p-12 text-center">
              <h3 className="text-lg font-semibold text-white mb-2">No Sensor Data</h3>
              <p className="text-sm text-neutral-400">Upload a CSV file to analyze sensor data.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {analyses.map(a => (
                <div key={a.id} className="bg-surface-raised border border-surface-border rounded-xl p-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="text-sm">📊</span>
                      <div>
                        <p className="text-sm text-neutral-200">{a.original_name}</p>
                        <p className="text-[10px] text-neutral-500">{a.row_count || 0} rows</p>
                      </div>
                    </div>
                    <Badge variant={statusColors[a.status] || 'default'} size="sm">{a.status}</Badge>
                  </div>
                  {a.ai_explanation && (
                    <p className="text-xs text-neutral-400 mt-2 pl-8">{a.ai_explanation.slice(0, 200)}...</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

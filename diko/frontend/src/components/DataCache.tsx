import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react'
import { API } from '../App'

interface CacheData {
  library: any[] | null
  stats: any | null
  categories: any[] | null
  collections: any[] | null
  settings: any | null
}

interface DataCacheCtx {
  data: CacheData
  loading: boolean
  refreshLibrary: () => Promise<void>
  refreshSettings: () => Promise<void>
  refreshAll: () => Promise<void>
  prefetch: (key: keyof CacheData) => void
}

const DataCacheContext = createContext<DataCacheCtx | null>(null)

const STALE_MS = 30_000 // 30 sec cache

export function DataCacheProvider({ children }: { children: React.ReactNode }) {
  const [data, setData] = useState<CacheData>({
    library: null, stats: null, categories: null, collections: null, settings: null,
  })
  const [loading, setLoading] = useState(true)
  const timestamps = useRef<Record<string, number>>({})
  const inflight = useRef<Record<string, Promise<any>>>({})

  const fetchOnce = useCallback(async (key: string, url: string, transform?: (d: any) => any) => {
    const now = Date.now()
    if (timestamps.current[key] && now - timestamps.current[key] < STALE_MS) return undefined
    if (key in inflight.current) return inflight.current[key]

    const p = fetch(`${API}${url}`)
      .then(r => r.json())
      .then(d => {
        const val = transform ? transform(d) : d
        setData(prev => ({ ...prev, [key]: val }))
        timestamps.current[key] = Date.now()
        delete inflight.current[key]
        return val
      })
      .catch(() => { delete inflight.current[key] })

    inflight.current[key] = p
    return p
  }, [])

  const refreshLibrary = useCallback(async () => {
    timestamps.current.library = 0
    timestamps.current.stats = 0
    timestamps.current.categories = 0
    timestamps.current.collections = 0
    await Promise.all([
      fetchOnce('library', '/api/library', d => d.items || []),
      fetchOnce('stats', '/api/stats'),
      fetchOnce('categories', '/api/categories', d => d.categories || []),
      fetchOnce('collections', '/api/collections', d => d.collections || []),
    ])
  }, [fetchOnce])

  const refreshSettings = useCallback(async () => {
    timestamps.current.settings = 0
    await fetchOnce('settings', '/api/settings')
  }, [fetchOnce])

  const refreshAll = useCallback(async () => {
    Object.keys(timestamps.current).forEach(k => { timestamps.current[k] = 0 })
    await Promise.all([
      refreshLibrary(),
      refreshSettings(),
    ])
  }, [refreshLibrary, refreshSettings])

  const prefetch = useCallback((key: keyof CacheData) => {
    switch (key) {
      case 'library':
        fetchOnce('library', '/api/library', d => d.items || [])
        fetchOnce('stats', '/api/stats')
        fetchOnce('categories', '/api/categories', d => d.categories || [])
        fetchOnce('collections', '/api/collections', d => d.collections || [])
        break
      case 'settings':
        fetchOnce('settings', '/api/settings')
        break
    }
  }, [fetchOnce])

  // Initial load
  useEffect(() => {
    Promise.all([
      fetchOnce('library', '/api/library', d => d.items || []),
      fetchOnce('stats', '/api/stats'),
      fetchOnce('categories', '/api/categories', d => d.categories || []),
      fetchOnce('collections', '/api/collections', d => d.collections || []),
      fetchOnce('settings', '/api/settings'),
    ]).then(() => setLoading(false))
  }, [fetchOnce])

  return (
    <DataCacheContext.Provider value={{ data, loading, refreshLibrary, refreshSettings, refreshAll, prefetch }}>
      {children}
    </DataCacheContext.Provider>
  )
}

export function useDataCache() {
  const ctx = useContext(DataCacheContext)
  if (!ctx) throw new Error('useDataCache must be inside DataCacheProvider')
  return ctx
}

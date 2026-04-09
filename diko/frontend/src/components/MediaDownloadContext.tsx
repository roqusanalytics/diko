import { createContext, useContext, useState, useCallback, type ReactNode } from 'react'

interface ActiveDownload {
  jobId: string
  title: string
  format: string
  quality: string
  progress: number
  stage: string // queued, downloading, converting, complete, error
}

interface MediaDownloadContextType {
  activeDownloads: ActiveDownload[]
  addDownload: (dl: ActiveDownload) => void
  updateDownload: (jobId: string, updates: Partial<ActiveDownload>) => void
  removeDownload: (jobId: string) => void
}

const MediaDownloadContext = createContext<MediaDownloadContextType>({
  activeDownloads: [],
  addDownload: () => {},
  updateDownload: () => {},
  removeDownload: () => {},
})

export function useMediaDownloads() {
  return useContext(MediaDownloadContext)
}

export function MediaDownloadProvider({ children }: { children: ReactNode }) {
  const [downloads, setDownloads] = useState<ActiveDownload[]>([])

  const addDownload = useCallback((dl: ActiveDownload) => {
    setDownloads(prev => [...prev.filter(d => d.jobId !== dl.jobId), dl])
  }, [])

  const updateDownload = useCallback((jobId: string, updates: Partial<ActiveDownload>) => {
    setDownloads(prev => prev.map(d =>
      d.jobId === jobId ? { ...d, ...updates } : d
    ))
  }, [])

  const removeDownload = useCallback((jobId: string) => {
    setDownloads(prev => prev.filter(d => d.jobId !== jobId))
  }, [])

  return (
    <MediaDownloadContext.Provider value={{
      activeDownloads: downloads,
      addDownload,
      updateDownload,
      removeDownload,
    }}>
      {children}
    </MediaDownloadContext.Provider>
  )
}

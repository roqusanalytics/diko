import { Routes, Route, NavLink, useNavigate } from 'react-router-dom'
import { useState } from 'react'
import TranscribePage from './pages/TranscribePage'
import LibraryPage from './pages/LibraryPage'
import SettingsPage from './pages/SettingsPage'
import Breadcrumb from './components/Breadcrumb'
import { MediaDownloadProvider, useMediaDownloads } from './components/MediaDownloadContext'
import './App.css'

const API = ''  // Uses Vite proxy in dev, same origin in prod

export { API }

function SidebarDownloads() {
  const { activeDownloads, removeDownload } = useMediaDownloads()
  if (activeDownloads.length === 0) return null

  const visible = activeDownloads.slice(0, 3)
  const overflow = activeDownloads.length - 3

  return (
    <div className="sidebar-downloads">
      <div className="nav-section-label">Atsisiuntimai</div>
      {visible.map(dl => (
        <div key={dl.jobId} className="sidebar-dl-item">
          <div className="sidebar-dl-title">
            {dl.title ? (dl.title.length > 22 ? dl.title.slice(0, 22) + '...' : dl.title) : 'Atsisiunčiama...'}
          </div>
          <div className="sidebar-dl-meta">
            <span className="sidebar-dl-format">{dl.format.toUpperCase()}</span>
            {dl.stage === 'complete' ? (
              <span className="sidebar-dl-done" onClick={() => setTimeout(() => removeDownload(dl.jobId), 300)}>✓</span>
            ) : dl.stage === 'error' ? (
              <span className="sidebar-dl-error">✕</span>
            ) : (
              <span className="sidebar-dl-pct">{Math.round(dl.progress * 100)}%</span>
            )}
          </div>
          <div className="sidebar-dl-bar">
            <div
              className={`sidebar-dl-bar-fill ${dl.stage === 'complete' ? 'sidebar-dl-bar-done' : dl.stage === 'error' ? 'sidebar-dl-bar-error' : ''}`}
              style={{ width: `${Math.round(dl.progress * 100)}%` }}
            />
          </div>
        </div>
      ))}
      {overflow > 0 && (
        <div className="sidebar-dl-overflow">+{overflow} daugiau</div>
      )}
    </div>
  )
}

function App() {
  const [recentItems, setRecentItems] = useState<{video_id: string, title: string, language: string}[]>([])
  const [currentVideoTitle, setCurrentVideoTitle] = useState<string | undefined>()
  const navigate = useNavigate()

  const addRecent = (item: {video_id: string, title: string, language: string}) => {
    setRecentItems(prev => {
      const filtered = prev.filter(i => i.video_id !== item.video_id)
      return [item, ...filtered].slice(0, 10)
    })
    setCurrentVideoTitle(item.title)
  }

  return (
    <MediaDownloadProvider>
    <div className="layout">
      <aside className="sidebar">
        <div className="logo">
          <img src="/logo.svg" alt="App Logo" className="logo-icon" style={{ width: '32px', height: '32px', marginRight: '12px' }} />
          Diko
        </div>

        <NavLink to="/" end className={({isActive}) => `nav-item ${isActive ? 'active' : ''}`}>
          <span className="nav-icon">+</span> Naujas
        </NavLink>
        <NavLink to="/library" className={({isActive}) => `nav-item ${isActive ? 'active' : ''}`}>
          <span className="nav-icon">&#9776;</span> Biblioteka
        </NavLink>
        <NavLink to="/settings" className={({isActive}) => `nav-item ${isActive ? 'active' : ''}`}>
          <span className="nav-icon">&#9881;</span> Nustatymai
        </NavLink>

        {recentItems.length > 0 && (
          <>
            <div className="nav-section-label">Paskutiniai</div>
            <div className="recents-wrapper">
              {recentItems.map(item => (
                <div
                  key={item.video_id}
                  className="recent-item"
                  onClick={() => navigate(`/?v=${item.video_id}`)}
                >
                  <span className={`recent-dot ${item.language === 'lt' ? 'lt' : 'en'}`} />
                  {item.title.length > 28 ? item.title.slice(0, 28) + '...' : item.title}
                </div>
              ))}
            </div>
          </>
        )}

        <SidebarDownloads />
        <div className="sidebar-footer">Powered by Whisper AI</div>
      </aside>

      <main className="main-card">
        <Breadcrumb videoTitle={currentVideoTitle} />
        <Routes>
          <Route path="/" element={<TranscribePage onTranscribed={addRecent} onTitleChange={setCurrentVideoTitle} />} />
          <Route path="/library" element={<LibraryPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
    </MediaDownloadProvider>
  )
}

export default App

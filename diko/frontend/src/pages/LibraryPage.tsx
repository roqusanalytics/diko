import { useState, useEffect, useMemo, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import { API } from '../App'
import DownloadModal from '../components/DownloadModal'
import './LibraryPage.css'

interface LibraryItem {
  video_id: string
  title: string
  url: string
  language: string
  duration: number
  summary: string
  source: string
  summary_status: string
  channel_name: string
  view_count: number
  like_count: number
  categories: string[]
  category_status: string
  created_at: string
}

const CATEGORY_LABELS_LT: Record<string, string> = {
  AI: 'DI',
  Programming: 'Programavimas',
  Business: 'Verslas',
  Science: 'Mokslas',
  Education: 'Švietimas',
  Design: 'Dizainas',
  Marketing: 'Rinkodara',
  Finance: 'Finansai',
  Health: 'Sveikata',
  Music: 'Muzika',
  Gaming: 'Žaidimai',
  News: 'Naujienos',
  Philosophy: 'Filosofija',
  Productivity: 'Produktyvumas',
  Other: 'Kita',
}

interface TranscriptData {
  video_id: string
  title: string
  url: string
  language: string
  duration: number
  summary: string
  summary_status: string
  source: string
  translated_text: string
  segments: { start: number; end: number; text: string }[]
}

type SortKey = 'date_desc' | 'date_asc' | 'title_asc' | 'title_desc' | 'duration_desc' | 'duration_asc'
type LangFilter = 'all' | 'en' | 'lt' | 'other'

function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  return `${m}:${s.toString().padStart(2, '0')}`
}

function formatDateTime(dateStr: string): string {
  if (!dateStr) return ''
  try {
    const d = new Date(dateStr.includes('T') ? dateStr : dateStr.replace(' ', 'T'))
    const date = d.toLocaleDateString('lt-LT', { year: 'numeric', month: '2-digit', day: '2-digit' })
    const time = d.toLocaleTimeString('lt-LT', { hour: '2-digit', minute: '2-digit' })
    return `${date} ${time}`
  } catch {
    return dateStr.split('T')[0] || dateStr.split(' ')[0] || ''
  }
}

function formatRelativeDate(dateStr: string): string {
  if (!dateStr) return ''
  try {
    const d = new Date(dateStr.includes('T') ? dateStr : dateStr.replace(' ', 'T'))
    const now = new Date()
    const diff = now.getTime() - d.getTime()
    const mins = Math.floor(diff / 60000)
    if (mins < 1) return 'ką tik'
    if (mins < 60) return `prieš ${mins} min`
    const hours = Math.floor(mins / 60)
    if (hours < 24) return `prieš ${hours} val`
    const days = Math.floor(hours / 24)
    if (days < 7) return `prieš ${days} d.`
    return formatDateTime(dateStr)
  } catch {
    return ''
  }
}

function formatCount(n: number): string {
  if (!n) return ''
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1).replace(/\.0$/, '')}K`
  return String(n)
}

const PAUSE_THRESHOLD = 2.0

function mergeSegments(segments: { start: number; end: number; text: string }[]): string[] {
  const paragraphs: string[] = []
  let current: string[] = []
  segments.forEach((seg, i) => {
    if (i > 0) {
      const gap = seg.start - segments[i - 1].end
      if (gap >= PAUSE_THRESHOLD && current.length) {
        paragraphs.push(current.join(' '))
        current = []
      }
    }
    current.push(seg.text)
  })
  if (current.length) paragraphs.push(current.join(' '))
  return paragraphs
}

function saveMdFile(content: string, filename: string) {
  const blob = new Blob([content], { type: 'text/markdown' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  URL.revokeObjectURL(a.href)
}

function CopyButtons({ text, md, mdFilename }: { text: string; md: string; mdFilename?: string }) {
  const [copied, setCopied] = useState<'text' | 'md' | null>(null)
  const copy = (content: string, type: 'text' | 'md') => {
    navigator.clipboard.writeText(content)
    setCopied(type)
    setTimeout(() => setCopied(null), 1500)
  }
  return (
    <div className="section-copy-buttons">
      <button className="btn-copy-sm" onClick={() => copy(text, 'text')}>
        {copied === 'text' ? '✓' : 'Kopijuoti'}
      </button>
      <button className="btn-copy-sm" onClick={() => copy(md, 'md')}>
        {copied === 'md' ? '✓' : 'MD'}
      </button>
      <button className="btn-copy-sm" onClick={() => saveMdFile(md, mdFilename || 'export.md')} title="Atsisiųsti .md failą">
        ⬇ .md
      </button>
    </div>
  )
}

function CollapsibleCard({ className, label, children, copyText, copyMd, mdFilename }: {
  className: string
  label: string
  children: React.ReactNode
  copyText?: string
  copyMd?: string
  mdFilename?: string
}) {
  const [expanded, setExpanded] = useState(false)
  const innerRef = useRef<HTMLDivElement>(null)
  const [needsExpand, setNeedsExpand] = useState(false)
  const collapsedHeight = 200

  useEffect(() => {
    const el = innerRef.current
    if (!el) return
    const check = () => setNeedsExpand(el.scrollHeight > collapsedHeight + 20)
    check()
    const ro = new ResizeObserver(check)
    ro.observe(el)
    return () => ro.disconnect()
  }, [children])

  return (
    <div className={className}>
      <div className="lib-detail-header">
        <div className="lib-detail-label">{label}</div>
        {copyText && copyMd && <CopyButtons text={copyText} md={copyMd} mdFilename={mdFilename} />}
      </div>
      <div
        className={`collapsible-content ${!expanded && needsExpand ? 'collapsible-collapsed' : ''}`}
        style={!expanded && needsExpand ? { maxHeight: collapsedHeight } : undefined}
      >
        <div ref={innerRef}>{children}</div>
      </div>
      {needsExpand && (
        <button
          className="collapsible-toggle"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? 'Rodyti mažiau' : 'Rodyti daugiau'}
        </button>
      )}
    </div>
  )
}

function LibrarySummaryBox({ text, title }: { text: string; title?: string }) {
  const [expanded, setExpanded] = useState(false)
  const innerRef = useRef<HTMLDivElement>(null)
  const [needsExpand, setNeedsExpand] = useState(false)
  const collapsedHeight = 200

  useEffect(() => {
    const el = innerRef.current
    if (!el) return
    const check = () => setNeedsExpand(el.scrollHeight > collapsedHeight + 20)
    check()
    const ro = new ResizeObserver(check)
    ro.observe(el)
    return () => ro.disconnect()
  }, [text])

  // Strip markdown for plain text copy
  const plainText = text
    .replace(/#{1,6}\s+/g, '')
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/\*(.*?)\*/g, '$1')
    .replace(/- /g, '• ')
    .trim()

  return (
    <div className="lib-detail-summary">
      <div className="lib-detail-header">
        <div className="lib-detail-label">Santrauka</div>
        <CopyButtons text={plainText} md={text} mdFilename={title ? `${title} - santrauka.md` : 'santrauka.md'} />
      </div>
      <div
        className={`summary-content ${!expanded && needsExpand ? 'summary-collapsed' : ''}`}
        style={!expanded && needsExpand ? { maxHeight: collapsedHeight } : undefined}
      >
        <div ref={innerRef}>
          <ReactMarkdown>{text}</ReactMarkdown>
        </div>
      </div>
      {needsExpand && (
        <button
          className="summary-toggle"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? 'Rodyti mažiau' : 'Rodyti daugiau'}
        </button>
      )}
    </div>
  )
}

export default function LibraryPage() {
  const [items, setItems] = useState<LibraryItem[]>([])
  const [query, setQuery] = useState('')
  const [sortBy, setSortBy] = useState<SortKey>('date_desc')
  const [langFilter, setLangFilter] = useState<LangFilter>('all')
  const [currentPage, setCurrentPage] = useState(1)
  const perPage = 10
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selectedTranscript, setSelectedTranscript] = useState<TranscriptData | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)
  const [downloadItem, setDownloadItem] = useState<LibraryItem | null>(null)
  const [stats, setStats] = useState<any>(null)
  const [collections, setCollections] = useState<{id: number, name: string, count: number}[]>([])
  const [collectionFilter, setCollectionFilter] = useState<number | null>(null)
  const [categoryCounts, setCategoryCounts] = useState<{name: string, count: number}[]>([])
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null)
  const [showNewCollection, setShowNewCollection] = useState(false)
  const [newCollectionName, setNewCollectionName] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    loadItems()
    fetch(`${API}/api/stats`).then(r => r.json()).then(setStats)
    fetch(`${API}/api/collections`).then(r => r.json()).then(d => setCollections(d.collections || []))
    fetch(`${API}/api/categories`).then(r => r.json()).then(d => setCategoryCounts(d.categories || []))
  }, [])

  const loadItems = () => {
    fetch(`${API}/api/library`)
      .then(r => r.json())
      .then(data => setItems(data.items || []))
  }

  const createCollection = async () => {
    if (!newCollectionName.trim()) return
    await fetch(`${API}/api/collections`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: newCollectionName.trim() }),
    })
    setNewCollectionName('')
    setShowNewCollection(false)
    const res = await fetch(`${API}/api/collections`)
    const data = await res.json()
    setCollections(data.collections || [])
  }

  // Filter + sort
  const displayItems = useMemo(() => {
    let filtered = items

    // Category filter
    if (categoryFilter) {
      filtered = filtered.filter(i =>
        i.categories && i.categories.includes(categoryFilter)
      )
    }

    // Language filter
    if (langFilter === 'en') filtered = filtered.filter(i => i.language === 'en')
    else if (langFilter === 'lt') filtered = filtered.filter(i => i.language === 'lt')
    else if (langFilter === 'other') filtered = filtered.filter(i => i.language !== 'en' && i.language !== 'lt')

    // Search filter
    if (query.trim()) {
      const q = query.toLowerCase()
      filtered = filtered.filter(i =>
        i.title.toLowerCase().includes(q) ||
        (i.summary || '').toLowerCase().includes(q)
      )
    }

    // Sort
    const sorted = [...filtered]
    switch (sortBy) {
      case 'date_desc': sorted.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || '')); break
      case 'date_asc': sorted.sort((a, b) => (a.created_at || '').localeCompare(b.created_at || '')); break
      case 'title_asc': sorted.sort((a, b) => a.title.localeCompare(b.title)); break
      case 'title_desc': sorted.sort((a, b) => b.title.localeCompare(a.title)); break
      case 'duration_desc': sorted.sort((a, b) => b.duration - a.duration); break
      case 'duration_asc': sorted.sort((a, b) => a.duration - b.duration); break
    }

    return sorted
  }, [items, query, sortBy, langFilter, categoryFilter])

  const totalPages = Math.max(1, Math.ceil(displayItems.length / perPage))
  const safeCurrentPage = Math.min(currentPage, totalPages)
  const paginatedItems = displayItems.slice((safeCurrentPage - 1) * perPage, safeCurrentPage * perPage)

  // Reset to page 1 when filters change
  useEffect(() => { setCurrentPage(1) }, [query, sortBy, langFilter])

  // Language counts for filter badges
  const langCounts = useMemo(() => {
    const counts = { all: items.length, en: 0, lt: 0, other: 0 }
    items.forEach(i => {
      if (i.language === 'en') counts.en++
      else if (i.language === 'lt') counts.lt++
      else counts.other++
    })
    return counts
  }, [items])

  // Total duration
  const totalDuration = useMemo(() => {
    const secs = displayItems.reduce((sum, i) => sum + i.duration, 0)
    const h = Math.floor(secs / 3600)
    const m = Math.floor((secs % 3600) / 60)
    if (h > 0) return `${h} val ${m} min`
    return `${m} min`
  }, [displayItems])

  const openTranscript = async (videoId: string) => {
    if (selectedId === videoId) {
      setSelectedId(null)
      setSelectedTranscript(null)
      return
    }
    setSelectedId(videoId)
    setDetailLoading(true)
    try {
      const res = await fetch(`${API}/api/transcripts/${videoId}`)
      if (res.ok) {
        const data = await res.json()
        setSelectedTranscript(data)
      }
    } catch { /* ignore */ }
    setDetailLoading(false)
  }

  const handleDelete = async (videoId: string) => {
    try {
      await fetch(`${API}/api/transcripts/${videoId}`, { method: 'DELETE' })
      setItems(prev => prev.filter(i => i.video_id !== videoId))
      if (selectedId === videoId) {
        setSelectedId(null)
        setSelectedTranscript(null)
      }
    } catch { /* ignore */ }
    setDeleteConfirm(null)
  }

  const downloadMD = (videoId: string) => {
    window.open(`${API}/api/transcripts/${videoId}/md`, '_blank')
  }

  const downloadSRT = (videoId: string) => {
    window.open(`${API}/api/transcripts/${videoId}/srt`, '_blank')
  }

  return (
    <div className="library-page">
      <div className="lib-header">
        <div>
          <h1 className="lib-title">Biblioteka</h1>
          <p className="lib-subtitle">
            {items.length} {items.length === 1 ? 'transkripcija' : 'transkripcijos'} · {totalDuration}
          </p>
        </div>
      </div>

      {/* Stats cards */}
      {stats && stats.total > 0 && (
        <div className="stats-row">
          <div className="stat-card">
            <div className="stat-value">{stats.total}</div>
            <div className="stat-label">Iš viso</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.week_count}</div>
            <div className="stat-label">Šią savaitę</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{Math.round(stats.total_duration / 3600 * 10) / 10}h</div>
            <div className="stat-label">Bendra trukmė</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{Math.round(stats.avg_duration / 60)}min</div>
            <div className="stat-label">Vid. trukmė</div>
          </div>
        </div>
      )}

      {/* Category filter tabs */}
      {categoryCounts.length > 0 && (
        <div className="category-tabs" role="tablist">
          <button
            className={`category-tab ${categoryFilter === null ? 'active' : ''}`}
            role="tab"
            aria-selected={categoryFilter === null}
            onClick={() => setCategoryFilter(null)}
          >
            Visos
          </button>
          {categoryCounts.map(c => (
            <button
              key={c.name}
              className={`category-tab ${categoryFilter === c.name ? 'active' : ''}`}
              role="tab"
              aria-selected={categoryFilter === c.name}
              onClick={() => setCategoryFilter(categoryFilter === c.name ? null : c.name)}
            >
              {CATEGORY_LABELS_LT[c.name] || c.name}
              <span className="category-tab-count">({c.count})</span>
            </button>
          ))}
        </div>
      )}

      {/* Collections */}
      {(collections.length > 0 || showNewCollection) && (
        <div className="collections-bar">
          <div className="collections-list">
            <button
              className={`filter-btn ${collectionFilter === null ? 'active' : ''}`}
              onClick={() => setCollectionFilter(null)}
            >
              Visos
            </button>
            {collections.map(c => (
              <button
                key={c.id}
                className={`filter-btn ${collectionFilter === c.id ? 'active' : ''}`}
                onClick={() => setCollectionFilter(collectionFilter === c.id ? null : c.id)}
                title={`${c.count} transkripcijų`}
              >
                {c.name} ({c.count})
              </button>
            ))}
            <button className="filter-btn" onClick={() => setShowNewCollection(true)}>+</button>
          </div>
          {showNewCollection && (
            <div className="new-collection-row">
              <input
                className="new-collection-input"
                type="text"
                placeholder="Kolekcijos pavadinimas..."
                value={newCollectionName}
                onChange={e => setNewCollectionName(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && createCollection()}
                autoFocus
              />
              <button className="btn-sm" onClick={createCollection}>Sukurti</button>
              <button className="btn-sm" onClick={() => setShowNewCollection(false)}>Atšaukti</button>
            </div>
          )}
        </div>
      )}

      {/* Search */}
      <input
        className="library-search"
        type="text"
        placeholder="Ieškoti pagal pavadinimą ar santrauką..."
        value={query}
        onChange={e => setQuery(e.target.value)}
      />

      {/* Filters + Sort */}
      <div className="lib-controls">
        <div className="lib-filters">
          <button
            className={`filter-btn ${langFilter === 'all' ? 'active' : ''}`}
            onClick={() => setLangFilter('all')}
          >
            Visos ({langCounts.all})
          </button>
          {langCounts.en > 0 && (
            <button
              className={`filter-btn ${langFilter === 'en' ? 'active' : ''}`}
              onClick={() => setLangFilter('en')}
            >
              English ({langCounts.en})
            </button>
          )}
          {langCounts.lt > 0 && (
            <button
              className={`filter-btn ${langFilter === 'lt' ? 'active' : ''}`}
              onClick={() => setLangFilter('lt')}
            >
              Lietuvių ({langCounts.lt})
            </button>
          )}
          {langCounts.other > 0 && (
            <button
              className={`filter-btn ${langFilter === 'other' ? 'active' : ''}`}
              onClick={() => setLangFilter('other')}
            >
              Kitos ({langCounts.other})
            </button>
          )}
        </div>

        <select
          className="lib-sort"
          value={sortBy}
          onChange={e => setSortBy(e.target.value as SortKey)}
        >
          <option value="date_desc">Naujausi pirmi</option>
          <option value="date_asc">Seniausi pirmi</option>
          <option value="title_asc">Pavadinimas A-Z</option>
          <option value="title_desc">Pavadinimas Z-A</option>
          <option value="duration_desc">Ilgiausi pirmi</option>
          <option value="duration_asc">Trumpiausi pirmi</option>
        </select>
      </div>

      {/* Empty states */}
      {displayItems.length === 0 && !query && langFilter === 'all' && (
        <div className="empty-state">
          <p>Dar nėra transkripcijų.</p>
          <button className="btn-primary" onClick={() => navigate('/')}>Pradėkite pirmą!</button>
        </div>
      )}

      {displayItems.length === 0 && (query || langFilter !== 'all') && (
        <div className="empty-state">
          <p>Nieko nerasta</p>
        </div>
      )}

      {/* Items grid */}
      <div className="lib-grid">
        {paginatedItems.map(item => (
          <div key={item.video_id} className={`lib-card ${selectedId === item.video_id ? 'expanded' : ''}`}>
            <div className="lib-card-body" onClick={() => openTranscript(item.video_id)}>
              <div className="lib-card-content">
                {item.categories && item.categories.length > 0 && (
                  <div className="lib-card-categories">
                    {item.categories.slice(0, 2).map((cat, i) => (
                      <span key={cat}>
                        {i > 0 && <span className="category-sep"> · </span>}
                        <span className="category-label">
                          {CATEGORY_LABELS_LT[cat] || cat}
                        </span>
                      </span>
                    ))}
                    {item.categories.length > 2 && (
                      <span className="category-overflow"> +{item.categories.length - 2}</span>
                    )}
                  </div>
                )}
                {item.category_status === 'pending' && (
                  <div className="lib-card-categories category-pending">
                    Kategorizuojama...
                  </div>
                )}
                <div className="lib-card-title">{item.title}</div>
                {item.channel_name && (
                  <div className="lib-card-channel">{item.channel_name}</div>
                )}
                {(item.view_count > 0 || item.like_count > 0) && (
                  <div className="lib-card-stats">
                    {item.view_count > 0 && <span>{formatCount(item.view_count)} peržiūrų</span>}
                    {item.like_count > 0 && <span>♥ {formatCount(item.like_count)}</span>}
                  </div>
                )}
              </div>
            </div>
            <div className="lib-card-footer" onClick={() => openTranscript(item.video_id)}>
              <span className="lib-card-duration">{formatDuration(item.duration)}</span>
              <span className={`badge badge-lang ${item.language === 'lt' ? 'badge-lt' : 'badge-en'}`}>
                {item.language?.toUpperCase()}
              </span>
              <span className="lib-card-date" title={formatDateTime(item.created_at)}>
                {formatRelativeDate(item.created_at)}
              </span>
            </div>

            {/* Expanded detail view */}
            {selectedId === item.video_id && (
              <div className="lib-detail">
                {detailLoading && <div className="lib-detail-loading">Kraunama...</div>}

                {selectedTranscript && !detailLoading && (
                  <>
                    {/* Actions — grouped with hierarchy */}
                    <div className="lib-detail-actions">
                      {/* Primary actions */}
                      <div className="lib-action-group">
                        <button className="btn-action btn-action-primary" onClick={() => navigate(`/?v=${item.video_id}`)} title="Atidaryti su video grotuvu ir pilna transkripcija">
                          <span className="btn-action-icon">&#8599;</span>
                          Atidaryti
                        </button>
                        <button className="btn-action btn-action-accent" onClick={() => setDownloadItem(item)} title="Atsisiųsti audio ar video failą">
                          <span className="btn-action-icon">&#8595;</span>
                          Media
                        </button>
                      </div>

                      {/* Export actions */}
                      <div className="lib-action-group lib-action-exports">
                        <span className="lib-action-group-label">Eksportas</span>
                        <button className="btn-action btn-action-ghost" onClick={() => downloadMD(item.video_id)} title="Atsisiųsti Markdown failą su visa transkripcija">
                          MD
                        </button>
                        <button className="btn-action btn-action-ghost" onClick={() => downloadSRT(item.video_id)} title="Atsisiųsti subtitrų failą (SRT formatas)">
                          SRT
                        </button>
                        <button className="btn-action btn-action-ghost" onClick={() => {
                          const text = mergeSegments(selectedTranscript.segments).join('\n\n')
                          navigator.clipboard.writeText(text)
                        }} title="Kopijuoti visą transkripciją į iškarpinę">
                          Kopijuoti
                        </button>
                      </div>

                      <div className="lib-actions-spacer" />

                      {/* Destructive action */}
                      {deleteConfirm === item.video_id ? (
                        <div className="lib-action-group">
                          <span className="delete-confirm-text">Tikrai ištrinti?</span>
                          <button className="btn-action btn-action-danger" onClick={() => handleDelete(item.video_id)}>
                            Taip
                          </button>
                          <button className="btn-action btn-action-ghost" onClick={() => setDeleteConfirm(null)}>Ne</button>
                        </div>
                      ) : (
                        <button className="btn-action btn-action-danger-ghost" onClick={() => setDeleteConfirm(item.video_id)} title="Ištrinti šią transkripciją visam laikui">
                          Ištrinti
                        </button>
                      )}
                    </div>

                    {/* Video embed */}
                    <div className="lib-detail-video">
                      <iframe
                        className="lib-video-embed"
                        src={`https://www.youtube.com/embed/${selectedTranscript.video_id}`}
                        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                        allowFullScreen
                      />
                    </div>

                    {/* Info bar */}
                    <div className="lib-detail-info">
                      <span>{formatDuration(selectedTranscript.duration)}</span>
                      <span>{selectedTranscript.language.toUpperCase()}</span>
                      <span>{selectedTranscript.source !== 'whisper' ? 'YouTube subtitrai' : 'Whisper AI'}</span>
                      <span>{formatDateTime(item.created_at)}</span>
                    </div>

                    {/* Summary */}
                    {selectedTranscript.summary && (
                      <LibrarySummaryBox text={selectedTranscript.summary} title={item.title} />
                    )}

                    {/* Translation */}
                    {selectedTranscript.translated_text && (
                      <CollapsibleCard
                        className="lib-detail-translation"
                        label="Vertimas (LT)"
                        copyText={selectedTranscript.translated_text}
                        copyMd={`## Vertimas (LT)\n\n${selectedTranscript.translated_text}`}
                        mdFilename={`${item.title} - vertimas.md`}
                      >
                        {selectedTranscript.translated_text.split('\n\n').map((para, i) => (
                          <p key={i}>{para}</p>
                        ))}
                      </CollapsibleCard>
                    )}

                    {/* Transcript text */}
                    <div className="lib-detail-transcript">
                      <div className="lib-detail-header">
                        <div className="lib-detail-label">Transkripcija</div>
                        <CopyButtons
                          text={mergeSegments(selectedTranscript.segments).join('\n\n')}
                          md={`## Transkripcija\n\n${mergeSegments(selectedTranscript.segments).join('\n\n')}`}
                          mdFilename={`${item.title} - transkripcija.md`}
                        />
                      </div>
                      <div className="lib-detail-text">
                        {mergeSegments(selectedTranscript.segments).map((para, i) => (
                          <p key={i}>{para}</p>
                        ))}
                      </div>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="lib-pagination">
          <button
            className="lib-pagination-btn"
            disabled={safeCurrentPage === 1}
            onClick={() => setCurrentPage(p => p - 1)}
          >
            ‹
          </button>
          {Array.from({ length: totalPages }, (_, i) => i + 1).map(page => (
            <button
              key={page}
              className={`lib-pagination-btn ${page === safeCurrentPage ? 'active' : ''}`}
              onClick={() => setCurrentPage(page)}
            >
              {page}
            </button>
          ))}
          <button
            className="lib-pagination-btn"
            disabled={safeCurrentPage === totalPages}
            onClick={() => setCurrentPage(p => p + 1)}
          >
            ›
          </button>
          <span className="lib-pagination-info">
            {(safeCurrentPage - 1) * perPage + 1}–{Math.min(safeCurrentPage * perPage, displayItems.length)} iš {displayItems.length}
          </span>
        </div>
      )}
      {downloadItem && (
        <DownloadModal
          url={downloadItem.url}
          videoId={downloadItem.video_id}
          title={downloadItem.title}
          duration={downloadItem.duration}
          onClose={() => setDownloadItem(null)}
        />
      )}
    </div>
  )
}

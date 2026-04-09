import { useState, useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import { API } from '../App'
import DownloadModal from '../components/DownloadModal'
import './TranscribePage.css'

interface Segment {
  start: number
  end: number
  text: string
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
  channel_name: string
  view_count: number
  like_count: number
  segments: Segment[]
  timing?: { download_s: number; transcribe_s: number; summary_s: number }
  model_hint?: string
}

interface Props {
  onTranscribed: (item: {video_id: string, title: string, language: string}) => void
  onTitleChange?: (title: string | undefined) => void
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function formatCount(n: number): string {
  if (!n) return ''
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1).replace(/\.0$/, '')}K`
  return String(n)
}

const JOB_STORAGE_KEY = 'diko_active_job'

function formatEta(seconds: number): string {
  if (seconds < 60) return 'mažiau nei minutė'
  const m = Math.round(seconds / 60)
  if (m === 1) return '~1 min'
  return `~${m} min`
}

function getProgressText(
  stage: string,
  progress: number,
  queuePosition: number,
  title: string,
  videoDuration: number,
  eta: number | null,
): string {
  const pct = Math.round(progress * 100)
  if (stage === 'downloading') return `${pct}% · Atsiunčiama...`
  if (stage === 'transcribing') {
    let text = `${pct}% · Transkribuojama...`
    if (title) text = `${pct}% · ${title}`
    if (videoDuration > 600) {
      text += ` (${Math.round(videoDuration / 60)} min video)`
    }
    if (eta !== null && eta > 0) text += ` · liko ${formatEta(eta)}`
    return text
  }
  if (stage === 'summarizing') return `${pct}% · Santrauka...`
  if (queuePosition > 0) return `Eilėje... (pozicija: ${queuePosition})`
  return `${pct}% · Eilėje...`
}

function SummaryBox({ text }: { text: string }) {
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

  return (
    <div className="summary-box">
      <div className="summary-label">AI Santrauka</div>
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

export default function TranscribePage({ onTranscribed, onTitleChange }: Props) {
  const [searchParams] = useSearchParams()
  const [url, setUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [progress, setProgress] = useState(0)
  const [stage, setStage] = useState('')
  const [queuePosition, setQueuePosition] = useState(0)
  const [title, setTitle] = useState('')
  const [videoDuration, setVideoDuration] = useState(0)
  const [eta, setEta] = useState<number | null>(null)
  const [transcript, setTranscript] = useState<TranscriptData | null>(null)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [showVideo, setShowVideo] = useState(true)
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [modelHint, setModelHint] = useState('')
  const [viewMode, setViewMode] = useState<'subtitles' | 'text' | 'translation'>('text')
  const [translating, setTranslating] = useState(false)
  const [translateDone, setTranslateDone] = useState(false)
  const [regeneratingSummary, setRegeneratingSummary] = useState(false)
  const [isDragOver, setIsDragOver] = useState(false)
  const [showDownloadModal, setShowDownloadModal] = useState(false)
  const playerRef = useRef<HTMLIFrameElement>(null)
  const etaRef = useRef<{ time: number; progress: number }[]>([])
  function connectToJob(jobId: string, _savedUrl?: string) {
    void _savedUrl
    setLoading(true)
    setError('')
    setProgress(0)
    setStage('queued')
    setQueuePosition(0)
    setEta(null)
    setActiveJobId(jobId)
    setModelHint('')
    etaRef.current = []

    const eventSource = new EventSource(`${API}/api/jobs/${jobId}/stream`)

    eventSource.addEventListener('queued', (e) => {
      const d = JSON.parse(e.data)
      setQueuePosition(d.queue_position)
      setStage('queued')
    })

    eventSource.addEventListener('progress', (e) => {
      const d = JSON.parse(e.data)
      setProgress(d.progress)
      setStage(d.stage)
      setQueuePosition(0)
      if (d.title) setTitle(d.title)
      if (d.duration) setVideoDuration(d.duration)

      // Calculate ETA from progress rate
      if (d.progress > 0) {
        const now = Date.now() / 1000
        const samples = etaRef.current
        samples.push({ time: now, progress: d.progress })
        if (samples.length > 10) samples.shift()
        if (samples.length >= 2) {
          const first = samples[0]
          const last = samples[samples.length - 1]
          const dt = last.time - first.time
          const dp = last.progress - first.progress
          if (dp > 0 && dt > 0) {
            const rate = dp / dt
            const remaining = (1 - last.progress) / rate
            setEta(remaining)
          }
        }
      }
    })

    eventSource.addEventListener('complete', (e) => {
      const d = JSON.parse(e.data)
      setTranscript(d)
      setLoading(false)
      setActiveJobId(null)
      if (d.model_hint === 'non_en_small') {
        setModelHint('Pastaba: ne-anglų kalboms "medium" modelis tiksliau transkribuoja')
      }
      eventSource.close()
      sessionStorage.removeItem(JOB_STORAGE_KEY)
      onTranscribed({ video_id: d.video_id, title: d.title, language: d.language })
    })

    eventSource.addEventListener('cancelled', () => {
      setLoading(false)
      setActiveJobId(null)
      setError('Transkripcija atšaukta.')
      eventSource.close()
      sessionStorage.removeItem(JOB_STORAGE_KEY)
    })

    eventSource.addEventListener('error', (e) => {
      if (e instanceof MessageEvent) {
        const d = JSON.parse(e.data)
        setError(d.message)
      } else {
        setError('Ryšys nutrūko. Bandykite dar kartą.')
      }
      setLoading(false)
      setActiveJobId(null)
      eventSource.close()
      sessionStorage.removeItem(JOB_STORAGE_KEY)
    })
  }

  // Load cached transcript from URL params, or reconnect to active job
  useEffect(() => {
    const vid = searchParams.get('v')
    if (vid) {
      fetch(`${API}/api/transcripts/${vid}`)
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          if (data) {
            setTranscript(data)
            setUrl(data.url || '')
            onTitleChange?.(data.title)
          }
        })
      return
    }
    onTitleChange?.(undefined)

    // Reconnect to active job from sessionStorage
    const saved = sessionStorage.getItem(JOB_STORAGE_KEY)
    if (saved) {
      try {
        const { job_id, url: savedUrl } = JSON.parse(saved)
        if (job_id) {
          setUrl(savedUrl || '')
          connectToJob(job_id, savedUrl)
        }
      } catch {
        sessionStorage.removeItem(JOB_STORAGE_KEY)
      }
    }
  }, [searchParams])

  const handleSubmit = async () => {
    if (!url.trim()) return
    setError('')
    setLoading(true)
    setProgress(0)
    setStage('queued')
    setTranscript(null)
    setTitle('')
    setVideoDuration(0)
    setEta(null)

    try {
      const res = await fetch(`${API}/api/transcribe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url.trim() }),
      })

      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Failed to submit')
      }

      const data = await res.json()

      if (data.status === 'complete') {
        setTranscript(data.transcript)
        setLoading(false)
        onTranscribed({ video_id: data.video_id, title: data.transcript.title, language: data.transcript.language })
        return
      }

      // Save job to sessionStorage for reconnection
      sessionStorage.setItem(JOB_STORAGE_KEY, JSON.stringify({
        job_id: data.job_id,
        url: url.trim(),
      }))

      connectToJob(data.job_id)

    } catch (e: any) {
      setError(e.message)
      setLoading(false)
    }
  }

  const seekTo = (seconds: number) => {
    if (playerRef.current?.contentWindow) {
      playerRef.current.contentWindow.postMessage(
        JSON.stringify({ event: 'command', func: 'seekTo', args: [seconds, true] }),
        '*'
      )
    }
  }

  // Merge segments into readable paragraphs based on pauses
  const mergedParagraphs = (() => {
    if (!transcript) return []
    const PAUSE_THRESHOLD = 2.0 // seconds gap = new paragraph
    const paragraphs: { start: number; text: string; segmentIndices: number[] }[] = []
    let current: { start: number; parts: string[]; indices: number[] } | null = null

    transcript.segments.forEach((seg, i) => {
      if (!current) {
        current = { start: seg.start, parts: [seg.text], indices: [i] }
        return
      }

      const gap = seg.start - (transcript.segments[i - 1]?.end ?? seg.start)

      if (gap >= PAUSE_THRESHOLD) {
        // Finish current paragraph, start new one
        paragraphs.push({
          start: current.start,
          text: current.parts.join(' '),
          segmentIndices: current.indices,
        })
        current = { start: seg.start, parts: [seg.text], indices: [i] }
      } else {
        // Continue current paragraph
        current.parts.push(seg.text)
        current.indices.push(i)
      }
    })

    const last = current as { start: number; parts: string[]; indices: number[] } | null
    if (last && last.parts.length > 0) {
      paragraphs.push({
        start: last.start,
        text: last.parts.join(' '),
        segmentIndices: last.indices,
      })
    }

    return paragraphs
  })()

  // Filter paragraphs by search query
  const filteredParagraphs = search
    ? mergedParagraphs.filter(p => p.text.toLowerCase().includes(search.toLowerCase()))
    : mergedParagraphs

  const copyTranscript = () => {
    if (!transcript) return
    if (viewMode === 'translation' && transcript.translated_text) {
      navigator.clipboard.writeText(transcript.translated_text)
    } else if (viewMode === 'text') {
      const text = mergedParagraphs.map(p => p.text).join('\n\n')
      navigator.clipboard.writeText(text)
    } else {
      const text = transcript.segments.map(s => `[${formatTime(s.start)}] ${s.text}`).join('\n')
      navigator.clipboard.writeText(text)
    }
  }

  const cancelJob = async () => {
    if (!activeJobId) return
    try {
      await fetch(`${API}/api/jobs/${activeJobId}/cancel`, { method: 'POST' })
    } catch {
      // Best effort
    }
  }

  const reTranscribe = async () => {
    if (!transcript) return
    setError('')
    setLoading(true)
    setProgress(0)
    setStage('queued')
    setTranscript(null)
    setModelHint('')

    try {
      const res = await fetch(`${API}/api/transcribe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: transcript.url, force_whisper: true }),
      })

      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Failed to submit')
      }

      const data = await res.json()

      if (data.status === 'complete') {
        setTranscript(data.transcript)
        setLoading(false)
        onTranscribed({ video_id: data.video_id, title: data.transcript.title, language: data.transcript.language })
        return
      }

      sessionStorage.setItem(JOB_STORAGE_KEY, JSON.stringify({
        job_id: data.job_id,
        url: transcript.url,
      }))
      connectToJob(data.job_id)
    } catch (e: any) {
      setError(e.message)
      setLoading(false)
    }
  }

  const downloadSRT = () => {
    if (!transcript) return
    let srt = ''
    transcript.segments.forEach((s, i) => {
      const start = new Date(s.start * 1000).toISOString().substring(11, 23).replace('.', ',')
      const end = new Date(s.end * 1000).toISOString().substring(11, 23).replace('.', ',')
      srt += `${i + 1}\n${start} --> ${end}\n${s.text}\n\n`
    })
    const blob = new Blob([srt], { type: 'text/srt' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${transcript.title || 'transcript'}.srt`
    a.click()
  }

  const downloadMD = () => {
    if (!transcript) return
    window.open(`${API}/api/transcripts/${transcript.video_id}/md`, '_blank')
  }

  const translateToLT = async () => {
    if (!transcript) return
    setTranslating(true)
    setTranslateDone(false)
    setError('')
    try {
      const res = await fetch(`${API}/api/transcripts/${transcript.video_id}/translate`, {
        method: 'POST',
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Vertimas nepavyko')
      }
      const data = await res.json()
      setTranscript({ ...transcript, translated_text: data.translated_text })
      setViewMode('translation')
      setTranslateDone(true)
      setTimeout(() => setTranslateDone(false), 3000)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setTranslating(false)
    }
  }

  const regenerateSummary = async () => {
    if (!transcript) return
    setRegeneratingSummary(true)
    try {
      const res = await fetch(`${API}/api/transcripts/${transcript.video_id}/regenerate-summary`, {
        method: 'POST',
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Nepavyko')
      }
      const data = await res.json()
      setTranscript({ ...transcript, summary: data.summary, summary_status: 'done' })
    } catch (e: any) {
      setError(e.message)
    } finally {
      setRegeneratingSummary(false)
    }
  }

  // Drag & drop
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(true)
  }
  const handleDragLeave = () => setIsDragOver(false)
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    const text = e.dataTransfer.getData('text/plain') || e.dataTransfer.getData('text/uri-list')
    if (text && (text.includes('youtube.com') || text.includes('youtu.be'))) {
      setUrl(text.trim())
    }
  }

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!transcript) return
      const target = e.target as HTMLElement
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') return

      if (e.key === ' ' && playerRef.current?.contentWindow) {
        e.preventDefault()
        playerRef.current.contentWindow.postMessage(
          JSON.stringify({ event: 'command', func: 'playVideo', args: [] }),
          '*'
        )
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [transcript])

  const filteredSegments = transcript?.segments.filter(
    s => !search || s.text.toLowerCase().includes(search.toLowerCase())
  )

  const youtubeEmbedUrl = transcript
    ? `https://www.youtube.com/embed/${transcript.video_id}?enablejsapi=1`
    : null

  // Handle multi-URL paste (batch)
  const handleUrlChange = (value: string) => {
    // If pasted text contains multiple URLs (newlines), offer batch
    if (value.includes('\n') && value.trim().split('\n').filter(l => l.trim()).length > 1) {
      const urls = value.trim().split('\n').filter(l => l.trim())
      if (urls.length > 1 && urls.every(u => u.includes('youtube.com') || u.includes('youtu.be'))) {
        handleBatchSubmit(urls)
        return
      }
    }
    setUrl(value)
  }

  const handleBatchSubmit = async (urls: string[]) => {
    setError('')
    setLoading(true)
    setStage('batch')
    try {
      const res = await fetch(`${API}/api/transcribe/batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ urls }),
      })
      if (!res.ok) throw new Error('Batch failed')
      const data = await res.json()
      const queued = data.jobs.filter((j: any) => j.status === 'queued')
      if (queued.length > 0) {
        setUrl('')
        connectToJob(queued[0].job_id)
      } else {
        setLoading(false)
      }
    } catch (e: any) {
      setError(e.message)
      setLoading(false)
    }
  }

  // Empty state (no transcript, not loading)
  if (!transcript && !loading && !error) {
    return (
      <div
        className={`hero-empty ${isDragOver ? 'drag-over' : ''}`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <h1>Transkribuokite YouTube video</h1>
        <p>Įklijuokite nuorodą, nutempkite, arba įklijuokite kelis URL</p>
        <div className="url-row">
          <input
            className="url-input mono"
            type="text"
            placeholder="https://youtube.com/watch?v=... (arba kelis URL atskiriant Enter)"
            value={url}
            onChange={e => handleUrlChange(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSubmit()}
          />
          <button className="btn-primary" onClick={handleSubmit}>Transkribuoti</button>
          <button className="btn-secondary" onClick={() => url.trim() && setShowDownloadModal(true)}>⬇ Atsisiųsti</button>
        </div>
        {showDownloadModal && !transcript && (
          <DownloadModal
            url={url.trim()}
            onClose={() => setShowDownloadModal(false)}
          />
        )}
      </div>
    )
  }

  return (
    <div onDragOver={handleDragOver} onDragLeave={handleDragLeave} onDrop={handleDrop}>
      <h1 className="page-title">Naujas transkribavimas</h1>

      {isDragOver && (
        <div className="drop-overlay">Numeskite YouTube nuorodą čia</div>
      )}

      <div className="url-row">
        <input
          className="url-input mono"
          type="text"
          placeholder="https://youtube.com/watch?v=... (arba kelis URL)"
          value={url}
          onChange={e => handleUrlChange(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSubmit()}
        />
        <button className="btn-primary" onClick={handleSubmit} disabled={loading}>
          {loading ? 'Vykdoma...' : 'Transkribuoti'}
        </button>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {loading && (
        <div className="progress-row">
          <img src="/logo.svg" alt="Vykdoma..." style={{ width: '48px', height: '48px', marginRight: '16px', borderRadius: '12px' }} />
          <span className="progress-text">
            {getProgressText(stage, progress, queuePosition, title, videoDuration, eta)}
          </span>
          {activeJobId && (
            <button className="btn-sm" onClick={cancelJob} style={{ marginLeft: 8 }}>
              Atšaukti
            </button>
          )}
        </div>
      )}

      {modelHint && (
        <div className="alert alert-info" style={{ marginTop: 8 }}>
          {modelHint}
        </div>
      )}

      {transcript && (
        <div className="result-layout">
          <div className="video-column">
            {showVideo && youtubeEmbedUrl && (
              <div className="video-card">
                <button className="video-close" onClick={() => setShowVideo(false)}>&times;</button>
                <iframe
                  ref={playerRef}
                  className="video-embed"
                  src={youtubeEmbedUrl}
                  allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                  allowFullScreen
                />
                <div className="video-info">
                  <div className="video-title">{transcript.title}</div>
                  {(transcript.channel_name || transcript.view_count > 0) && (
                    <div className="video-channel-row">
                      {transcript.channel_name && <span className="video-channel">{transcript.channel_name}</span>}
                      {transcript.view_count > 0 && <span className="video-stat">{formatCount(transcript.view_count)} peržiūrų</span>}
                      {transcript.like_count > 0 && <span className="video-stat">♥ {formatCount(transcript.like_count)}</span>}
                    </div>
                  )}
                  <div className="video-meta-row">
                    {formatTime(transcript.duration)} &middot;
                    <span className="badge badge-accent">{transcript.language.toUpperCase()}</span>
                    {transcript.source && transcript.source !== 'whisper' && (
                      <span className="badge badge-info" title={transcript.source === 'youtube_manual' ? 'YouTube subtitrai (rankinis)' : 'YouTube subtitrai (auto)'}>
                        YT
                      </span>
                    )}
                    {transcript.source === 'whisper' && (
                      <span className="badge badge-whisper" title="Transkribuota su Whisper AI">
                        Whisper
                      </span>
                    )}
                  </div>
                </div>
              </div>
            )}

            {transcript.summary && (
              <SummaryBox text={transcript.summary} />
            )}

            {!transcript.summary && !loading && (
              <div className={`summary-box summary-unavailable ${transcript.summary_status === 'pending' ? 'summary-shimmer' : ''}`}>
                <div className="summary-label">AI Santrauka</div>
                <p>
                  {transcript.summary_status === 'failed'
                    ? 'Santraukos generavimas nepavyko.'
                    : transcript.summary_status === 'no_key'
                    ? 'Nustatykite OpenRouter API raktą nustatymuose.'
                    : transcript.summary_status === 'pending'
                    ? 'Generuojama...'
                    : 'Santrauka nepasiekiama.'}
                </p>
              </div>
            )}

            <div className="video-actions" style={{ display: 'flex', gap: 4, marginTop: 8, flexWrap: 'wrap' }}>
              {transcript.source && transcript.source !== 'whisper' && !loading && (
                <button className="btn-sm" onClick={reTranscribe}>
                  Transkribuoti su Whisper
                </button>
              )}
              {!loading && (
                <button
                  className={`btn-sm ${regeneratingSummary ? 'btn-shimmer' : ''}`}
                  onClick={regenerateSummary}
                  disabled={regeneratingSummary}
                >
                  {regeneratingSummary ? 'Generuojama...' : 'Pergeneruoti santrauką'}
                </button>
              )}
              {!loading && (
                <button className="btn-sm" onClick={() => setShowDownloadModal(true)}>
                  ⬇ Atsisiųsti media
                </button>
              )}
            </div>
          </div>

          <div className="transcript-column">
            <div className="transcript-card">
              <div className="transcript-toolbar">
                <h3>Transkripcija</h3>
                <div className="toolbar-actions">
                  <div className="view-toggle">
                    <button
                      className={`btn-sm ${viewMode === 'text' ? 'btn-sm-active' : ''}`}
                      onClick={() => setViewMode('text')}
                    >
                      Tekstas
                    </button>
                    <button
                      className={`btn-sm ${viewMode === 'translation' ? 'btn-sm-active' : ''} ${translating ? 'btn-shimmer' : ''} ${translateDone ? 'btn-done' : ''}`}
                      onClick={() => transcript?.translated_text ? setViewMode('translation') : translateToLT()}
                      disabled={translating}
                    >
                      {translating ? 'Verčiama...' : translateDone ? 'Išversta!' : 'LT vertimas'}
                    </button>
                    <button
                      className={`btn-sm ${viewMode === 'subtitles' ? 'btn-sm-active' : ''}`}
                      onClick={() => setViewMode('subtitles')}
                    >
                      Subtitrai
                    </button>
                  </div>
                  <button className="btn-sm" onClick={copyTranscript}>Kopijuoti</button>
                  <button className="btn-sm" onClick={downloadSRT}>SRT</button>
                  <button className="btn-sm" onClick={downloadMD}>MD</button>
                  <button className="btn-sm" onClick={() => transcript && window.open(`${API}/api/transcripts/${transcript.video_id}/txt`, '_blank')}>TXT</button>
                  <button className="btn-sm" onClick={() => transcript && window.open(`${API}/api/transcripts/${transcript.video_id}/json`, '_blank')}>JSON</button>
                </div>
              </div>
              <input
                className="transcript-search"
                type="text"
                placeholder="Ieškoti..."
                value={search}
                onChange={e => setSearch(e.target.value)}
              />

              {viewMode === 'text' ? (
                <div className="transcript-text">
                  {filteredParagraphs.map((p, i) => (
                    <p
                      key={i}
                      className="t-paragraph"
                      onClick={() => seekTo(p.start)}
                    >
                      <span className="t-para-time">{formatTime(p.start)}</span>
                      {p.text}
                    </p>
                  ))}
                </div>
              ) : viewMode === 'translation' ? (
                <div className="transcript-text">
                  {transcript?.translated_text ? (
                    transcript.translated_text.split('\n\n').map((para, i) => (
                      <p key={i} className="t-paragraph">
                        {para}
                      </p>
                    ))
                  ) : (
                    <div className="translation-empty">
                      <p>Vertimas dar nesukurtas.</p>
                      <button className="btn-primary" onClick={translateToLT} disabled={translating}>
                        {translating ? 'Verčiama...' : 'Versti į lietuvių kalbą'}
                      </button>
                    </div>
                  )}
                  {transcript?.translated_text && (
                    <button
                      className="btn-sm"
                      onClick={translateToLT}
                      disabled={translating}
                      style={{ marginTop: 8 }}
                    >
                      {translating ? 'Verčiama...' : 'Versti iš naujo'}
                    </button>
                  )}
                </div>
              ) : (
                <div className="transcript-lines">
                  {filteredSegments?.map((s, i) => (
                    <div key={i} className="t-line" onClick={() => seekTo(s.start)}>
                      <span className="t-time">{formatTime(s.start)}</span>
                      <span className="t-text">{s.text}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {showDownloadModal && transcript && (
        <DownloadModal
          url={transcript.url}
          videoId={transcript.video_id}
          title={transcript.title}
          duration={transcript.duration}
          onClose={() => setShowDownloadModal(false)}
        />
      )}
    </div>
  )
}

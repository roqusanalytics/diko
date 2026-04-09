import { useState, useEffect, useRef } from 'react'
import { API } from '../App'
import './DownloadModal.css'

interface Props {
  url: string
  videoId?: string
  title?: string
  duration?: number
  defaultFormat?: string
  defaultQuality?: string
  onClose: () => void
  onStarted?: (jobId: string) => void
  onComplete?: (jobId: string) => void
}

const AUDIO_FORMATS = ['mp3', 'm4a', 'wav', 'flac', 'ogg'] as const
const VIDEO_FORMATS = ['mp4', 'webm'] as const
const LOSSY_FORMATS = new Set(['mp3', 'ogg'])

const QUALITY_OPTIONS: Record<string, { label: string; value: string }[]> = {
  mp3: [
    { label: '320 kbps', value: '320' },
    { label: '192 kbps', value: '192' },
    { label: '128 kbps', value: '128' },
  ],
  ogg: [
    { label: '320 kbps', value: '320' },
    { label: '192 kbps', value: '192' },
    { label: '128 kbps', value: '128' },
  ],
  mp4: [
    { label: 'Geriausia', value: 'best' },
    { label: '1080p', value: '1080' },
    { label: '720p', value: '720' },
    { label: '360p', value: '360' },
  ],
  webm: [
    { label: 'Geriausia', value: 'best' },
    { label: '720p', value: '720' },
  ],
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

function estimateSize(duration: number, format: string, quality: string): number | null {
  if (!duration || duration <= 0) return null
  const bitrates: Record<string, number> = {
    'mp3-128': 128_000, 'mp3-192': 192_000, 'mp3-320': 320_000,
    'ogg-128': 128_000, 'ogg-192': 192_000, 'ogg-320': 320_000,
    'm4a-': 128_000,
    'wav-': 1_411_200,
    'flac-': 700_000,
    'mp4-360': 700_000, 'mp4-720': 2_500_000, 'mp4-1080': 5_000_000, 'mp4-best': 8_000_000,
    'webm-720': 2_000_000, 'webm-best': 6_000_000,
  }
  const key = `${format}-${quality}`
  const br = bitrates[key] || bitrates[`${format}-`]
  if (!br) return null
  return Math.round((br / 8) * duration)
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function parseTime(str: string): number | null {
  const parts = str.split(':')
  if (parts.length === 2) {
    const m = parseInt(parts[0], 10)
    const s = parseInt(parts[1], 10)
    if (!isNaN(m) && !isNaN(s)) return m * 60 + s
  }
  return null
}

export default function DownloadModal({
  url,
  videoId,
  title,
  duration,
  defaultFormat = 'mp3',
  defaultQuality = '320',
  onClose,
  onStarted,
  onComplete,
}: Props) {
  const [format, setFormat] = useState(defaultFormat)
  const [quality, setQuality] = useState(defaultQuality)
  const [showTrim, setShowTrim] = useState(false)
  const [trimStart, setTrimStart] = useState('0:00')
  const [trimEnd, setTrimEnd] = useState(duration ? formatTime(duration) : '0:00')
  const [trimError, setTrimError] = useState('')

  const [downloading, setDownloading] = useState(false)
  const [progress, setProgress] = useState(0)
  const [stage, setStage] = useState('')
  const [error, setError] = useState('')
  const [jobId, setJobId] = useState<string | null>(null)

  const eventSourceRef = useRef<EventSource | null>(null)

  // Update quality when format changes
  useEffect(() => {
    const opts = QUALITY_OPTIONS[format]
    if (opts) {
      setQuality(opts[0].value)
    } else {
      setQuality('')
    }
  }, [format])

  // Update trim end when duration changes
  useEffect(() => {
    if (duration) {
      setTrimEnd(formatTime(duration))
    }
  }, [duration])

  const hasQuality = LOSSY_FORMATS.has(format) || VIDEO_FORMATS.includes(format as any)
  const qualityOpts = QUALITY_OPTIONS[format] || []
  const estimated = estimateSize(duration || 0, format, quality)
  const isLargeFile = estimated && estimated > 500 * 1024 * 1024

  const validateTrim = (): { start: number; end: number } | null => {
    const s = parseTime(trimStart)
    const e = parseTime(trimEnd)
    if (s === null || e === null) {
      setTrimError('Neteisingas laiko formatas (M:SS)')
      return null
    }
    if (s >= e) {
      setTrimError('Pradžia turi būti mažesnė nei pabaiga')
      return null
    }
    if (e - s < 1) {
      setTrimError('Minimalus intervalas: 1 sekundė')
      return null
    }
    if (duration && e > duration) {
      setTrimError(`Pabaiga viršija trukmę (${formatTime(duration)})`)
      return null
    }
    setTrimError('')
    return { start: s, end: e }
  }

  const handleDownload = async () => {
    setError('')
    setTrimError('')

    let startTime: number | undefined
    let endTime: number | undefined

    if (showTrim) {
      const trim = validateTrim()
      if (!trim) return
      startTime = trim.start
      endTime = trim.end
    }

    setDownloading(true)
    setProgress(0)
    setStage('queued')

    try {
      const body: Record<string, any> = {
        format,
        quality,
      }
      if (videoId) body.video_id = videoId
      else body.url = url

      if (startTime !== undefined && endTime !== undefined) {
        body.start_time = startTime
        body.end_time = endTime
      }

      const res = await fetch(`${API}/api/media/download`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })

      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Nepavyko pradėti atsisiuntimo')
      }

      const data = await res.json()
      setJobId(data.job_id)
      onStarted?.(data.job_id)

      // Save format preference
      fetch(`${API}/api/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ media_format: format, media_quality: quality }),
      }).catch(() => {})

      // Connect SSE
      const es = new EventSource(`${API}/api/media/${data.job_id}/stream`)
      eventSourceRef.current = es

      es.addEventListener('progress', (e) => {
        const d = JSON.parse(e.data)
        setProgress(d.progress)
        setStage(d.stage)
      })

      es.addEventListener('complete', () => {
        setProgress(1)
        setStage('complete')
        es.close()

        // Trigger file download
        const link = document.createElement('a')
        link.href = `${API}/api/media/${data.job_id}/file`
        link.download = ''
        document.body.appendChild(link)
        link.click()
        document.body.removeChild(link)

        onComplete?.(data.job_id)

        setTimeout(() => {
          setDownloading(false)
          onClose()
        }, 1000)
      })

      es.addEventListener('error', (e) => {
        if (e instanceof MessageEvent) {
          const d = JSON.parse(e.data)
          setError(d.message)
        } else {
          setError('Ryšys nutrūko')
        }
        setDownloading(false)
        es.close()
      })

      es.addEventListener('cancelled', () => {
        setDownloading(false)
        setError('Atšaukta')
        es.close()
      })

    } catch (e: any) {
      setError(e.message)
      setDownloading(false)
    }
  }

  const handleCancel = async () => {
    if (jobId) {
      await fetch(`${API}/api/media/${jobId}/cancel`, { method: 'POST' }).catch(() => {})
    }
    eventSourceRef.current?.close()
    setDownloading(false)
    onClose()
  }

  const progressPct = Math.round(progress * 100)

  return (
    <div className="dm-overlay" onClick={(e) => e.target === e.currentTarget && !downloading && onClose()}>
      <div className="dm-modal">
        <h2 className="dm-title">⬇ Atsisiųsti media</h2>
        {title && <p className="dm-video-title">{title}</p>}

        {!downloading ? (
          <>
            {/* Audio formats */}
            <div className="dm-section-label">AUDIO</div>
            <div className="dm-chips">
              {AUDIO_FORMATS.map(f => (
                <button
                  key={f}
                  className={`dm-chip ${format === f ? 'dm-chip-active' : ''}`}
                  onClick={() => setFormat(f)}
                >
                  {f.toUpperCase()}
                </button>
              ))}
            </div>

            {/* Video formats */}
            <div className="dm-section-label">VIDEO</div>
            <div className="dm-chips">
              {VIDEO_FORMATS.map(f => (
                <button
                  key={f}
                  className={`dm-chip ${format === f ? 'dm-chip-active' : ''}`}
                  onClick={() => setFormat(f)}
                >
                  {f.toUpperCase()}
                </button>
              ))}
            </div>

            {/* Quality */}
            {hasQuality && qualityOpts.length > 0 && (
              <div className="dm-quality-row">
                <label className="dm-label">Kokybė</label>
                <select
                  className="dm-select"
                  value={quality}
                  onChange={e => setQuality(e.target.value)}
                >
                  {qualityOpts.map(o => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              </div>
            )}

            {!hasQuality && (
              <div className="dm-quality-row">
                <span className="dm-label-muted">
                  {format === 'wav' ? 'Originali kokybė (nesuspaustas)' :
                   format === 'flac' ? 'Originali kokybė (be nuostolių)' :
                   format === 'm4a' ? 'Originali kokybė' : ''}
                </span>
              </div>
            )}

            {/* Trim */}
            <div className="dm-trim-toggle">
              <button
                className="dm-trim-btn"
                onClick={() => setShowTrim(!showTrim)}
              >
                {showTrim ? '▾' : '▸'} Apkirpti
              </button>
            </div>
            {showTrim && (
              <div className="dm-trim-inputs">
                <div className="dm-trim-field">
                  <label className="dm-label">Nuo:</label>
                  <input
                    className="dm-time-input"
                    value={trimStart}
                    onChange={e => setTrimStart(e.target.value)}
                    placeholder="0:00"
                  />
                </div>
                <div className="dm-trim-field">
                  <label className="dm-label">Iki:</label>
                  <input
                    className="dm-time-input"
                    value={trimEnd}
                    onChange={e => setTrimEnd(e.target.value)}
                    placeholder={duration ? formatTime(duration) : '0:00'}
                  />
                </div>
              </div>
            )}
            {trimError && <div className="dm-trim-error">{trimError}</div>}

            {/* Size estimate + warning */}
            {estimated && (
              <div className={`dm-size-estimate ${isLargeFile ? 'dm-size-warning' : ''}`}>
                {isLargeFile ? '⚠ ' : ''}
                Apytikris dydis: ~{formatBytes(estimated)}
                {isLargeFile ? '. Atsisiuntimas gali užtrukti.' : ''}
              </div>
            )}

            {error && <div className="dm-error">{error}</div>}

            {/* Actions */}
            <div className="dm-actions">
              <button className="dm-download-btn" onClick={handleDownload}>
                ⬇ Atsisiųsti
              </button>
              <button className="dm-cancel-btn" onClick={onClose}>
                Atšaukti
              </button>
            </div>
          </>
        ) : (
          <>
            {/* Progress state */}
            <div className="dm-progress-info">
              <span className="dm-progress-format">
                {format.toUpperCase()}
                {hasQuality ? ` · ${quality}${LOSSY_FORMATS.has(format) ? ' kbps' : 'p'}` : ''}
              </span>
            </div>

            <div className="dm-progress-bar-track">
              <div
                className={`dm-progress-bar-fill ${stage === 'complete' ? 'dm-progress-done' : ''}`}
                style={{ width: `${progressPct}%` }}
              />
            </div>

            <div className="dm-progress-text">
              {stage === 'downloading' && `${progressPct}% · Atsisiunčiama...`}
              {stage === 'converting' && 'Konvertuojama...'}
              {stage === 'complete' && 'Baigta!'}
              {stage === 'queued' && 'Eilėje...'}
            </div>

            {error && <div className="dm-error">{error}</div>}

            {stage !== 'complete' && (
              <div className="dm-actions">
                <button className="dm-cancel-btn" onClick={handleCancel}>
                  Atšaukti
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

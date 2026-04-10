import { useState, useEffect, useRef } from 'react'
import { API } from '../App'
import { useDataCache } from '../components/DataCache'
import Dropdown from '../components/Dropdown'
import './SettingsPage.css'

interface SavedModel {
  model_id: string
  name: string
  is_favorite: number
}

interface SearchModel {
  id: string
  name: string
}

export default function SettingsPage() {
  const [apiKey, setApiKey] = useState('')
  const [whisperModel, setWhisperModel] = useState('small')
  const [language, setLanguage] = useState('')
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [hasStoredKey, setHasStoredKey] = useState(false)
  const [editingKey, setEditingKey] = useState(false)

  // Model picker state
  const [savedModels, setSavedModels] = useState<SavedModel[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<SearchModel[]>([])
  const [showSearch, setShowSearch] = useState(false)
  const [searching, setSearching] = useState(false)
  const searchRef = useRef<HTMLDivElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined)

  const { data: cache, refreshSettings } = useDataCache()

  // Load settings from cache
  useEffect(() => {
    if (cache.settings) {
      const data = cache.settings
      const storedKey = data.openrouter_api_key || ''
      setHasStoredKey(storedKey === '***')
      setApiKey(storedKey === '***' ? '' : storedKey)
      setWhisperModel(data.whisper_model || 'small')
      setLanguage(data.default_language || '')
    }
    loadSavedModels()
  }, [cache.settings])

  const loadSavedModels = () => {
    fetch(`${API}/api/models/saved`)
      .then(r => r.json())
      .then(data => setSavedModels(data.models || []))
  }

  // Close search dropdown on outside click
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setShowSearch(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  // Debounced search against OpenRouter API
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (!searchQuery.trim()) {
      setSearchResults([])
      return
    }
    setSearching(true)
    debounceRef.current = setTimeout(() => {
      fetch(`${API}/api/models/search?q=${encodeURIComponent(searchQuery.trim())}`)
        .then(r => r.json())
        .then(data => {
          const savedIds = new Set(savedModels.map(m => m.model_id))
          setSearchResults((data.models || []).filter((m: SearchModel) => !savedIds.has(m.id)))
          setSearching(false)
        })
        .catch(() => setSearching(false))
    }, 300)
  }, [searchQuery, savedModels])

  const addModel = async (id: string, name: string) => {
    await fetch(`${API}/api/models/saved`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_id: id, name }),
    })
    setSearchQuery('')
    setShowSearch(false)
    loadSavedModels()
  }

  const removeModel = async (modelId: string) => {
    await fetch(`${API}/api/models/saved/${encodeURIComponent(modelId)}`, { method: 'DELETE' })
    loadSavedModels()
  }

  const setFavorite = async (modelId: string) => {
    await fetch(`${API}/api/models/saved/${encodeURIComponent(modelId)}/favorite`, { method: 'POST' })
    loadSavedModels()
  }

  const favoriteModel = savedModels.find(m => m.is_favorite)

  const handleSave = async () => {
    setError('')
    setSaved(false)
    try {
      const res = await fetch(`${API}/api/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          openrouter_api_key: editingKey ? apiKey : '',
          openrouter_model: favoriteModel?.model_id || 'anthropic/claude-sonnet-4',
          whisper_model: whisperModel,
          default_language: language,
        }),
      })
      if (!res.ok) throw new Error('Nepavyko issaugoti')
      if (editingKey && apiKey.trim()) {
        setHasStoredKey(true)
        setEditingKey(false)
        setApiKey('')
        setShowKey(false)
      }
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (e: any) {
      setError(e.message)
    }
  }

  return (
    <div className="settings-page">
      <div className="settings-header">
        <h1 className="settings-title">Nustatymai</h1>
        <p className="settings-subtitle">Transkribavimo ir AI santraukos parametrai</p>
      </div>

      <div className="settings-cards">
      <div className="settings-card">
        <div className="card-header">
          <h2 className="card-title">AI Santrauka</h2>
          <p className="card-desc">OpenRouter API modeliai santraukoms</p>
        </div>

        <div className="card-body">
          <div className="settings-field">
            <label className="field-label">API raktas</label>

            {hasStoredKey && !editingKey ? (
              <div className="api-key-saved">
                <div className="key-status">
                  <span className="key-status-dot" />
                  <span className="key-status-text">Raktas pridetas</span>
                  <span className="key-status-masked">sk-or---------</span>
                </div>
                <button
                  className="key-change-btn"
                  onClick={() => { setEditingKey(true); setApiKey(''); setShowKey(false) }}
                  type="button"
                >
                  Keisti
                </button>
              </div>
            ) : (
              <>
                <div className="api-key-wrap">
                  <input
                    className="settings-input api-key-input"
                    type={showKey ? 'text' : 'password'}
                    placeholder="sk-or-..."
                    value={apiKey}
                    onChange={e => setApiKey(e.target.value)}
                    autoFocus={editingKey}
                  />
                  <button
                    className="key-toggle"
                    onClick={() => setShowKey(!showKey)}
                    type="button"
                    title={showKey ? 'Slepti rakta' : 'Rodyti rakta'}
                  >
                    {showKey ? (
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/>
                        <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/>
                        <line x1="1" y1="1" x2="23" y2="23"/>
                      </svg>
                    ) : (
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                        <circle cx="12" cy="12" r="3"/>
                      </svg>
                    )}
                  </button>
                </div>
                {editingKey && (
                  <button
                    className="key-cancel-btn"
                    onClick={() => { setEditingKey(false); setApiKey('') }}
                    type="button"
                  >
                    Atsaukti
                  </button>
                )}
              </>
            )}
            <p className="field-hint">Gaukite rakta: <a href="https://openrouter.ai/keys" target="_blank" rel="noopener" className="field-link">openrouter.ai/keys</a></p>
          </div>

          <div className="settings-field">
            <label className="field-label">Modelis</label>

            <div className="model-dropdown-wrap" ref={searchRef}>
              <div className="model-trigger" onClick={() => setShowSearch(!showSearch)}>
                <span className="model-trigger-text">
                  {favoriteModel ? (
                    <><span className="model-trigger-star">&#9733;</span> {favoriteModel.name}</>
                  ) : (
                    'Pasirinkite modeli...'
                  )}
                </span>
                <span className="model-trigger-chevron">{showSearch ? '\u25B2' : '\u25BC'}</span>
              </div>

              {showSearch && (
                <div className="model-dropdown">
                  <input
                    className="model-dropdown-search"
                    type="text"
                    placeholder="Ieskoti OpenRouter modeliu..."
                    value={searchQuery}
                    onChange={e => setSearchQuery(e.target.value)}
                    autoFocus
                  />

                  {savedModels.length > 0 && !searchQuery.trim() && (
                    <div className="model-dropdown-section">
                      <div className="model-dropdown-label">Išsaugoti modeliai</div>
                      {savedModels.map(m => (
                        <div key={m.model_id} className={`model-dropdown-item ${m.is_favorite ? 'is-fav' : ''}`}>
                          <button
                            className={`dd-star ${m.is_favorite ? 'active' : ''}`}
                            onClick={(e) => { e.stopPropagation(); setFavorite(m.model_id) }}
                          >
                            {m.is_favorite ? '\u2605' : '\u2606'}
                          </button>
                          <div className="dd-item-info" onClick={() => { setFavorite(m.model_id); setShowSearch(false) }}>
                            <span className="dd-item-name">{m.name}</span>
                            <span className="dd-item-id">{m.model_id}</span>
                          </div>
                          {m.is_favorite && <span className="dd-badge">default</span>}
                          <button
                            className="dd-remove"
                            onClick={(e) => { e.stopPropagation(); removeModel(m.model_id) }}
                          >
                            &times;
                          </button>
                        </div>
                      ))}
                    </div>
                  )}

                  {searchQuery.trim() && (
                    <div className="model-dropdown-section">
                      {searching && <div className="dd-status">Ieskoma...</div>}

                      {!searching && searchResults.length > 0 && (
                        <>
                          <div className="model-dropdown-label">OpenRouter modeliai</div>
                          {searchResults.map(m => (
                            <div
                              key={m.id}
                              className="model-dropdown-item"
                              onClick={() => addModel(m.id, m.name)}
                            >
                              <span className="dd-plus">+</span>
                              <div className="dd-item-info">
                                <span className="dd-item-name">{m.name}</span>
                                <span className="dd-item-id">{m.id}</span>
                              </div>
                            </div>
                          ))}
                        </>
                      )}

                      {!searching && savedModels.filter(m =>
                        m.model_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
                        m.name.toLowerCase().includes(searchQuery.toLowerCase())
                      ).length > 0 && (
                        <>
                          <div className="model-dropdown-label">Išsaugoti</div>
                          {savedModels.filter(m =>
                            m.model_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
                            m.name.toLowerCase().includes(searchQuery.toLowerCase())
                          ).map(m => (
                            <div key={m.model_id} className={`model-dropdown-item ${m.is_favorite ? 'is-fav' : ''}`}>
                              <button
                                className={`dd-star ${m.is_favorite ? 'active' : ''}`}
                                onClick={(e) => { e.stopPropagation(); setFavorite(m.model_id) }}
                              >
                                {m.is_favorite ? '\u2605' : '\u2606'}
                              </button>
                              <div className="dd-item-info" onClick={() => { setFavorite(m.model_id); setShowSearch(false); setSearchQuery('') }}>
                                <span className="dd-item-name">{m.name}</span>
                                <span className="dd-item-id">{m.model_id}</span>
                              </div>
                              <button
                                className="dd-remove"
                                onClick={(e) => { e.stopPropagation(); removeModel(m.model_id) }}
                              >
                                &times;
                              </button>
                            </div>
                          ))}
                        </>
                      )}

                      {!searching && searchResults.length === 0 && (
                        <div className="dd-status">
                          <button
                            className="dd-add-custom"
                            onClick={() => addModel(searchQuery.trim(), searchQuery.trim())}
                          >
                            + Prideti &bdquo;{searchQuery.trim()}&ldquo;
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="settings-card">
        <div className="card-header">
          <h2 className="card-title">Whisper transkribavimas</h2>
          <p className="card-desc">Kalbos atpazinimo modelio nustatymai</p>
        </div>

        <div className="card-body">
          <div className="settings-grid">
            <div className="settings-field">
              <label className="field-label">Modelio dydis</label>
              <Dropdown
                value={whisperModel}
                onChange={setWhisperModel}
                options={[
                  { value: 'tiny', label: 'Tiny', description: 'Greiciausias, maziausias tikslumas' },
                  { value: 'base', label: 'Base', description: 'Greitas, vidutinis tikslumas' },
                  { value: 'small', label: 'Small', description: 'Rekomenduojamas' },
                  { value: 'medium', label: 'Medium', description: 'Letesnis, tikslesnis' },
                  { value: 'large-v3', label: 'Large v3', description: 'Leciausias, tiksliausias' },
                ]}
              />
            </div>

            <div className="settings-field">
              <label className="field-label">Numatytoji kalba</label>
              <Dropdown
                value={language}
                onChange={setLanguage}
                placeholder="Automatinis aptikimas"
                options={[
                  { value: '', label: 'Automatinis aptikimas', description: 'Whisper nustato pats' },
                  { value: 'lt', label: 'Lietuviu' },
                  { value: 'en', label: 'English' },
                  { value: 'de', label: 'Deutsch' },
                  { value: 'fr', label: 'Francais' },
                  { value: 'es', label: 'Espanol' },
                  { value: 'ru', label: 'Russkij' },
                  { value: 'pl', label: 'Polski' },
                  { value: 'uk', label: 'Ukrainska' },
                  { value: 'ja', label: '\u65E5\u672C\u8A9E' },
                  { value: 'zh', label: '\u4E2D\u6587' },
                  { value: 'ko', label: '\uD55C\uAD6D\uC5B4' },
                ]}
              />
            </div>
          </div>
        </div>
      </div>
      </div>

      <div className="settings-footer">
        {error && <div className="alert-error">{error}</div>}
        {saved && <div className="alert-success">Issaugota!</div>}
        <button className="btn-save" onClick={handleSave}>Išsaugoti nustatymus</button>
      </div>
    </div>
  )
}

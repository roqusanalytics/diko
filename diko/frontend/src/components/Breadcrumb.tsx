import { useLocation, Link } from 'react-router-dom'
import './Breadcrumb.css'

const ROUTE_NAMES: Record<string, string> = {
  '/': 'Naujas',
  '/library': 'Biblioteka',
  '/settings': 'Nustatymai',
}

interface BreadcrumbProps {
  videoTitle?: string
}

export default function Breadcrumb({ videoTitle }: BreadcrumbProps) {
  const { pathname } = useLocation()
  const pageName = ROUTE_NAMES[pathname] || 'Naujas'

  return (
    <nav className="breadcrumb" aria-label="Breadcrumb">
      <Link to="/" className="breadcrumb-root">Diko</Link>
      <span className="breadcrumb-sep">/</span>
      <span className="breadcrumb-current">{pageName}</span>
      {videoTitle && pathname === '/' && (
        <>
          <span className="breadcrumb-sep">/</span>
          <span className="breadcrumb-video" title={videoTitle}>
            {videoTitle.length > 40 ? videoTitle.slice(0, 40) + '...' : videoTitle}
          </span>
        </>
      )}
    </nav>
  )
}

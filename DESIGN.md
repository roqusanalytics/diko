# Design System — Diko

## Product Context
- **What this is:** Self-hosted YouTube video transcription app with AI summaries and full-text search
- **Who it's for:** Lithuanian builder and their friends/family
- **Space/industry:** Productivity / transcription tools (Otter.ai, Descript, Flow by Wispr)
- **Project type:** Web app (Vite + React SPA + FastAPI backend)

## Aesthetic Direction
- **Direction:** Midnight Rose
- **Decoration level:** Intentional (subtle film grain texture on dark bg at 2-3% opacity, soft rose glow on card edges, no gradients/blobs)
- **Mood:** A book read by candlelight. Deep violet-dark backgrounds with warm rose-white card surfaces. Elegantly unusual, intimately premium. Like a velvet notebook in a dimly lit parlor.
- **Reference:** Linear (dark premium), Arc Browser (violet tones), Superhuman (dark-to-light contrast)
- **Max shadow:** `0 2px 8px rgba(0,0,0,0.15), 0 0 0 1px rgba(240,230,239,0.04)` — cards get presence through glow, not heavy drop shadows
- **Card glow:** `0 0 40px rgba(201,120,142,0.06)` — subtle rose glow around card edges

## Typography
- **Display/Hero:** Fraunces 400 — variable optical-size serif. Warm, literary, unique. Nobody in the transcription space uses a serif. Says "this is a tool with taste, not a corporate SaaS." Lithuanian: ą, č, ę, ė, į, š, ų, ū, ž supported.
- **Body:** Plus Jakarta Sans 300-400 — geometric but softer than Inter. More refined, slightly more personality. Excellent Lithuanian character support.
- **UI/Labels:** Plus Jakarta Sans 500-600 — medium-bold weight for buttons, nav, section headers
- **Data/Timestamps:** JetBrains Mono 400 with `font-variant-numeric: tabular-nums` — aligned columns, more polished than IBM Plex Mono
- **Code/URLs:** JetBrains Mono 300-400 — deliberate technical contrast
- **Section labels:** Plus Jakarta Sans 600, 11px, uppercase, letter-spacing 1.5px, color: var(--accent)
- **Loading:** Google Fonts CDN: `Fraunces:ital,opsz,wght@0,9..144,300;0,9..144,400;0,9..144,500;0,9..144,600;0,9..144,700;1,9..144,400` + `Plus+Jakarta+Sans:wght@300;400;500;600;700` + `JetBrains+Mono:wght@300;400;500`
- **Scale:**
  - Display: 28px Fraunces 400 (page titles)
  - Title: 20px Fraunces 400 (section headers)
  - Body large: 15px Plus Jakarta Sans 400 (summary text, main content)
  - Body: 14px Plus Jakarta Sans 400 (default)
  - Body small: 13px Plus Jakarta Sans 300 (transcript lines, secondary content)
  - UI: 13px Plus Jakarta Sans 500 (buttons, nav items)
  - Caption: 12px JetBrains Mono 400 (timestamps, metadata)
  - Micro: 11px Plus Jakarta Sans 600 uppercase (section labels, badges)
  - Nano: 10px Plus Jakarta Sans 600 uppercase (tiny badges, language tags)

## Color
- **Approach:** Restrained — dusty rose accent on deep violet-dark foundation, rose-white cards, warm bronze for AI content

### Core Palette
| Token | Hex | Usage |
|-------|-----|-------|
| `--bg` | `#1a1020` | Page background (deep violet-black) |
| `--bg-sidebar` | `#221728` | Sidebar surface (slightly lighter violet) |
| `--bg-card` | `#f7f2f5` | Card surfaces, main content area (warm rose-white) |
| `--bg-card-hover` | `#ede6eb` | Hover states on card surfaces |
| `--bg-hover` | `#2d2035` | Hover states on dark surfaces |
| `--bg-active` | `#382840` | Active/pressed states on dark surfaces |
| `--border` | `#d5c8d2` | Borders on light card surfaces |
| `--border-subtle` | `#e0d6dc` | Dividers, separators on light surfaces |
| `--border-dark` | `#382840` | Borders on dark surfaces |
| `--text` | `#1a1020` | Primary text on light surfaces |
| `--text-light` | `#f0e6ef` | Primary text on dark surfaces |
| `--text-secondary` | `#7a6875` | Secondary text, descriptions |
| `--text-muted` | `#9e8a96` | Placeholder text, metadata on light |
| `--text-muted-dark` | `#6b5565` | Muted text on dark surfaces |
| `--accent` | `#c9788e` | Interactive elements, timestamps, focus rings, primary buttons (dusty rose) |
| `--accent-hover` | `#d4899a` | Hover state for accent |
| `--accent-dark` | `#a85f75` | Darker accent for text on accent-light backgrounds |
| `--accent-light` | `#f8eff2` | Focus ring glow, accent backgrounds on light surfaces |
| `--warm` | `#8b6e4e` | AI summary labels, bronze highlights |
| `--warm-light` | `#f9f3ec` | AI summary card background |
| `--warm-border` | `#e5d5c2` | AI summary card border |

### Semantic Colors
| Token | Hex | Light bg | Usage |
|-------|-----|----------|-------|
| `--success` / `--green` | `#5e8a6e` | `#eaf5ee` | Save confirmations, Lithuanian language badge |
| `--error` | `#c44d5a` | `#fde8ea` | Validation errors, failed downloads |
| `--warning` | `#b88a3e` | `#fef3cd` | Long video warnings |
| `--info` | `#7a8eb5` | `#edf1fa` | System messages, English language badge |

### Dark Mode
- The default theme IS dark. The violet-dark background is the foundation.
- A future "light mode" toggle could swap dark surfaces for a light lavender/rose approach.

## Spacing
- **Base unit:** 4px
- **Density:** Comfortable
- **Scale:**

| Token | Value | Usage |
|-------|-------|-------|
| `--space-2xs` | 2px | Tight gaps, badge padding |
| `--space-xs` | 4px | Icon gaps, inline spacing |
| `--space-sm` | 8px | Card internal gaps, list item padding |
| `--space-md` | 16px | Section gaps, card padding |
| `--space-lg` | 24px | Major section spacing |
| `--space-xl` | 32px | Page-level padding |
| `--space-2xl` | 48px | Hero spacing, section dividers |

## Layout
- **Approach:** Grid-disciplined
- **Structure:** Sidebar (220px, dark bg-sidebar with light text) + Main content card (flex: 1, warm ivory, border-radius 14px)
- **Result layout:** Two columns inside main card — video (380px) left, transcript (flex: 1) right
- **Max content width:** No max — fills available space
- **Card margins:** 12px from edges, 0 from sidebar
- **Responsive breakpoints:**
  - Mobile (375px): sidebar hidden (hamburger), single column, video full-width
  - Tablet (768px): sidebar collapsed to icons (64px), single column results
  - Desktop (1024px+): full sidebar (220px), two-column results

### Border Radius
| Token | Value | Usage |
|-------|-------|-------|
| `--radius-sm` | 4px | Badges, small elements, language tags |
| `--radius-md` | 8px | Inputs, buttons |
| `--radius-inner` | 7px | Inner containers, transcript panel, alerts |
| `--radius-lg` | 14px | Main content card, section cards |

## Motion
- **Approach:** Minimal-functional — transitions that aid comprehension, warm glow fade on card mount
- **Easing:** `ease` for hover, `ease-out` for enter/appear, `ease-in` for exit
- **Durations:**

| Token | Value | Usage |
|-------|-------|-------|
| micro | 100ms | Hover color changes |
| short | 150ms | Button press, nav active state, page transitions |
| medium | 200ms | State changes, card appear with glow, toast enter |
| long | 300ms | Modal open, hero-to-results transition |

## Component Patterns

### Buttons
- **Primary:** `background: var(--accent); color: var(--bg);` — amber/gold, the main action
- **Dark:** `background: var(--text); color: var(--bg-card);` — secondary emphasis
- **Secondary:** `background: var(--bg-card); border: 1px solid var(--border);` — outlined
- **Ghost:** `background: transparent; color: var(--accent);` — text-only with amber hover bg
- **Toolbar:** `border: 1px solid var(--border); border-radius: 6px; font-size: 12px;` — compact
- **Danger:** `background: var(--error-light); color: var(--error); border: 1px solid rgba(196,77,77,0.2);`

### Cards
- **Main content:** `var(--bg-card)`, `var(--radius-lg)`, `var(--shadow-card)`, `var(--shadow-glow)`, margin 12px from edges
- **Standard:** `var(--bg-card)`, `var(--border)`, `var(--radius-inner)`, `var(--space-md)` padding
- **AI Summary:** `var(--warm-light)` background, `var(--warm-border)`, uppercase label in `var(--warm)`, 10px font-weight 700

### Sidebar
- **Background:** `var(--bg-sidebar)` — dark charcoal
- **Logo icon:** `var(--accent)` background, `var(--bg)` text, `var(--radius-sm)`, 24x24px
- **Nav items:** `var(--text-muted-dark)` default, `var(--text-light)` on hover/active
- **Active nav:** `var(--bg-active)` background, `var(--text-light)`, font-weight 500
- **Section labels:** 10px uppercase, `var(--text-muted-dark)`, letter-spacing 0.5px
- **Recent items:** 12px, `var(--text-muted-dark)`, dot indicators (green for LT, blue for EN)
- **Footer:** 11px, `var(--text-muted-dark)`

### Alerts/Toasts
- Positioned bottom-right
- Auto-dismiss after 3 seconds
- Rounded `var(--radius-inner)`, 1px border, light semantic background
- Lithuanian text

### Empty States
- Centered in container
- Warm, inviting text (not "No items found")
- Primary action button (amber)
- Example: "Dar nera transkripciju. Pradekite pirma!" with a Transkribuoti button

### Film Grain Texture
```css
background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.03'/%3E%3C/svg%3E");
background-size: 256px 256px;
```
Applied to body, creates subtle noise texture on dark background. 3% opacity, barely visible but adds materiality.

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-04-02 | Warm Minimal aesthetic (v1) | 8 wireframe iterations converged on Flow-app inspired warm linen look |
| 2026-04-02 | Inter as primary font (v1) | Lithuanian character support, tabular nums for timestamps |
| 2026-04-03 | **Refined Dark Warm redesign (v2)** | User wanted premium, aesthetic, unique. Research showed dark foundations = premium (Linear, Superhuman, Descript) |
| 2026-04-03 | Dark background (#141210) | Warm black with brown undertone. Not cold IDE dark, but artisan study dark |
| 2026-04-03 | Amber/gold accent (#c49a3f) | Every transcription app uses blue. Amber is Diko's face. Premium, warm, unique |
| 2026-04-03 | Fraunces serif for display | Risk: serifs unusual for web apps. Reward: literary, warm, cultured. Says "tool with taste" |
| 2026-04-03 | Plus Jakarta Sans for body | Geometric but softer than Inter. More personality. Full Lithuanian support |
| 2026-04-03 | JetBrains Mono for code/URLs | More polished than IBM Plex Mono, better rendering |
| 2026-04-03 | Warm ivory cards (#faf7f3) | Not pure white. Warm ivory harmonizes with dark background and amber accent |
| 2026-04-03 | Film grain texture on dark bg | 3% opacity SVG noise. Adds materiality without decoration |
| 2026-04-03 | Card glow effect | Subtle 40px amber glow (6% opacity) gives cards presence on dark background |
| 2026-04-06 | **Midnight Rose redesign (v3)** | User wanted fresh palette. Chose dusty rose over ocean teal and forest green |
| 2026-04-06 | Violet-dark background (#1a1020) | Deep violet-black. Not cold, not warm brown, distinctly moody and elegant |
| 2026-04-06 | Dusty rose accent (#c9788e) | No transcription app uses rose. Unique, elegant, memorable |
| 2026-04-06 | Bronze secondary (#8b6e4e) | Warm contrast to cool rose. Used for AI content highlights |
| 2026-04-06 | Rose-white cards (#f7f2f5) | Subtle pink warmth in the white, harmonizes with rose accent |
| 2026-04-06 | Rose card glow | Subtle 40px rose glow (6% opacity) replaces amber glow |

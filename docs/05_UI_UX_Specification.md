# 05 UI/UX Specification
## Sovereign AI Workbench

**Version:** 1.0
**Status:** Draft
**Classification:** Internal - SIH 2026 Prototype
**Depends on:** 01_PRD.md v1.0, 04_App_User_Flow.md v1.0

---

## 1. Purpose

This document specifies the visual design system, layout structure, component library, interaction patterns, accessibility requirements, and responsive behavior for the Sovereign AI Workbench frontend. It is the primary reference for frontend developers implementing the React/Tailwind UI.

---

## 2. Design Principles

| Principle | Application |
|-----------|-------------|
| **Clarity first** | Information density balanced with whitespace; no decorative elements that reduce comprehension |
| **Privacy-visible** | The UI always makes it clear that processing is local and data stays on-premise |
| **Control-forward** | Risky or irreversible actions require explicit confirmation; defaults are always safe |
| **Functional density** | Dense information displays (tables, logs) preferred over empty UX in a workbench context |
| **Consistent feedback** | Every action has a visible response: loading states, success confirmation, error messaging |
| **Accessibility-first** | WCAG 2.1 AA compliance throughout; not an afterthought |

---

## 3. Visual Design System

### 3.1 Color Palette

**Primary brand colors:**

| Token | Hex | Usage |
|-------|-----|-------|
| `primary-600` | `#2563EB` | Primary buttons, active nav items, links |
| `primary-700` | `#1D4ED8` | Hover state for primary buttons |
| `primary-100` | `#DBEAFE` | Light backgrounds, selected state chips |
| `primary-50` | `#EFF6FF` | Subtle tint backgrounds |

**Semantic colors:**

| Token | Hex (light) | Usage |
|-------|-------------|-------|
| `success-500` | `#22C55E` | Success states, healthy indicators |
| `success-100` | `#DCFCE7` | Success backgrounds |
| `warning-500` | `#F59E0B` | Warning states, medium risk |
| `warning-100` | `#FEF3C7` | Warning backgrounds |
| `danger-600` | `#DC2626` | Error states, high risk, destructive actions |
| `danger-100` | `#FEE2E2` | Error/danger backgrounds |
| `critical-700` | `#7F1D1D` | Critical risk level label |
| `info-500` | `#3B82F6` | Informational states |

**Neutral palette:**

| Token | Hex (light) | Dark mode |
|-------|-------------|-----------|
| `neutral-50` | `#F9FAFB` | Page background (light) |
| `neutral-100` | `#F3F4F6` | Panel/card backgrounds |
| `neutral-200` | `#E5E7EB` | Dividers, borders |
| `neutral-400` | `#9CA3AF` | Placeholder text, secondary labels |
| `neutral-600` | `#4B5563` | Secondary body text |
| `neutral-800` | `#1F2937` | Primary body text |
| `neutral-900` | `#111827` | Headings, high-emphasis text |

**Dark mode equivalents:** Tailwind `dark:` variants used. Dark mode activated by class on `<html>` element, stored in `localStorage` and Zustand UIStore.

### 3.2 Typography

**Font stack:** System font stack (no external font CDN dependency — privacy principle):
```css
font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
             "Helvetica Neue", Arial, sans-serif;
font-family-mono: "JetBrains Mono", "Fira Code", Consolas, "Courier New", monospace;
```

**Type scale (Tailwind defaults):**

| Role | Class | Size | Weight |
|------|-------|------|--------|
| Page title | `text-2xl font-bold` | 24px | 700 |
| Section heading | `text-lg font-semibold` | 18px | 600 |
| Card title | `text-base font-medium` | 16px | 500 |
| Body | `text-sm` | 14px | 400 |
| Label / meta | `text-xs text-neutral-500` | 12px | 400 |
| Code / mono | `font-mono text-sm` | 14px | 400 |

### 3.3 Spacing

Tailwind's 4px grid used consistently:
- Component padding: `p-4` (16px)
- Card padding: `p-6` (24px)
- Stack spacing (between sibling components): `space-y-4` (16px)
- Inline spacing: `gap-2` (8px)

### 3.4 Border Radius

| Context | Class |
|---------|-------|
| Cards, panels | `rounded-lg` (8px) |
| Buttons | `rounded-md` (6px) |
| Inputs | `rounded-md` (6px) |
| Badges, pills | `rounded-full` |
| Code blocks | `rounded` (4px) |

### 3.5 Shadows

| Context | Class |
|---------|-------|
| Cards (resting) | `shadow-sm` |
| Modals | `shadow-xl` |
| Dropdowns | `shadow-lg` |
| Hover on interactive cards | `shadow-md` |

### 3.6 Risk Level Color Coding

Risk levels appear throughout the UI (tools, approvals, audit). Consistent color treatment:

| Risk Level | Badge classes |
|-----------|---------------|
| Low | `bg-green-100 text-green-700` |
| Medium | `bg-yellow-100 text-yellow-700` |
| High | `bg-orange-100 text-orange-700` |
| Critical | `bg-red-100 text-red-700 font-semibold` |

---

## 4. Layout Structure

### 4.1 Application Shell

```
┌──────────────────────────────────────────────────────────────┐
│  TOP BAR (h-14, sticky, z-50)                                │
│  [≡ logo/name] [---spacer---] [status pill] [model] [avatar] │
├──────────┬───────────────────────────────────────────────────┤
│          │                                                    │
│ SIDEBAR  │   MAIN CONTENT AREA                               │
│ (w-56)   │   (flex-1, overflow-y-auto, p-6)                  │
│          │                                                    │
│ [nav     │   Page-specific content renders here              │
│  items]  │                                                    │
│          │                                                    │
│ [bottom  │                                                    │
│  items]  │                                                    │
│          │                                                    │
└──────────┴───────────────────────────────────────────────────┘
```

**Top bar:**
- Fixed height: `h-14` (56px)
- Background: `bg-white dark:bg-neutral-900 border-b border-neutral-200`
- Contains: sidebar toggle (mobile), logo + "Sovereign AI Workbench" text, status pill, current model badge, user menu

**Sidebar:**
- Width: `w-56` (224px) on desktop
- Background: `bg-neutral-900 dark:bg-neutral-950` (always dark, regardless of mode)
- Text: `text-neutral-200`
- Active item: `bg-primary-700 text-white rounded-md`
- Hover: `hover:bg-neutral-700`
- Collapsible to `w-14` icon-only on mobile

**Main content:**
- `flex-1 overflow-y-auto bg-neutral-50 dark:bg-neutral-900 p-6`
- Max width: `max-w-7xl mx-auto` (prevents ultra-wide stretching)

### 4.2 Page Layout Patterns

**Standard page:**
```
PageHeader (title + breadcrumb + action button)
    ↓
Content area (cards / tables / forms)
```

**Split panel (Chat, Agent run):**
```
Left panel (conversations list / agent list) │ Right panel (active item)
```

**Full-width (Dashboard):**
```
Grid of metric cards
Activity feed (full width)
```

---

## 5. Component Library

### 5.1 Buttons

Four variants, all share base: `inline-flex items-center justify-center font-medium rounded-md transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2`

| Variant | Classes | Use case |
|---------|---------|----------|
| Primary | `bg-primary-600 text-white hover:bg-primary-700 focus:ring-primary-500` | Main CTA |
| Secondary | `bg-white text-neutral-700 border border-neutral-300 hover:bg-neutral-50` | Secondary action |
| Danger | `bg-danger-600 text-white hover:bg-danger-700 focus:ring-danger-500` | Destructive |
| Ghost | `text-neutral-600 hover:bg-neutral-100` | Tertiary / icon buttons |

Sizes: `text-sm px-3 py-1.5` (sm), `text-sm px-4 py-2` (default), `text-base px-6 py-3` (lg)

Disabled state: `opacity-50 cursor-not-allowed`

Loading state: spinner icon replaces leading icon; `pointer-events-none`

### 5.2 Input Fields

```
Base: w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm
      shadow-sm placeholder-neutral-400
      focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500
      dark:bg-neutral-800 dark:border-neutral-600 dark:text-neutral-100

Error state: border-danger-500 focus:ring-danger-500
             + error message below: text-xs text-danger-600 mt-1
```

Label: `block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1`

Required indicator: `text-danger-500 ml-1` asterisk

### 5.3 Cards

```
Standard card:
  bg-white dark:bg-neutral-800 rounded-lg shadow-sm border border-neutral-200 dark:border-neutral-700 p-6

Interactive card (hover effect):
  + hover:shadow-md hover:border-primary-300 transition-all cursor-pointer

Danger/warning card:
  bg-danger-50 border-danger-200  or  bg-warning-50 border-warning-200
```

### 5.4 Badges and Chips

```
Base: inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium

Status: ● Online  → bg-success-100 text-success-700
        ● Offline → bg-danger-100 text-danger-700
        ● Unknown → bg-neutral-100 text-neutral-600

Role:   Admin   → bg-purple-100 text-purple-700
        Analyst → bg-blue-100 text-blue-700
        Viewer  → bg-neutral-100 text-neutral-600

Status (process): pending → bg-neutral-100  processing → bg-blue-100 (animated)
                  indexed → bg-success-100  failed → bg-danger-100
```

### 5.5 Tables

```
Wrapper: overflow-x-auto (for responsive scroll)
Table: w-full text-sm text-left text-neutral-700

<thead>: bg-neutral-50 dark:bg-neutral-700
<th>: px-4 py-3 font-medium text-neutral-500 uppercase tracking-wider text-xs

<tbody>: divide-y divide-neutral-200 dark:divide-neutral-700
<tr>: hover:bg-neutral-50 dark:hover:bg-neutral-700/50 transition-colors
<td>: px-4 py-3
```

Sortable columns: sort icon (`↑↓` / `↑` / `↓`), click to sort.

Pagination: `Showing 1–50 of 4,521` | `← Prev` `Next →`

### 5.6 Modals

```
Overlay: fixed inset-0 bg-black/50 z-40 flex items-center justify-center

Modal box: relative bg-white dark:bg-neutral-800 rounded-lg shadow-xl
           w-full max-w-lg mx-4 z-50

Header: flex items-center justify-between p-6 border-b border-neutral-200
        h2: text-lg font-semibold
        [X] close button

Body: p-6

Footer: flex justify-end gap-3 p-6 border-t border-neutral-200
        [Cancel] [Action] buttons
```

Confirmation modals for destructive actions always show:
1. Clear description of what will happen
2. "This cannot be undone" if irreversible
3. Danger button for confirm action

### 5.7 Toast Notifications

```
Position: top-right, fixed, z-50, stack vertically
Width: min-w-72 max-w-sm

Variants:
  Success: bg-success-50 border-l-4 border-success-500 text-success-800
  Error:   bg-danger-50  border-l-4 border-danger-500  text-danger-800
  Warning: bg-warning-50 border-l-4 border-warning-500 text-warning-800
  Info:    bg-blue-50    border-l-4 border-blue-500    text-blue-800

Auto-dismiss: 5 seconds (error: 8 seconds, no auto-dismiss for critical)
```

### 5.8 Progress Indicators

**Spinner:** `animate-spin h-4 w-4 border-2 border-current border-t-transparent rounded-full`

**Progress bar (document processing):**
```
Steps bar (linear):
  ○ Received → ○ Extracting → ○ OCR → ○ Chunking → ○ Embedding → ○ Indexed
  
Each step: circle icon, label below
Current step: pulsing blue animation
Completed: green check
Failed: red X
```

**Linear progress bar (model pull):**
```
<div role="progressbar" aria-valuenow=65 aria-valuemin=0 aria-valuemax=100>
  bg-neutral-200 rounded-full h-2
    └── bg-primary-600 h-2 rounded-full transition-all (width=percentage%)
</div>
```

### 5.9 Code Blocks

```
bg-neutral-900 dark:bg-neutral-950 rounded text-neutral-100 font-mono text-sm p-4 overflow-x-auto

Line numbers: text-neutral-500 select-none mr-4 (optional)
[Copy] button: top-right corner, ghost style
```

### 5.10 System Status Pill (Top Bar)

```
Healthy:  ● System Healthy   → bg-success-100 text-success-700 border border-success-200
Degraded: ● System Degraded  → bg-warning-100 text-warning-700 border border-warning-200
Unhealthy:● System Unhealthy → bg-danger-100  text-danger-700  border border-danger-200
```

Clicking opens a dropdown with individual service statuses (Ollama, Qdrant, Database).

---

## 6. Page-Specific UI Specifications

### 6.1 Dashboard Page

**Layout:** 12-column grid

```
Row 1: 4 metric cards (col-span-3 each)
  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
  │  CPU Usage   │ │  RAM Usage   │ │  Disk Free   │ │  Models      │
  │  34%         │ │  5.1/16 GB   │ │  67 GB       │ │  3 loaded    │
  │  [sparkline] │ │  [bar]       │ │  [bar]       │ │  [status]    │
  └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘

Row 2: 3-panel layout
  ┌─────────────────────────┐ ┌──────────────┐ ┌──────────────┐
  │ Activity Feed           │ │ Services     │ │ Quick Actions│
  │ (col-span-6)            │ │ (col-span-3) │ │ (col-span-3) │
  │ Recent events list      │ │ Ollama: ●    │ │ [New Chat]   │
  │ with timestamps, icons  │ │ Qdrant:  ●   │ │ [Upload Doc] │
  │                         │ │ DB:      ●   │ │ [New Agent]  │
  └─────────────────────────┘ └──────────────┘ └──────────────┘
```

**Local Processing Banner:**
A persistent blue info banner at top of every AI-related page:
```
🔒 All AI processing is running locally on this device. No data leaves your network.
```

### 6.2 Chat Page

**Layout:** Split panel

```
┌─────────────────┬────────────────────────────────────────────┐
│ Conversations   │  Chat View                                 │
│ (w-72)          │                                            │
│                 │  [Model: llama3.2:3b ▼] [System Prompt ⚙] │
│ [+ New Chat]    │  [KB: None ▼]                              │
│                 │  ──────────────────────────────────────── │
│ ▸ Q3 Analysis   │                                            │
│   Today, 10:32  │  🔒 Processing locally                      │
│                 │                                            │
│ ▸ Policy Review │  [User message bubble - right aligned]     │
│   Yesterday     │  "Summarize the Q3 report"                 │
│                 │                                            │
│ ▸ Sales Data    │  [Assistant message bubble - left aligned] │
│   2 days ago    │  "The Q3 report shows..."                  │
│                 │  Sources: [report.pdf · p.4] [report.pdf · p.7]│
│                 │                                            │
│                 │  ──────────────────────────────────────── │
│                 │  [Message input textarea          ] [Send] │
│                 │  [Attach] [Token count: 234/4096]          │
└─────────────────┴────────────────────────────────────────────┘
```

**Message bubbles:**
- User messages: right-aligned, `bg-primary-600 text-white rounded-2xl rounded-tr-sm px-4 py-2`
- Assistant messages: left-aligned, `bg-white dark:bg-neutral-800 border rounded-2xl rounded-tl-sm px-4 py-3`
- Streaming: blinking cursor at end of current token stream
- Citations: small tag chips below the assistant message

**"Processing locally" indicator:**
Small badge shown during streaming: `🔒 Local · llama3.2:3b`

### 6.3 Document Upload Modal

Already specified in Flow 7.1. Visual details:

```
Drag-and-drop zone:
  border-2 border-dashed border-neutral-300 rounded-lg p-8 text-center
  hover: border-primary-400 bg-primary-50
  active/dragover: border-primary-500 bg-primary-100

File accepted (preview):
  bg-neutral-50 border rounded p-3 flex items-center gap-3
  [file type icon] [filename] [size] [× remove]

OCR toggle:
  Switch component (Tailwind toggle pattern)
  Label: "Run OCR (for scanned documents and images)"
```

### 6.4 Knowledge Base Query View

```
┌──────────────────────────────────────────────────────────────┐
│ Knowledge Base: "Policy Documents"  [47 docs · 12,431 chunks]│
│ ──────────────────────────────────────────────────────────── │
│ Query                                                        │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ Ask a question about your documents...                   │ │
│ └──────────────────────────────────────────────────────────┘ │
│  [Ask]  [Advanced options ▼]                                 │
│                                                              │
│ ──────────────────────────────────────────────────────────── │
│ ANSWER                                                       │
│ "According to the procurement policy..."                     │
│                                                              │
│ SOURCES (3)                                    [Score ≥ 0.87]│
│ ┌────────────────────────────────────────────────────────┐   │
│ │ 📄 procurement_policy.pdf · Page 12                    │   │
│ │ Relevance: ████████░░ 0.91                             │   │
│ │ "...contracts exceeding ten lakh rupees must be..."    │   │
│ │ [View full document]                                   │   │
│ └────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

### 6.5 Agent Run View

```
┌──────────────────────────────────────────────────────────────┐
│ Agent Run #A-047                        [● Running] [Cancel] │
│ Goal: "Analyze Q3 sales and find top 5 products"             │
│ Model: llama3.2:3b  │  Iteration: 3/10  │  Duration: 0:24   │
│ ──────────────────────────────────────────────────────────── │
│                                                              │
│ EXECUTION TRACE                                              │
│                                                              │
│  💭 Planning...                                              │
│     "I need to: 1) Read the CSV, 2) Analyze revenue..."     │
│                                                              │
│  ✓ Step 1  file_read  [Low]  · 12ms                         │
│    Input: {"path": "sales_q3.csv"}                          │
│    Output: "200 rows, 8 columns: date, product, revenue..."  │
│                                                              │
│  ✓ Step 2  python_exec  [High · Sandboxed]  · 1,203ms       │
│    Input: {"code": "import pandas as pd..."}                │
│    Output: "top_5 = [Widget A: 420000, Widget B: 380000...]"│
│                                                              │
│  ↻ Step 3  Reasoning...                                     │
│    (animated spinner)                                        │
│                                                              │
│ ──────────────────────────────────────────────────────────── │
│ [Result will appear here when complete]                      │
└──────────────────────────────────────────────────────────────┘
```

**Step row color coding:**
- Pending: `text-neutral-400`
- Running: `text-blue-600 animate-pulse`
- Success: `text-success-600`
- Failed: `text-danger-600`
- Awaiting approval: `text-warning-600` with badge

**Sandboxed indicator:** small `[Sandboxed]` badge in `bg-neutral-100 text-neutral-600 font-mono text-xs`

### 6.6 Approval Request Detail View

```
┌──────────────────────────────────────────────────────────────┐
│ ⚠️  APPROVAL REQUIRED                          [HIGH RISK]   │
│ ──────────────────────────────────────────────────────────── │
│                                                              │
│ Requested by: sonam (analyst)        Expires in: 4m 32s     │
│                                                              │
│ OPERATION                                                    │
│  Tool:      file_delete                                      │
│  File path: /workspace/old_report.pdf                        │
│  Reason:    "Cleaning up temporary files after analysis"     │
│                                                              │
│ AGENT CONTEXT                                                │
│  Run #A-047 · "Analyze Q3 sales..."                         │
│  Step 4 of estimated 5                                       │
│                                                              │
│ RISK ASSESSMENT                                              │
│  ● This operation is IRREVERSIBLE                            │
│  ● File will be permanently deleted                          │
│  ● No external network access required                       │
│                                                              │
│ DECISION NOTE (required for rejection)                       │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ Add a note...                                            │ │
│ └──────────────────────────────────────────────────────────┘ │
│                                                              │
│                        [Reject]  [Approve]                   │
└──────────────────────────────────────────────────────────────┘
```

---

## 7. Interaction Patterns

### 7.1 Loading States

Every data-fetching operation shows one of:
- **Skeleton loader:** for tables and card grids — `animate-pulse bg-neutral-200` placeholders matching the shape of real content
- **Spinner:** for inline operations (button loading, inline status)
- **Progress bar:** for operations with known completion (model pull, document upload)

Rule: never show a blank page. Always show skeleton or spinner.

### 7.2 Empty States

When a list or table is empty, show a centered empty state:
```
[Relevant icon (large, muted)]
[Primary message: "No conversations yet"]
[Secondary message: "Start a new chat to begin."]
[Action button: "+ New Chat"]
```

### 7.3 Confirmation Dialogs

Destructive actions always require an explicit modal confirmation. The confirm button is always a Danger button. Pattern:

```
Title: "Delete Knowledge Base"
Body: "Are you sure you want to delete 'Policy Documents'?
       This will permanently delete 47 documents and 12,431 indexed chunks.
       This action cannot be undone."
Buttons: [Cancel]  [Delete Knowledge Base]  ← Danger button
```

The confirm button does NOT use the same label as the generic "Confirm" — it uses a specific action verb ("Delete Knowledge Base", "Approve Request", "Cancel Agent Run").

### 7.4 Streaming Text Display

During LLM streaming:
- Text appends character-by-character (or token-by-token)
- Blinking cursor at insertion point: `▋ animate-pulse`
- "Stop generating" button visible while streaming
- Token counter updates live in footer

### 7.5 Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+Enter` | Send chat message |
| `Ctrl+/` | Open new chat |
| `Esc` | Close modal |
| `↑` in chat input | Load previous message |
| `Ctrl+Shift+A` | Quick-open agent panel |

All shortcuts are shown in tooltips and documented in Settings → Keyboard Shortcuts.

### 7.6 Copy to Clipboard

Code blocks and AI responses include a `[Copy]` button.
- Success feedback: button text changes to `✓ Copied` for 2 seconds
- Uses `navigator.clipboard.writeText()`

---

## 8. Accessibility Requirements

### 8.1 WCAG 2.1 AA Compliance

| Criterion | Implementation |
|-----------|---------------|
| 1.1.1 Non-text Content | All icons have `aria-label` or companion visible text; decorative icons have `aria-hidden="true"` |
| 1.3.1 Info and Relationships | Semantic HTML: `<nav>`, `<main>`, `<section>`, `<header>`, `<table>` with `<caption>` |
| 1.4.1 Use of Color | Status indicated by both color AND text/icon (never color alone) |
| 1.4.3 Contrast | Minimum 4.5:1 ratio for normal text; 3:1 for large text |
| 1.4.11 Non-text Contrast | 3:1 for UI components (borders, icons) |
| 2.1.1 Keyboard | All functionality reachable via keyboard; no keyboard traps |
| 2.1.2 No Keyboard Trap | Focus never trapped in modal (Esc closes); Tab cycles within modal |
| 2.4.3 Focus Order | Logical DOM order; no visual-only reordering |
| 2.4.7 Focus Visible | `focus:ring-2 focus:ring-primary-500 focus:ring-offset-2` on all interactive elements |
| 3.2.2 On Input | No unexpected context changes on input; explicit submit required |
| 3.3.1 Error Identification | Field-level error messages linked to inputs via `aria-describedby` |
| 4.1.2 Name, Role, Value | All custom components use ARIA roles, states, properties |

**Note:** Full WCAG 2.1 AA validation requires manual testing with assistive technologies (NVDA, VoiceOver) and expert accessibility review. The specification above sets implementation targets; actual compliance must be verified through testing.

### 8.2 Focus Management in Modals

When a modal opens:
1. Focus moves to the modal's first focusable element (or close button)
2. Tab key cycles only within the modal (focus trap)
3. `Esc` closes modal and returns focus to the triggering element
4. Modal has `role="dialog"`, `aria-modal="true"`, `aria-labelledby` pointing to modal title

### 8.3 Screen Reader Announcements

Live regions for dynamic content:
```html
<!-- Status announcements -->
<div aria-live="polite" aria-atomic="true" class="sr-only" id="status-announcement" />

<!-- Urgent alerts (errors) -->
<div aria-live="assertive" aria-atomic="true" class="sr-only" id="alert-announcement" />
```

When:
- Chat message streaming completes → announce "AI response received"
- Document indexed → announce "Document processed successfully"
- Approval required → announce "Approval required for agent action" (assertive)

### 8.4 Reduced Motion

```css
@media (prefers-reduced-motion: reduce) {
  .animate-pulse, .animate-spin, .transition-all { animation: none !important; }
}
```

---

## 9. Responsive Design

### 9.1 Breakpoints (Tailwind defaults)

| Breakpoint | Width | Layout behavior |
|-----------|-------|----------------|
| `sm` | 640px | Mobile (phone landscape) |
| `md` | 768px | Tablet (iPad portrait) |
| `lg` | 1024px | Small laptop |
| `xl` | 1280px | Desktop (target primary) |
| `2xl` | 1536px | Large display |

### 9.2 Layout Adaptations

| Element | Desktop (xl) | Tablet (md) | Mobile (sm) |
|---------|-------------|-------------|-------------|
| Sidebar | Fixed w-56, always visible | Fixed w-56, overlay on toggle | Hidden, hamburger menu |
| Dashboard grid | 4-col | 2-col | 1-col |
| Chat split panel | side-by-side | side-by-side | Stack (conversations above) |
| Tables | Full columns | Horizontal scroll | Horizontal scroll |
| Modals | max-w-lg centered | max-w-lg | Full screen |

---

## 10. Dark Mode

Toggle via: top-bar icon (sun/moon). Preference persisted in `localStorage`.

Implementation: Add `dark` class to `<html>` element. All components use Tailwind `dark:` variants.

Dark mode palette highlights:
- Background: `neutral-900` (page), `neutral-800` (cards)
- Text: `neutral-100` (primary), `neutral-400` (secondary)
- Borders: `neutral-700`
- Inputs: `neutral-800` background, `neutral-100` text
- Sidebar: unchanged (already dark)

---

## 11. Privacy and Security UI Affordances

### 11.1 Local Processing Indicator

Present on every page where AI processing occurs:

```
[🔒 icon] Processing locally · No data leaves your network
```

Style: `text-xs text-success-700 bg-success-50 border border-success-200 rounded px-2 py-1 inline-flex items-center gap-1`

This is NOT dismissable. It is always visible on AI pages to reinforce the privacy guarantee.

### 11.2 Risk Level Visibility

- Every tool shown in agent traces includes its risk level badge
- Approval requests prominently display risk level in color
- Settings page shows which tools are enabled/disabled with their risk levels
- No tool name is shown without its associated risk classification

### 11.3 Sensitive Data Handling in UI

- Passwords: `type="password"` inputs; show/hide toggle with `aria-label`
- JWTs/tokens: never displayed in UI; stored only in memory
- Audit log metadata: raw JSON viewer with expand/collapse (not auto-expanded for large payloads)
- File paths in agent traces: shown as-is (within sandbox `/workspace/`; host paths never appear)

---

## 12. Error States and Edge Cases

### 12.1 Form Validation

- Client-side validation on blur and on submit
- Server-side validation errors displayed inline after submit
- Field-level errors: below the input in `text-xs text-danger-600`
- Global form errors: at the top of the form in a danger alert box

### 12.2 API Error Display

| HTTP Status | User-visible message |
|-------------|---------------------|
| 400 | "Invalid request. Please check your input." + field details |
| 401 | "Session expired. Please sign in again." → redirect to login |
| 403 | "You don't have permission to perform this action." |
| 404 | "The requested item was not found." |
| 422 | "Validation error." + specific field messages |
| 429 | "Too many requests. Please wait a moment." |
| 503 | "Service temporarily unavailable." + which service |
| 500 | "An unexpected error occurred. (Ref: {trace_id})" |

Trace IDs are shown for 500 errors to help with log correlation.

---

## 13. Animation and Transition Guidelines

| Element | Animation | Duration |
|---------|-----------|----------|
| Page transitions | `fade` (opacity 0→1) | 150ms |
| Modal open/close | `scale` + `fade` | 200ms |
| Sidebar collapse | `width` transition | 200ms |
| Toast appear | `slide-in-right` | 200ms |
| Dropdown open | `fade` + `scale-y` | 150ms |
| Progress bar | `width` transition | Continuous |
| Streaming cursor | `pulse` | 800ms |

All animations use `ease-out` timing function. All transitions respect `prefers-reduced-motion`.

---

## 14. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-08-23 | Lead Architect | Initial UI/UX Specification |

---

*End of UI/UX Specification*

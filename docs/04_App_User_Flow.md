# 04 Application & User Flow
## Sovereign AI Workbench

**Version:** 1.0
**Status:** Draft
**Classification:** Internal - SIH 2026 Prototype
**Depends on:** 01_PRD.md v1.0, 02_TRD.md v1.0, 03_System_Architecture.md v1.0

---

## 1. Purpose

This document defines the complete user journeys, screen flows, navigation structure, and state transitions for every major workflow in the Sovereign AI Workbench. It is the primary reference for UX design, frontend development, and acceptance testing.

Each flow specifies:
- Entry point (what triggers it)
- Steps (ordered user actions and system responses)
- Decision branches (success path and error/edge paths)
- Exit point (what the user has achieved)

---

## 2. Application Navigation Structure

### 2.1 Global Navigation

All authenticated users see a persistent sidebar navigation:

```
Sidebar
├── 🏠 Dashboard          (all roles)
├── 💬 Chat               (all roles)
├── 📄 Documents          (analyst, admin)
├── 🧠 Knowledge Bases    (analyst, admin)
├── 🤖 Agents             (analyst, admin)
├── ✅ Approvals          (admin only)
├── 📋 Audit Log          (admin only)
└── ⚙️  Settings          (admin only)

Top bar
├── [System Status indicator] — green/yellow/red pill
├── [Active model badge] — shows current chat model
├── [User avatar + role badge]
└── [Logout button]
```

Unauthenticated users are redirected to `/login` from any protected route.

### 2.2 Route → Role Access Matrix

| Route | Viewer | Analyst | Admin |
|-------|--------|---------|-------|
| `/login` | ✓ | ✓ | ✓ |
| `/` (Dashboard) | ✓ | ✓ | ✓ |
| `/chat` | ✓ | ✓ | ✓ |
| `/models` | ✓ | ✓ | ✓ |
| `/documents` | — | ✓ | ✓ |
| `/knowledge-bases` | ✓ (read) | ✓ | ✓ |
| `/agents` | — | ✓ | ✓ |
| `/approvals` | — | — | ✓ |
| `/audit` | — | — | ✓ |
| `/settings` | — | — | ✓ |

---

## 3. Authentication Flows

### 3.1 Flow: User Login

**Entry point:** User navigates to `http://localhost` (unauthenticated, redirected to `/login`)

```
Step 1: Login Page displayed
  └── Fields: Email, Password
      Button: "Sign In"
      Link: "New here? Contact your admin." (no self-signup in MVP except first admin)

Step 2: User enters credentials → clicks "Sign In"
  └── Frontend: POST /api/v1/auth/login

  ── [Success path] ──
  Step 3a: JWT access + refresh tokens received
    → Tokens stored in memory (access) + httpOnly cookie (refresh)
    → Redirect to /dashboard
    → AuditLog: auth.login.success

  ── [Failure: invalid credentials] ──
  Step 3b: 401 response
    → Display: "Invalid email or password"
    → Increment failed attempt counter (shown after 3 attempts)
    → AuditLog: auth.login.failure

  ── [Failure: account locked] ──
  Step 3c: 429 response (rate limited)
    → Display: "Too many attempts. Try again in 15 minutes."
    → AuditLog: auth.login.ratelimited
```

**Exit point:** User lands on Dashboard with active session.

---

### 3.2 Flow: Token Expiry Handling

**Entry point:** API call returns 401 (access token expired)

```
Step 1: API interceptor detects 401
  └── POST /api/v1/auth/refresh (using httpOnly cookie)

  ── [Success path] ──
  Step 2a: New access token received
    → Retry original failed request
    → User sees no interruption

  ── [Failure: refresh expired] ──
  Step 2b: Refresh also returns 401
    → Clear all auth state
    → Redirect to /login with message: "Session expired. Please sign in again."
```

---

### 3.3 Flow: Logout

**Entry point:** User clicks "Logout" in the top bar.

```
Step 1: POST /api/v1/auth/logout
  → Invalidate refresh token server-side
  → Clear tokens from client memory/cookie
  → Redirect to /login
  → AuditLog: auth.logout
```

---

## 4. Dashboard Flow

### 4.1 Flow: View Dashboard

**Entry point:** User lands on `/` after login.

```
Step 1: Dashboard page loads
  └── GET /api/v1/system/status  (system health + resource metrics)
  └── GET /api/v1/models         (list installed models)
  └── GET /api/v1/audit/logs?limit=10  (recent activity, admin only)
  └── GET /api/v1/agents/runs?limit=5  (recent agent runs)

Step 2: Dashboard renders with:
  ├── Service Health Cards
  │     Ollama:  [●] Online  or  [○] Offline
  │     Qdrant:  [●] Online  or  [○] Offline
  │     Backend: [●] Online  (always green if page loads)
  │
  ├── Resource Usage Gauges
  │     CPU: XX%   RAM: X.X/XX GB   Disk: XX GB free
  │
  ├── Model Status Panel
  │     Active chat model: llama3.2:3b
  │     Active embedding model: nomic-embed-text
  │     [Manage Models →]
  │
  ├── Recent Activity Feed (last 10 events)
  │     e.g.: "User sonam uploaded report.pdf · 2 min ago"
  │           "Agent run completed: Analyze sales data · 15 min ago"
  │
  └── Quick Actions
        [+ New Chat]   [Upload Document]   [New Agent Run]

Step 3: Auto-refresh every 30 seconds (non-blocking background poll)
```

---

## 5. Chat Flows

### 5.1 Flow: Start a New Conversation

**Entry point:** User clicks "Chat" in sidebar or "New Chat" button on dashboard.

```
Step 1: Chat page loads
  └── GET /api/v1/conversations (list recent conversations, sidebar)
  └── GET /api/v1/models (populate model selector dropdown)

Step 2: User selects model from dropdown (default: active chat model)
  └── Optional: click gear icon → configure system prompt

Step 3: User types a message → presses Enter or clicks Send
  └── POST /api/v1/chat/conversations (create conversation, first message)
     OR
  └── POST /api/v1/chat/conversations/{id}/messages (existing conversation)

  ── [Success path] ──
  Step 4a: SSE stream opens
    → "Processing locally..." spinner shown
    → Tokens stream in one-by-one into chat bubble
    → Token counter increments live
    → On "done" event: spinner disappears; message saved to history

  ── [RAG-augmented chat] ──
  Step 4b: User had selected a knowledge base
    → System retrieves relevant context (invisible to user by default)
    → "Sources" section appears below the response with clickable citations
    → User can expand citations to see source chunk + document + page

  ── [Model unavailable] ──
  Step 4c: Ollama returns error
    → Stream delivers error event
    → Display: "The AI model is currently unavailable. Please try again."
    → No partial message saved

Step 5: Conversation saved automatically
  → Appears in left sidebar conversation list
  → Title auto-generated from first user message (LLM summarizes in background)
```

---

### 5.2 Flow: Load Previous Conversation

**Entry point:** User clicks a conversation in the sidebar.

```
Step 1: GET /api/v1/chat/conversations/{id}
  → Full message history loaded and rendered
  → Model shown in dropdown (locked to conversation model unless user changes)

Step 2: User continues chatting (appends to existing context)
  → Same as Step 3+ in Flow 5.1
```

---

### 5.3 Flow: Export Conversation

**Entry point:** User clicks "Export" menu on an open conversation.

```
Step 1: User selects format (JSON or Markdown)
  └── GET /api/v1/chat/conversations/{id}/export?format=markdown

Step 2: File downloaded to browser
  → Filename: "conversation_{date}_{model}.md"
  → AuditLog: chat.conversation.exported
```

---

## 6. Model Management Flows

### 6.1 Flow: View and Manage Models

**Entry point:** Admin navigates to `/models`.

```
Step 1: GET /api/v1/models
  → Grid/list of installed models displayed:
     Model name | Family | Size | Quantization | Roles | Status

Step 2: User clicks a model → detail panel opens
  → Parameter count, context window, capabilities
  → [Set as Chat Model] [Set as Embedding Model] [Set as Vision Model]
  → [Run Health Check] button

Step 3: Admin clicks [Pull New Model]
  → Modal opens: text input for model name (e.g. "mistral:7b-q4")
  → POST /api/v1/models/pull
  → Modal switches to progress bar (SSE stream from pull endpoint)
  → On complete: new model appears in list
  → AuditLog: model.pulled

Step 4: Admin clicks [Set as Chat Model]
  → PUT /api/v1/models/roles  {role: "chat", model: "llama3.2:3b"}
  → Active model badge in top bar updates
  → AuditLog: model.role.updated
```

---

## 7. Document Management Flows

### 7.1 Flow: Upload a Document

**Entry point:** Analyst/Admin navigates to `/documents` or `/knowledge-bases/{id}`.

```
Step 1: User clicks [Upload Document]
  → Modal opens with:
     - File picker (drag and drop or click to browse)
     - Knowledge Base selector dropdown
     - "Run OCR" toggle (default: ON)
     - "Process Now" button

Step 2: User drags file(s) or selects from browser
  → Client-side validation: file type and size check
  → If invalid: show inline error "Only PDF, DOCX, TXT, PNG, JPG, CSV, MD allowed. Max 50MB."

Step 3: User clicks "Process Now"
  → POST /api/v1/documents/upload (multipart)
  → Modal shows: "Uploading..."
  → Server saves file, returns document_id and status "pending"
  → Modal shows: "Processing..."

Step 4: Status polling
  → GET /api/v1/documents/{id}/status  (poll every 3s)
  → Progress steps shown:
     ✓ File received
     ↻ Extracting text...      ← current step (spinner)
       Running OCR...
       Chunking...
       Generating embeddings...
       Indexing to knowledge base...

  ── [Success path] ──
  Step 5a: status = "indexed"
    → ✓ All steps checked
    → Show: "Document ready. {N} chunks indexed."
    → Document appears in KB document list
    → AuditLog: document.indexed

  ── [Failure path] ──
  Step 5b: status = "failed"
    → ✗ icon on failed step
    → Show error message from server
    → Option: [Retry] or [Delete]
    → AuditLog: document.processing.failed
```

---

### 7.2 Flow: Delete a Document

**Entry point:** Analyst/Admin on document list, clicks delete icon.

```
Step 1: Confirmation dialog
  → "Delete '{filename}'? This will remove all indexed chunks from the knowledge base.
     This action cannot be undone."
  → [Cancel] [Delete]

Step 2: User confirms
  → DELETE /api/v1/documents/{id}
  → File removed from storage
  → Vectors deleted from Qdrant collection
  → Document record deleted
  → KB doc_count and chunk_count updated
  → AuditLog: document.deleted
```

---

## 8. Knowledge Base Flows

### 8.1 Flow: Create Knowledge Base

**Entry point:** Analyst/Admin clicks [+ New Knowledge Base].

```
Step 1: Modal form
  → Name (required, max 100 chars)
  → Description (optional)
  → Embedding Model (dropdown; default: nomic-embed-text)
  → [Create] button

Step 2: POST /api/v1/knowledge-bases
  → Qdrant collection created
  → KB record saved
  → User redirected to /knowledge-bases/{new_id}
  → AuditLog: knowledge_base.created
```

---

### 8.2 Flow: Query a Knowledge Base

**Entry point:** User on `/knowledge-bases/{id}` page, uses search input.

```
Step 1: User types a question in the query input
  → Example: "What are the procurement rules for contracts above ₹10 lakhs?"

Step 2: User presses Enter or clicks [Ask]
  → POST /api/v1/knowledge-bases/{id}/query
     {query: "...", top_k: 5, generate_answer: true}

Step 3: Loading state shown
  → "Searching knowledge base..."
  → "Generating answer..."

  ── [Success path] ──
  Step 4a: Response panel appears
    ┌─────────────────────────────────────────────────────┐
    │ ANSWER                                              │
    │ "Contracts above ₹10 lakhs require approval from   │
    │  the Finance Committee and three competitive..."    │
    │                                                     │
    │ SOURCES (3 found)                                   │
    │ ┌─ procurement_policy.pdf · Page 12 · Score: 0.91 ─┐│
    │ │ "...contracts exceeding ten lakh rupees must..."  ││
    │ └───────────────────────────────────────────────────┘│
    │ ┌─ amendment_2024.docx · Page 3 · Score: 0.87 ──────┐│
    │ │ "...the Finance Committee shall review all..."    ││
    │ └───────────────────────────────────────────────────┘│
    └─────────────────────────────────────────────────────┘
    → AuditLog: rag.query

  ── [Low confidence / no results] ──
  Step 4b: score < threshold or 0 results
    → "No relevant information found in this knowledge base for your query."
    → Suggest: "Try rephrasing or check if relevant documents are indexed."

  ── [Model unavailable] ──
  Step 4c: Ollama unavailable
    → "AI answer generation unavailable. Showing retrieved sources only."
    → Sources still shown (retrieval works without LLM)
```

---

## 9. AI Agent Flows

### 9.1 Flow: Start an Agent Run

**Entry point:** Analyst/Admin navigates to `/agents` and clicks [+ New Agent Run].

```
Step 1: Agent configuration panel
  → Goal input (required): multi-line text area
     Example: "Analyze the quarterly sales data in sales_q3.csv and
               identify the top 5 performing products by revenue."
  → Model selector (default: active chat model)
  → Knowledge bases to use (multi-select)
  → Max iterations (default: 10, max: 20)
  → [Start Agent] button

Step 2: POST /api/v1/agents/runs
  → Agent run created, status = "pending"
  → User redirected to /agents/runs/{id}

Step 3: Live execution view
  → SSE stream: GET /api/v1/agents/runs/{id}/stream
  → Execution trace panel updates in real-time:

  ┌──────────────────────────────────────────────────────┐
  │ AGENT RUN: "Analyze quarterly sales..."              │
  │ Status: ● Running  │  Iteration: 2/10               │
  ├──────────────────────────────────────────────────────┤
  │ PLAN                                                 │
  │  1. Read sales_q3.csv                                │
  │  2. Execute Python analysis                          │
  │  3. Summarize results                                │
  ├──────────────────────────────────────────────────────┤
  │ EXECUTION TRACE                                      │
  │                                                      │
  │ ✓ Step 1: file_read(path="sales_q3.csv")            │
  │   → 200 rows, 8 columns loaded   [12ms]             │
  │                                                      │
  │ ↻ Step 2: python_exec(code="import pandas...")      │
  │   → Executing in sandbox...                         │
  │                                                      │
  └──────────────────────────────────────────────────────┘

  ── [Normal completion] ──
  Step 4a: "complete" SSE event received
    → Status changes to ● Completed
    → Result panel shown:
      "Top 5 products: 1. Widget A (₹4.2L), 2. Widget B (₹3.8L)..."
    → Full execution trace collapsible
    → [Download Trace] [Start New Run]
    → AuditLog: agent.run.completed

  ── [Approval required mid-run] ──
  Step 4b: "approval_required" SSE event
    → Execution pauses
    → APPROVAL REQUIRED banner appears (see Flow 9.2)
    → Admin must approve before run continues

  ── [Max iterations exceeded] ──
  Step 4c: "error" event with code "max_iterations"
    → Status: ● Stopped (partial result)
    → Partial result shown with warning
    → AuditLog: agent.run.max_iterations

  ── [User cancels] ──
  Step 4d: User clicks [Cancel]
    → POST /api/v1/agents/runs/{id}/cancel
    → Status: ● Cancelled
    → AuditLog: agent.run.cancelled
```

---

### 9.2 Flow: Human Approval During Agent Run

**Entry point:** Agent attempts a High or Critical risk tool; approval event emitted.

**This flow runs concurrently — the requesting analyst sees the pause while the admin sees a notification.**

```
[Analyst's view]
  Step 1: Approval banner appears in agent run view:
    ┌──────────────────────────────────────────────────────┐
    │ ⚠️  APPROVAL REQUIRED                               │
    │                                                      │
    │ The agent wants to execute:                          │
    │  Tool: file_delete                                   │
    │  File: /workspace/old_report.pdf                     │
    │  Risk Level: HIGH                                    │
    │                                                      │
    │ Waiting for administrator approval...                │
    │ [Timeout in 4:58]                                    │
    └──────────────────────────────────────────────────────┘

[Admin's view]
  Step 1: Badge on Approvals sidebar item shows count (e.g. "1")
  Step 2: Admin navigates to /approvals
    → GET /api/v1/approvals/pending
    → List of pending approval requests

  Step 3: Admin clicks on the request
    → Detail view:
      Requested by: sonam (analyst)
      Agent goal: "Analyze quarterly..."
      Requested operation: file_delete
      File path: /workspace/old_report.pdf
      Risk level: HIGH
      Reason from agent: "Cleaning up temporary file after analysis"
      Requested at: 10:32:04 AM
      Expires at: 10:37:04 AM
      [Decision note text area]
      [Reject] [Approve]

  ── [Admin approves] ──
  Step 4a: POST /api/v1/approvals/{id}/approve  {note: "OK to delete"}
    → Approval status = "approved"
    → Agent run resumes automatically
    → Analyst sees approval banner replaced by tool execution result
    → AuditLog: approval.granted

  ── [Admin rejects] ──
  Step 4b: POST /api/v1/approvals/{id}/reject  {note: "Do not delete files"}
    → Approval status = "rejected"
    → Agent run receives rejection; step skipped
    → Agent continues reasoning with the rejection message
    → AuditLog: approval.rejected

  ── [Timeout] ──
  Step 4c: No admin action before expires_at
    → ApprovalService auto-rejects
    → Agent run: step skipped
    → AuditLog: approval.expired
```

---

## 10. Audit Log Flow

### 10.1 Flow: View and Filter Audit Logs

**Entry point:** Admin navigates to `/audit`.

```
Step 1: Audit log page loads
  → GET /api/v1/audit/logs (default: last 24 hours, all types)
  → Table of events:
    Timestamp | User | Event Type | Action | Resource | Outcome

Step 2: Admin applies filters (any combination):
  → Date range picker
  → Event type multi-select (auth, model, agent, tool, sandbox, approval, error...)
  → User filter (dropdown of all users)
  → Outcome filter (success / failure / pending)
  → [Apply Filters] button

Step 3: Results update
  → Pagination: 50 events per page
  → Click any row → expanded detail panel (full JSON metadata)

Step 4 (optional): Admin clicks [Verify Integrity]
  → GET /api/v1/audit/verify
  → Backend recalculates hash chain
  → "✓ Audit log integrity verified. 4,521 entries checked."
  → Or: "✗ Hash chain broken at entry #2341. Possible tampering."
  → AuditLog: audit.verify (logged in a separate integrity log)

Step 5 (optional): Admin clicks [Export]
  → Format selector: CSV or JSON
  → GET /api/v1/audit/export (with current filters applied)
  → File downloads
```

---

## 11. Settings Flows

### 11.1 Flow: User Management

**Entry point:** Admin navigates to `/settings` → "Users" tab.

```
Step 1: List of all users (email, username, role, last login, active/inactive)

Step 2: Admin clicks [Invite User] (actually creates the account directly)
  → Form: email, username, password, role
  → POST /api/v1/auth/register (admin-initiated)
  → New user appears in list

Step 3: Admin clicks a user → edit panel
  → Change role (dropdown: viewer / analyst / admin)
  → Deactivate / Reactivate toggle
  → Force password reset (sets a "must_change_password" flag)
  → [Save changes]
  → AuditLog: user.updated
```

---

### 11.2 Flow: System Configuration

**Entry point:** Admin navigates to `/settings` → "System" tab.

```
Settings panels (read-current / change and save):

1. Model Settings
   → Active chat model (dropdown)
   → Active embedding model (dropdown)
   → Max context tokens (numeric input)

2. Document Processing Settings
   → Chunk size (tokens) [default: 512]
   → Chunk overlap (tokens) [default: 50]
   → Max file size (MB) [default: 50]
   → OCR confidence threshold [default: 0.7]

3. Agent Settings
   → Max iterations [default: 10]
   → Default approval trigger level [high | critical]
   → Approval timeout (minutes) [default: 5]

4. Sandbox Settings
   → Memory limit (MB) [default: 256]
   → CPU quota (%) [default: 50]
   → Timeout (seconds) [default: 30]
   → [Enable HTTP Request Tool] toggle (disabled by default)

5. Audit Settings
   → Log retention (days) [default: 365]

Each panel: [Save] button → PUT /api/v1/system/config → AuditLog: config.updated
```

---

## 12. Error and Edge Case Flows

### 12.1 Service Unavailable Flow

**Scenario:** User attempts to chat but Ollama is offline.

```
Step 1: User sends message → POST /api/v1/chat/conversations/{id}/messages
Step 2: Backend attempts LLMClient.chat() → connection refused
Step 3: Backend returns SSE error event:
  event: error
  data: {"code": "llm_unavailable", "message": "The AI model service is offline."}
Step 4: Frontend displays banner:
  "⚠ AI service is currently unavailable. Check system status."
  [View Dashboard →] link
Step 5: Dashboard shows Ollama health check in red.
```

---

### 12.2 Unauthorized Access Flow

**Scenario:** Analyst tries to access `/audit` (admin-only route).

```
Step 1: Frontend router checks role → Analyst < Admin requirement
  → Redirect to Dashboard
  → Toast: "You don't have permission to access that page."
  (Frontend-level guard)

If API is called directly:
Step 1: GET /api/v1/audit/logs with Analyst JWT
Step 2: Backend role check → 403 Forbidden
  {"error": {"code": "insufficient_permissions", "message": "Admin role required."}}
Step 3: AuditLog: auth.access.denied
```

---

### 12.3 Large Document Upload Flow

**Scenario:** User uploads a 45MB scanned PDF.

```
Step 1: Upload with run_ocr=true
  → Upload time: ~10-30s depending on network/disk speed (within org)

Step 2: Processing begins
  → OCR on scanned pages: ~5-15s per page (CPU mode)
  → For a 100-page document: ~10-25 minutes total
  → Status polling every 3s shows current page/step progress
  → No timeout on client — processing continues in background

Step 3: UI shows estimated time (based on page count × avg OCR time per page)
  → User can navigate away — processing continues
  → Bell notification (in-app) when document is ready
  → AuditLog: document.indexed with duration_ms
```

---

### 12.4 Agent Max Iterations Flow

**Scenario:** Agent enters a loop and hits the iteration limit.

```
Step 1: Agent reaches iteration 10 (or configured max)
Step 2: AgentService terminates the loop
  → status = "failed" with reason "max_iterations_exceeded"
  → Partial results compiled from completed steps
Step 3: SSE "error" event sent to frontend
  → Run detail view shows:
    "● Stopped: Maximum iterations (10) reached."
    "Partial result: [whatever was computed so far]"
    Full execution trace still available
  → AuditLog: agent.run.max_iterations
Step 4: User can start a new run with a more specific goal or higher iteration limit
```

---

## 13. State Transition Diagrams

### 13.1 Document Processing States

```
[Upload Received]
      │
      ▼
   pending
      │
      ▼
  processing ──── (failure) ───► failed
      │
      ▼
   indexed ◄──────────────── (re-index)
```

### 13.2 Agent Run States

```
[User submits goal]
      │
      ▼
   pending
      │
      ▼
   running ◄─────────────── (auto-resumes after approval)
      │
      ├── awaiting_approval ──► (admin approves/rejects) ──► running
      │
      ├── (max iterations)  ──► failed
      │
      ├── (user cancel)     ──► cancelled
      │
      └── (goal achieved)   ──► completed
```

### 13.3 Approval Request States

```
[High-risk tool call in agent run]
      │
      ▼
   pending ──── (admin approves) ──► approved
      │
      ├── (admin rejects)  ──► rejected
      │
      └── (timeout)        ──► expired

expired → treated as rejected
```

---

## 14. First-Run Setup Flow

**Scenario:** Brand new deployment; no users exist yet.

```
Step 1: docker compose up (admin runs on their machine)
Step 2: Wait ~60 seconds for all services to start
Step 3: Navigate to http://localhost

Step 4: First-run detection
  → Backend checks: user count = 0
  → API returns: {"setup_required": true}
  → Frontend shows Setup Wizard instead of Login

Step 5: Setup Wizard — Step 1 of 3: Create Admin Account
  → Full name, email, password (min 12 chars), confirm password
  → [Continue]

Step 6: Setup Wizard — Step 2 of 3: Configure AI Models
  → Detects available Ollama models
  → If none: "Pull models first. Run: ollama pull llama3.2:3b"
  → If models available: select default chat model, embedding model
  → [Continue]

Step 7: Setup Wizard — Step 3 of 3: Ready
  → Checklist:
     ✓ Admin account created
     ✓ Chat model configured: llama3.2:3b
     ✓ Embedding model configured: nomic-embed-text
     ✓ Qdrant: connected
     ✓ Database: initialized
  → [Open Workbench]

Step 8: Admin lands on Dashboard
  → AuditLog: system.setup.completed
```

---

## 15. Notification System

The MVP uses in-app notifications (no email/SMS).

| Event | Who notified | Type |
|-------|-------------|------|
| Document indexed successfully | Uploader | Toast (success) |
| Document processing failed | Uploader | Toast (error) |
| New approval request | All admins | Badge count + Toast |
| Approval approved/rejected | Requesting analyst | Toast |
| Agent run completed | Run creator | Toast |
| Service goes offline | All users (dashboard) | Status badge changes red |
| Audit hash chain broken | Admins | System alert banner |

Notifications are implemented as polling (every 30s) on `/api/v1/notifications` endpoint (simple count endpoint) in MVP. Push via WebSocket in future scope.

---

## 16. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-08-23 | Lead Architect | Initial App/User Flow document |

---

*End of App/User Flow*

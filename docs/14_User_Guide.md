# 14 User Guide
## Sovereign AI Workbench

**Version:** 1.0
**Status:** Draft
**Classification:** Internal - SIH 2026 Prototype
**Audience:** End users (Analysts, Admins, Viewers)

---

## 1. Introduction

Sovereign AI Workbench is a privacy-first AI platform that lets you use AI capabilities entirely within your organization's own infrastructure. Everything runs locally — no data is sent to any cloud AI service.

**What you can do:**
- Chat with local AI models
- Upload and analyze documents using AI
- Build a searchable knowledge base from your documents
- Run AI agents to automate multi-step analysis tasks
- View a full audit trail of all AI activity

**What never happens:**
- Your documents, questions, or AI responses are never sent to OpenAI, Google, or any cloud provider
- The "🔒 Processing locally" indicator you see on every AI page confirms this

---

## 2. Getting Started

### 2.1 Accessing the Workbench

Open your browser and navigate to the URL provided by your administrator (typically `http://localhost` or an internal network address).

### 2.2 Logging In

1. Enter your **email address** and **password**
2. Click **Sign In**

If you don't have an account, contact your administrator. The admin creates accounts — there is no public self-registration.

### 2.3 First Look: The Dashboard

After logging in, you see the **Dashboard**:

- **Service Health** — green dots mean Ollama (AI), Qdrant (knowledge base search), and the database are all working
- **Resource Usage** — shows how much CPU, RAM, and disk the system is using
- **Active Models** — shows which AI models are currently configured
- **Recent Activity** — a feed of recent actions in the system
- **Quick Actions** — buttons to start common tasks immediately

---

## 3. Chat with AI

### 3.1 Starting a Conversation

1. Click **Chat** in the sidebar
2. Click **+ New Chat** (or the New Chat button on the dashboard)
3. Select an AI model from the dropdown at the top of the chat area
4. Type your message in the input field at the bottom
5. Press **Enter** or click the **Send** button

You will see the AI response stream in word by word. The **🔒 Processing locally** badge confirms your message stayed on-premise.

### 3.2 Using a Knowledge Base in Chat

If you want the AI to answer based on your uploaded documents:
1. Click the **KB** dropdown in the chat toolbar
2. Select one or more knowledge bases
3. Send your message normally

The AI will search your documents and include relevant context in its answer. Source citations appear below the response — click them to see the exact passage used.

### 3.3 Configuring a System Prompt

A system prompt tells the AI how to behave for a conversation (e.g., "You are a legal document analyst").

1. Click the **⚙ gear icon** near the model selector
2. Type your system prompt
3. This applies to the current conversation only

### 3.4 Conversation History

Previous conversations appear in the left sidebar. Click any to reload it and continue.

To **export** a conversation: click the three-dot menu on a conversation → **Export** → choose JSON or Markdown.

---

## 4. Documents & Knowledge Bases

### 4.1 Creating a Knowledge Base

A knowledge base is a collection of documents that the AI can search through.

1. Click **Knowledge Bases** in the sidebar
2. Click **+ New Knowledge Base**
3. Enter a **name** (e.g., "Policy Documents 2026")
4. Optionally add a description
5. Click **Create**

### 4.2 Uploading Documents

1. Navigate to your knowledge base
2. Click **Upload Document**
3. Drag and drop files onto the upload area, or click to browse
4. Supported formats: PDF, Word (DOCX), plain text, Markdown, CSV, PNG, JPG
5. Maximum file size: 50 MB per file
6. Make sure **Run OCR** is turned on for scanned documents or images
7. Click **Process Now**

The document will be automatically:
- Extracted (text pulled out of the file)
- OCR'd (if it's a scanned document or image)
- Chunked (split into searchable sections)
- Embedded (converted to a searchable format)
- Indexed (stored for retrieval)

You can track progress in real time. Processing a large scanned PDF can take several minutes — this is normal for CPU-based OCR.

### 4.3 Querying Your Knowledge Base

1. Navigate to your knowledge base
2. Type your question in the query input
3. Click **Ask**

The system will:
1. Search for relevant passages in your documents
2. Show you the **sources** it found (with relevance scores)
3. Generate an **answer** based on those sources (if a language model is available)

**Source citations** show the document name, page number, and the relevant text excerpt. This lets you verify the AI's answer.

If the system says **"low confidence"**, it means the most relevant passage only weakly matched your question. The answer may still be useful, but check the sources carefully.

### 4.4 Managing Documents

- To **view** all documents in a knowledge base, click its name in the list
- To **delete** a document, click the trash icon next to it — this also removes its indexed content
- To **re-index** all documents (e.g., after changing embedding models), contact your admin

---

## 5. AI Agents

Agents can complete multi-step tasks on your behalf by combining AI reasoning with controlled tools.

### 5.1 What Agents Can Do

- Read and analyze files in the workspace
- Execute Python code for data analysis (in an isolated sandbox)
- Search knowledge bases
- Perform calculations

Agents **cannot**:
- Access the internet (unless explicitly enabled by an admin)
- Access files outside the designated workspace
- Perform irreversible actions (like deleting files) without administrator approval

### 5.2 Starting an Agent Run

1. Click **Agents** in the sidebar
2. Click **+ New Agent Run**
3. Enter a clear **goal** describing what you want the agent to accomplish
   - Good: "Analyze the file sales_q3.csv and identify the top 5 products by revenue"
   - Less good: "Do stuff with data"
4. Optionally select specific knowledge bases the agent can search
5. Click **Start Agent**

### 5.3 Watching the Agent Work

The agent execution view shows:
- **Plan** — the steps the agent intends to take
- **Execution Trace** — each tool call as it happens, with inputs and outputs
- **Status** — current iteration count and elapsed time

You can **Cancel** the run at any time.

### 5.4 Approval Required

If the agent attempts a **high-risk operation** (such as deleting a file), it will pause and display:

> ⚠️ APPROVAL REQUIRED — Waiting for administrator approval...

An administrator will be notified. Once they approve or reject the request, the agent will continue or skip that step. The approval request expires after 5 minutes if no decision is made.

### 5.5 Viewing Results

When an agent run completes:
- The **result** appears at the bottom of the execution view
- The full **trace** shows every step taken, every tool called, and every output
- All steps are also recorded in the **Audit Log**

---

## 6. Role-Based Access

Different users have different permissions:

| Action | Viewer | Analyst | Admin |
|--------|--------|---------|-------|
| View dashboard | ✓ | ✓ | ✓ |
| Chat with AI | ✓ | ✓ | ✓ |
| Upload documents | — | ✓ | ✓ |
| Create knowledge bases | — | ✓ | ✓ |
| Run AI agents | — | ✓ | ✓ |
| Approve high-risk actions | — | — | ✓ |
| View audit logs | — | — | ✓ |
| Manage users and models | — | — | ✓ |

---

## 7. For Administrators

### 7.1 Managing Models

Navigate to **Models** to:
- View all models installed in Ollama and their status
- Set the **active chat model** (used by default in chat)
- Set the **active embedding model** (used for knowledge base indexing)
- Pull new models by name (e.g., `mistral:7b-q4`)
- Run a health check on any model

**Note:** Pulling a model requires internet access. After the initial pull, the system works fully offline.

### 7.2 Managing Users

Navigate to **Settings → Users** to:
- Create new user accounts
- Change a user's role (Viewer / Analyst / Admin)
- Deactivate accounts
- Force a password reset

### 7.3 Reviewing Approvals

Navigate to **Approvals** to:
- See all pending approval requests from agent runs
- Click any request to see the full operation detail, risk level, and requesting agent's reasoning
- **Approve** or **Reject** with an optional note

Approvals expire after 5 minutes. Expired approvals auto-reject.

### 7.4 Audit Log

Navigate to **Audit** to:
- See a full, tamper-evident log of all system activity
- Filter by event type, user, date range, or outcome
- Export the log as CSV or JSON for compliance reporting
- Click **Verify Integrity** to confirm the audit log has not been tampered with

### 7.5 System Configuration

Navigate to **Settings → System** to configure:
- Default chunk size and overlap for document processing
- Agent iteration limits
- Sandbox resource limits (memory, CPU, timeout)
- Enabling the HTTP request tool (disabled by default for security)

---

## 8. Common Questions

**Q: Why is the AI response slow?**
AI inference on a CPU is slower than on a GPU. Expect 2–10 seconds for the first token, then steady streaming. Large models on CPU will be slower than small ones.

**Q: Why did document processing take so long?**
OCR (reading text from scanned documents and images) is the slow step. A 100-page scanned PDF can take 10–25 minutes on a CPU. Text-only PDFs process in seconds.

**Q: The AI said something incorrect. Why?**
Local AI models can make mistakes. Always verify important information using the source citations provided in knowledge base answers. The system shows you where the answer came from so you can check.

**Q: I uploaded a document but the knowledge base query doesn't find anything relevant.**
Make sure the document status shows "Indexed" (not "Processing" or "Failed"). Also check that you are querying the right knowledge base.

**Q: Why does the agent pause and ask for approval?**
The agent tried to do something risky (like deleting a file). This is a security feature — risky operations require an administrator to explicitly approve them. Contact your admin.

**Q: Can I use this to process classified information?**
The system processes data locally and does not send data externally. However, your organization's information security and classification policies apply. Consult your security officer about appropriate use.

---

## 9. Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl + Enter` | Send chat message |
| `Ctrl + /` | Open a new chat |
| `Esc` | Close a modal or dialog |
| `↑` in chat input | Load previous message |

---

## 10. Revision History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-08-23 | Initial User Guide |

---

*End of User Guide*

/**
 * Component-level regression tests for the stale-response races in ChatPage.
 *
 * These exercise the ACTUAL component code (unlike chatStore.test.ts which
 * models store behaviour), so they cover:
 *
 *  A. Sidebar must never be left stuck on "Loading…" when a lazy
 *     getConversation resolves with stale (assistant-less) data while the
 *     conversation is actively streaming. The bug: a single loading flag was
 *     shared by both the sidebar list and the detail fetch, and the streaming
 *     guard's early-return skipped clearing it.
 *
 *  B. refreshConversations must be race-safe: when two refreshes overlap, the
 *     latest one wins and a stale response is silently ignored.
 *
 *  C. A stale getConversation while a stream is active must neither be imposed
 *     as the conversation detail (clobbering optimistic/streaming content) nor
 *     leave the loading state stuck.
 *
 * Runtime note: this file forces the jsdom environment because it renders the
 * real React component. All network layers (chatApi, providersApi, fetch) are
 * mocked so no real requests are made.
 */
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import ChatPage from '../pages/ChatPage'
import { useChatStore } from '../stores/chatStore'
import { useAuthStore } from '../stores/authStore'

// jsdom lacks scrollIntoView (called by ChatPage's auto-scroll effect)
if (typeof window !== 'undefined' && typeof window.HTMLElement !== 'undefined') {
  Object.defineProperty(window.HTMLElement.prototype, 'scrollIntoView', {
    value: () => {}, configurable: true, writable: true,
  })
}

// ---------------------------------------------------------------- mocks ----

let routeParams: { convId?: string } = {}

vi.mock('react-router-dom', () => ({
  useParams: () => routeParams,
  useNavigate: () => vi.fn(),
}))

const chatApiMock = vi.hoisted(() => ({
  listConversations: vi.fn(),
  getConversation: vi.fn(),
  getAgentEvents: vi.fn(),
  createConversation: vi.fn(),
  renameConversation: vi.fn(),
  deleteConversation: vi.fn(),
  exportConversation: vi.fn(),
}))
vi.mock('../api/chat', () => ({ chatApi: chatApiMock }))

const providersMock = vi.hoisted(() => ({
  providersApi: { list: vi.fn(), getModels: vi.fn() },
  prefsApi: { set: vi.fn() },
}))
vi.mock('../api/providers', () => providersMock)

// ------------------------------------------------------------- fixtures ----

interface Conv {
  id: string; title: string | null; model_name: string
  system_prompt: string | null; context_mode: string
  created_at: string; updated_at: string; message_count: number
}

const conv = (id: string, title: string): Conv => ({
  id, title, model_name: 'openrouter/free', system_prompt: null,
  context_mode: 'chat', created_at: '2026-09-07T00:00:00Z',
  updated_at: '2026-09-07T00:00:00Z', message_count: 1,
})

const detail = (id: string, title: string, messages: unknown[]): any => ({
  ...conv(id, title), messages,
})

const userMsg = (content: string) => ({
  id: 'u-' + content, role: 'user', content,
  token_count: null, finish_reason: null, created_at: '2026-09-07T00:00:00Z',
})

const assistantMsg = (content: string) => ({
  id: 'a-' + content, role: 'assistant', content,
  token_count: null, finish_reason: null, created_at: '2026-09-07T00:00:00Z',
})

const deferred = <T,>() => {
  let resolve!: (v: T) => void
  let reject!: (e: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

function resetState() {
  useAuthStore.setState({
    accessToken: 'tok',
    user: { id: 'u1', email: 'a@b.c', username: 'analyst', role: 'analyst' } as any,
  })
  useChatStore.setState({ conversations: [], activeStreams: {}, agentEvents: {} })
}

beforeEach(() => {
  resetState()
  routeParams = {}
  chatApiMock.listConversations.mockReset()
  chatApiMock.getConversation.mockReset()
  chatApiMock.getAgentEvents.mockReset()
  chatApiMock.createConversation.mockReset()
  chatApiMock.getAgentEvents.mockResolvedValue({ events: [], runs: [] })
  providersMock.providersApi.getModels.mockReset()
  providersMock.providersApi.getModels.mockResolvedValue([])
  providersMock.prefsApi.set.mockReset()
  providersMock.prefsApi.set.mockResolvedValue(undefined)
  // The model-options effect iterates providerList from list(); return none.
  providersMock.providersApi.list.mockResolvedValue([])
})

// ------------------------------------------------------------------ tests --

describe('ChatPage refresh races (component-level)', () => {
  it('A: sidebar is never stuck on "Loading…" after stale detail fetch during stream', async () => {
    // Simulate an active autonomous run for conv-1 (doSend started a stream).
    useChatStore.getState().startStream('conv-1')

    // Pre-seed the list so the sidebar has content regardless of refresh timing.
    useChatStore.setState({ conversations: [conv('conv-1', 'Conv One')] })
    chatApiMock.listConversations.mockResolvedValue([conv('conv-1', 'Conv One')])

    // Server snapshot is STALE while the run is still compiling: user message
    // only, no assistant response yet.
    chatApiMock.getConversation.mockResolvedValue(
      detail('conv-1', 'Conv One', [userMsg('hello')]),
    )

    routeParams = { convId: 'conv-1' }
    const { unmount } = render(<ChatPage />)

    // Let the detail effect + list refresh settle.
    await waitFor(() => expect(screen.queryAllByText('Loading…')).toHaveLength(0))

    // REGRESSION: the sidebar must show the conversation list, NOT "Loading…".
    // (Before the fix, the streaming guard's early return left the shared
    //  loading flag true forever, sticking the sidebar on "Loading…".)
    expect(screen.getAllByText('Conv One').length).toBeGreaterThan(0)

    // The stale (assistant-less) snapshot must NOT become the rendered detail —
    // its user message should not appear as if it were the current conversation.
    expect(screen.queryAllByText('hello')).toHaveLength(0)

    unmount()
  })

  it('B: stale conversation-list refresh is ignored (latest wins)', async () => {
    const stale = deferred<Conv[]>()
    const newest = deferred<Conv[]>()

    // Call 1 = mount refresh (slow, will turn out stale).
    // Call 2 = post-send refresh (newest, must win).
    let calls = 0
    chatApiMock.listConversations.mockImplementation(() => {
      calls += 1
      return calls === 1 ? stale.promise : newest.promise
    })

    chatApiMock.createConversation.mockImplementation(async (data: any) => ({
      ...conv('conv-9', data.title || 'New chat'), title: data.title || 'New chat',
    }))
    chatApiMock.getConversation.mockResolvedValue(
      detail('conv-9', 'New chat', [userMsg('hello'), assistantMsg('answer')]),
    )

    // Mock the send flow's network layer: proactive auth refresh + agent SSE.
    const fetchMock = vi.fn((url: string) => {
      if (url.includes('/auth/refresh')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ access_token: 'tok2' }) })
      }
      if (url.includes('/agent') || url.includes('/messages')) {
        const body = 'event: done\ndata: {"state":"completed","content":"ok"}\n\n'
        const stream = new ReadableStream({
          start(ctl) {
            ctl.enqueue(new TextEncoder().encode(body))
            ctl.close()
          },
        })
        return Promise.resolve({ ok: true, body: stream })
      }
      return Promise.reject(new Error('unhandled fetch: ' + url))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<ChatPage />) // mount → refresh call 1 (pending)

    // Send a message — doSend creates a conv, streams an agent run (SSE done),
    // then refreshes the list in its finally block (call 2).
    fireEvent.change(screen.getByLabelText('Chat message input'), { target: { value: 'Test send' } })
    fireEvent.click(screen.getByLabelText('Send message'))

    // Newest refresh resolves first → its list is committed and sidebar shows it.
    newest.resolve([conv('conv-9', 'Newest Conv')])
    await waitFor(() => expect(screen.getAllByText('Newest Conv').length).toBeGreaterThan(0))

    // Stale (older) refresh resolves LAST → must be ignored, not applied.
    stale.resolve([conv('c-1', 'Stale Conv')])
    await waitFor(() => {
      expect(screen.queryAllByText('Stale Conv')).toHaveLength(0)
      expect(screen.getAllByText('Newest Conv').length).toBeGreaterThan(0)
      expect(screen.queryAllByText('Loading…')).toHaveLength(0)
    })

    vi.unstubAllGlobals()
  })

  it('C: stale getConversation during stream clears loading and is not imposed as detail', async () => {
    // Active stream for the conversation being viewed.
    useChatStore.getState().startStream('conv-1')
    useChatStore.setState({ conversations: [conv('conv-1', 'Conv One')] })
    chatApiMock.listConversations.mockResolvedValue([conv('conv-1', 'Conv One')])

    // The stale snapshot is missing the assistant message the run is producing.
    chatApiMock.getConversation.mockResolvedValue(
      detail('conv-1', 'Conv One', [userMsg('hello')]),
    )

    routeParams = { convId: 'conv-1' }
    const { unmount } = render(<ChatPage />)

    await waitFor(() => expect(screen.queryAllByText('Loading…')).toHaveLength(0))

    // The sidebar list is intact and the compose area is functional — nothing was
    // left stuck on a loading state.
    expect(screen.getAllByText('Conv One').length).toBeGreaterThan(0)
    expect(screen.getByLabelText('Chat message input')).toBeTruthy()

    // The stale snapshot was NOT poured into the view as the current detail
    // (its user message should never appear onscreen as a committed message).
    expect(screen.queryAllByText('hello')).toHaveLength(0)

    unmount()
  })
})
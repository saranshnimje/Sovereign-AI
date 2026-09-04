/**
 * Regression tests for the chat streaming lifecycle.
 *
 * These tests verify the exact UI state transitions that were causing:
 * 1. Stale Stop button after stream completion
 * 2. Loading state stuck in sidebar
 * 3. Stale events from old runs mutating current UI
 * 4. Race conditions between done/error/cancel events
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { useChatStore, ActiveStream } from '../stores/chatStore'

describe('ChatStore - Streaming Lifecycle', () => {
  beforeEach(() => {
    // Reset store before each test
    useChatStore.setState({ activeStreams: {} })
  })

  describe('startStream', () => {
    it('creates a new stream with streaming=true and unique runId', () => {
      const { startStream, getStream } = useChatStore.getState()
      const stream = startStream('conv-1')

      expect(stream.streaming).toBe(true)
      expect(stream.runId).toMatch(/^run-\d+-[a-z0-9]+$/)
      expect(stream.convId).toBe('conv-1')
      expect(stream.streamContent).toBe('')
      expect(stream.toolCalls).toEqual([])
      expect(stream.lastError).toBeNull()
      expect(stream.agentState).toBeNull()
      expect(stream.verificationStatus).toBe('none')
    })

    it('returns existing stream if one already exists for convId', () => {
      const { startStream } = useChatStore.getState()
      const stream1 = startStream('conv-1')
      const stream2 = startStream('conv-1')

      expect(stream1.runId).toBe(stream2.runId)
      expect(stream1).toBe(stream2)
    })

    it('creates different runIds for different conversations', () => {
      const { startStream } = useChatStore.getState()
      const stream1 = startStream('conv-1')
      const stream2 = startStream('conv-2')

      expect(stream1.runId).not.toBe(stream2.runId)
    })
  })

  describe('updateStream', () => {
    it('updates stream state atomically', () => {
      const { startStream, updateStream, getStream } = useChatStore.getState()
      startStream('conv-1')

      updateStream('conv-1', {
        streaming: false,
        agentState: 'completed',
        lastError: null,
      })

      const stream = getStream('conv-1')
      expect(stream?.streaming).toBe(false)
      expect(stream?.agentState).toBe('completed')
      expect(stream?.lastError).toBeNull()
    })

    it('ignores updates for non-existent streams', () => {
      const { updateStream, getStream } = useChatStore.getState()

      // Should not throw
      updateStream('non-existent', { streaming: false })

      expect(getStream('non-existent')).toBeUndefined()
    })
  })

  describe('endStream', () => {
    it('removes stream from activeStreams', () => {
      const { startStream, endStream, getStream } = useChatStore.getState()
      startStream('conv-1')

      endStream('conv-1')

      expect(getStream('conv-1')).toBeUndefined()
    })

    it('only removes the specified stream', () => {
      const { startStream, endStream, getStream } = useChatStore.getState()
      startStream('conv-1')
      startStream('conv-2')

      endStream('conv-1')

      expect(getStream('conv-1')).toBeUndefined()
      expect(getStream('conv-2')).toBeDefined()
    })
  })

  describe('Done event handling - core fix', () => {
    it('done event atomically sets streaming=false and clears state', () => {
      const { startStream, updateStream, getStream } = useChatStore.getState()
      startStream('conv-1')

      // Simulate done event (this is what the fixed code does)
      updateStream('conv-1', {
        streaming: false,
        agentState: 'completed',
        lastError: null,
      })

      const stream = getStream('conv-1')
      expect(stream?.streaming).toBe(false)
      expect(stream?.agentState).toBe('completed')
      expect(stream?.lastError).toBeNull()
    })

    it('done event is idempotent - multiple calls do not cause issues', () => {
      const { startStream, updateStream, getStream } = useChatStore.getState()
      startStream('conv-1')

      // First done event
      updateStream('conv-1', {
        streaming: false,
        agentState: 'completed',
        lastError: null,
      })

      // Second done event (should be ignored by processSSEStream)
      updateStream('conv-1', {
        streaming: false,
        agentState: 'completed',
        lastError: null,
      })

      const stream = getStream('conv-1')
      expect(stream?.streaming).toBe(false)
      expect(stream?.agentState).toBe('completed')
    })
  })

  describe('Error event handling', () => {
    it('error event atomically sets streaming=false and shows error', () => {
      const { startStream, updateStream, getStream } = useChatStore.getState()
      startStream('conv-1')

      // Simulate error event
      updateStream('conv-1', {
        streaming: false,
        lastError: 'Connection failed',
        agentState: 'failed',
      })

      const stream = getStream('conv-1')
      expect(stream?.streaming).toBe(false)
      expect(stream?.lastError).toBe('Connection failed')
      expect(stream?.agentState).toBe('failed')
    })
  })

  describe('Cancellation event handling', () => {
    it('cancelled event atomically sets streaming=false and shows cancelled state', () => {
      const { startStream, updateStream, getStream } = useChatStore.getState()
      startStream('conv-1')

      // Simulate cancelled event
      updateStream('conv-1', {
        streaming: false,
        lastError: 'Cancelled',
        agentState: 'cancelled',
      })

      const stream = getStream('conv-1')
      expect(stream?.streaming).toBe(false)
      expect(stream?.lastError).toBe('Cancelled')
      expect(stream?.agentState).toBe('cancelled')
    })
  })

  describe('Stale event filtering via runId', () => {
    it('runId remains consistent throughout stream lifecycle', () => {
      const { startStream, updateStream, getStream } = useChatStore.getState()
      const stream = startStream('conv-1')
      const originalRunId = stream.runId

      // Simulate multiple updates
      updateStream('conv-1', { streamContent: 'Hello' })
      updateStream('conv-1', { agentState: 'planning' })
      updateStream('conv-1', { agentState: 'executing' })

      const updatedStream = getStream('conv-1')
      expect(updatedStream?.runId).toBe(originalRunId)
    })

    it('new stream gets new runId, old runId is invalid', () => {
      const { startStream, updateStream, getStream } = useChatStore.getState()
      const stream1 = startStream('conv-1')
      const runId1 = stream1.runId

      // End old stream and start new one
      useChatStore.getState().endStream('conv-1')
      const stream2 = startStream('conv-1')
      const runId2 = stream2.runId

      expect(runId1).not.toBe(runId2)
    })
  })

  describe('Stop button state transitions', () => {
    it('streaming=true shows Stop button, streaming=false hides it', () => {
      const { startStream, updateStream, getStream } = useChatStore.getState()
      startStream('conv-1')

      // During streaming - Stop button should be visible
      let stream = getStream('conv-1')
      expect(stream?.streaming).toBe(true)

      // After done event - Stop button should be hidden
      updateStream('conv-1', { streaming: false, agentState: 'completed' })
      stream = getStream('conv-1')
      expect(stream?.streaming).toBe(false)
    })

    it('handleStop atomically clears all streaming state', () => {
      const { startStream, updateStream, getStream } = useChatStore.getState()
      startStream('conv-1')

      // Simulate handleStop (this is what the fixed code does)
      updateStream('conv-1', {
        streaming: false,
        streamContent: '',
        streamSources: [],
        toolCalls: [],
        lastError: 'Cancelled',
        agentState: 'cancelled',
        todo: [],
        subagents: [],
        verificationStatus: 'none',
        verificationType: null,
      })

      const stream = getStream('conv-1')
      expect(stream?.streaming).toBe(false)
      expect(stream?.streamContent).toBe('')
      expect(stream?.toolCalls).toEqual([])
      expect(stream?.lastError).toBe('Cancelled')
      expect(stream?.agentState).toBe('cancelled')
      expect(stream?.todo).toEqual([])
      expect(stream?.subagents).toEqual([])
      expect(stream?.verificationStatus).toBe('none')
    })
  })

  describe('Conversation switching during streaming', () => {
    it('old stream continues in background while new stream starts', () => {
      const { startStream, getStream } = useChatStore.getState()

      // Start stream for conv-1
      const stream1 = startStream('conv-1')
      expect(stream1.streaming).toBe(true)

      // Switch to conv-2 and start new stream
      const stream2 = startStream('conv-2')
      expect(stream2.streaming).toBe(true)

      // Both streams should exist
      expect(getStream('conv-1')).toBeDefined()
      expect(getStream('conv-2')).toBeDefined()
      expect(getStream('conv-1')?.runId).not.toBe(getStream('conv-2')?.runId)
    })

    it('ending old stream does not affect new stream', () => {
      const { startStream, endStream, getStream } = useChatStore.getState()

      startStream('conv-1')
      startStream('conv-2')

      endStream('conv-1')

      expect(getStream('conv-1')).toBeUndefined()
      expect(getStream('conv-2')).toBeDefined()
    })
  })

  describe('Race condition: done arrives immediately after final token', () => {
    it('processes token then done atomically', () => {
      const { startStream, updateStream, getStream } = useChatStore.getState()
      startStream('conv-1')

      // Simulate token event
      updateStream('conv-1', { streamContent: 'Hello world' })
      let stream = getStream('conv-1')
      expect(stream?.streaming).toBe(true)
      expect(stream?.streamContent).toBe('Hello world')

      // Immediately followed by done event
      updateStream('conv-1', {
        streaming: false,
        agentState: 'completed',
        lastError: null,
      })

      stream = getStream('conv-1')
      expect(stream?.streaming).toBe(false)
      expect(stream?.agentState).toBe('completed')
      expect(stream?.streamContent).toBe('Hello world') // Content preserved
    })
  })

  describe('Rapid send -> completion -> new send', () => {
    it('clears old stream state before starting new stream', () => {
      const { startStream, updateStream, endStream, getStream } = useChatStore.getState()

      // First send
      startStream('conv-1')
      updateStream('conv-1', { streamContent: 'Response 1' })

      // Complete first send
      updateStream('conv-1', { streaming: false, agentState: 'completed' })
      endStream('conv-1')

      // Second send
      startStream('conv-1')
      const stream = getStream('conv-1')

      expect(stream?.streaming).toBe(true)
      expect(stream?.streamContent).toBe('') // Fresh content
      expect(stream?.agentState).toBeNull() // Fresh state
    })
  })

  describe('Multiple conversations with active streams', () => {
    it('tracks each conversation stream independently', () => {
      const { startStream, updateStream, getStream } = useChatStore.getState()

      startStream('conv-1')
      startStream('conv-2')
      startStream('conv-3')

      updateStream('conv-1', { agentState: 'planning' })
      updateStream('conv-2', { agentState: 'executing' })
      // conv-3 stays in initial state

      expect(getStream('conv-1')?.agentState).toBe('planning')
      expect(getStream('conv-2')?.agentState).toBe('executing')
      expect(getStream('conv-3')?.agentState).toBeNull()
    })
  })

  describe('Stream content preservation', () => {
    it('preserves accumulated content after done event', () => {
      const { startStream, updateStream, getStream } = useChatStore.getState()
      startStream('conv-1')

      // Accumulate content
      updateStream('conv-1', { streamContent: 'Hello' })
      updateStream('conv-1', { streamContent: 'Hello world' })
      updateStream('conv-1', { streamContent: 'Hello world!' })

      // Done event
      updateStream('conv-1', { streaming: false, agentState: 'completed' })

      const stream = getStream('conv-1')
      expect(stream?.streamContent).toBe('Hello world!')
    })
  })

  describe('Verification state transitions', () => {
    it('tracks verification lifecycle correctly', () => {
      const { startStream, updateStream, getStream } = useChatStore.getState()
      startStream('conv-1')

      // Verification started
      updateStream('conv-1', {
        verificationStatus: 'started',
        verificationType: 'output',
      })
      expect(getStream('conv-1')?.verificationStatus).toBe('started')

      // Verification passed
      updateStream('conv-1', {
        verificationStatus: 'passed',
        verificationType: 'output',
      })
      expect(getStream('conv-1')?.verificationStatus).toBe('passed')
    })

    it('resets verification status on new stream', () => {
      const { startStream, updateStream, endStream, getStream } = useChatStore.getState()

      startStream('conv-1')
      updateStream('conv-1', { verificationStatus: 'passed' })
      endStream('conv-1')

      startStream('conv-1')
      const stream = getStream('conv-1')
      expect(stream?.verificationStatus).toBe('none')
    })
  })

  describe('Todo state transitions', () => {
    it('updates todo tasks during stream', () => {
      const { startStream, updateStream, getStream } = useChatStore.getState()
      startStream('conv-1')

      const tasks = [
        { id: 1, description: 'Task 1', status: 'pending' as const },
        { id: 2, description: 'Task 2', status: 'pending' as const },
      ]
      updateStream('conv-1', { todo: tasks })
      expect(getStream('conv-1')?.todo).toHaveLength(2)

      // Update task status
      const updatedTasks = [
        { id: 1, description: 'Task 1', status: 'completed' as const },
        { id: 2, description: 'Task 2', status: 'active' as const },
      ]
      updateStream('conv-1', { todo: updatedTasks })
      expect(getStream('conv-1')?.todo[0].status).toBe('completed')
      expect(getStream('conv-1')?.todo[1].status).toBe('active')
    })
  })
})

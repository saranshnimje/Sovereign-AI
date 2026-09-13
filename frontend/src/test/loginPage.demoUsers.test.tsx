/**
 * Tests for the dynamic Demo Credentials section on the login page.
 *
 * Verifies that the demo users list is fetched from the backend and
 * rendered correctly, including loading, error, empty, and populated states.
 */
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import LoginPage from '../pages/LoginPage'
import { useAuthStore } from '../stores/authStore'

// ---------------------------------------------------------------- mocks ----

const authApiMock = vi.hoisted(() => ({
  login: vi.fn(),
  me: vi.fn(),
  logout: vi.fn(),
  register: vi.fn(),
  setupStatus: vi.fn(),
  listUsers: vi.fn(),
  updateUser: vi.fn(),
  getDemoUsers: vi.fn(),
}))

vi.mock('../api/auth', () => ({
  authApi: authApiMock,
}))

vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
  // Provide Navigate stub — useNavigate is mocked at module level
}))

vi.mock('../components/ui/SovereignLogo', () => ({
  default: () => <div data-testid="logo" />,
}))

// ---------------------------------------------------------------- helpers ----

function renderLogin() {
  // Reset store so we don't redirect via accessToken
  useAuthStore.setState({ accessToken: null, user: null })
  return render(<LoginPage />)
}

// ---------------------------------------------------------------- tests ----

describe('LoginPage — Demo Credentials Section', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Default: setup not required, so demo section renders
    authApiMock.setupStatus.mockResolvedValue({ setup_required: false })
  })

  it('shows a loading spinner while fetching demo users', async () => {
    // Make getDemoUsers hang
    authApiMock.getDemoUsers.mockReturnValue(new Promise(() => {}))
    renderLogin()

    await waitFor(() => {
      expect(screen.getByText(/Loading demo accounts/)).toBeTruthy()
    })
  })

  it('shows an error message when the fetch fails', async () => {
    authApiMock.getDemoUsers.mockRejectedValue(new Error('Network error'))
    renderLogin()

    await waitFor(() => {
      expect(screen.getByText('Could not load demo accounts')).toBeTruthy()
    })
  })

  it('shows "No demo accounts available" when the list is empty', async () => {
    authApiMock.getDemoUsers.mockResolvedValue([])
    renderLogin()

    await waitFor(() => {
      expect(screen.getByText('No demo accounts available.')).toBeTruthy()
    })
  })

  it('renders a table with exactly one row — the Admin demo account', async () => {
    authApiMock.getDemoUsers.mockResolvedValue([
      { email: 'admin@admin.com', role: 'admin', has_demo_password: true, demo_password: 'admin12345678' },
    ])
    renderLogin()

    await waitFor(() => {
      expect(screen.getByText('admin@admin.com')).toBeTruthy()
    })
    // Only the single admin row — no other users
    expect(screen.queryByText('e2e_analyst@test.com')).toBeNull()
    expect(screen.queryByText('test@test.com')).toBeNull()

    // Table headers — use getAllByText since "Password" also appears in the form label
    expect(screen.getAllByText('Email').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Password').length).toBeGreaterThanOrEqual(2) // label + th
    expect(screen.getAllByText('Role').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Action').length).toBeGreaterThanOrEqual(1)
  })

  it('shows the Admin password when has_demo_password is true', async () => {
    authApiMock.getDemoUsers.mockResolvedValue([
      { email: 'admin@admin.com', role: 'admin', has_demo_password: true, demo_password: 'admin12345678' },
    ])
    renderLogin()

    await waitFor(() => {
      expect(screen.getByText('admin12345678')).toBeTruthy()
    })
  })

  it('does not show "Password unavailable" when the Admin password exists', async () => {
    authApiMock.getDemoUsers.mockResolvedValue([
      { email: 'admin@admin.com', role: 'admin', has_demo_password: true, demo_password: 'admin12345678' },
    ])
    renderLogin()

    await waitFor(() => {
      expect(screen.getByText('admin12345678')).toBeTruthy()
    })
    expect(screen.queryByText('Password unavailable')).toBeNull()
  })

  it('shows "Password unavailable" only when no configured demo password exists', async () => {
    authApiMock.getDemoUsers.mockResolvedValue([
      { email: 'admin@admin.com', role: 'admin', has_demo_password: false, demo_password: null },
    ])
    renderLogin()

    await waitFor(() => {
      expect(screen.getByText('Password unavailable')).toBeTruthy()
    })
  })

  it('shows "N/A" button only when no demo password exists', async () => {
    authApiMock.getDemoUsers.mockResolvedValue([
      { email: 'admin@admin.com', role: 'admin', has_demo_password: false, demo_password: null },
    ])
    renderLogin()

    await waitFor(() => {
      expect(screen.getByText('N/A')).toBeTruthy()
    })
  })

  it('"Use Credentials" fills the Admin email and password fields and clears login error', async () => {
    authApiMock.getDemoUsers.mockResolvedValue([
      { email: 'admin@admin.com', role: 'admin', has_demo_password: true, demo_password: 'admin12345678' },
    ])
    renderLogin()

    // The helper description also contains the span text "Use Credentials",
    // so query the button by role for an unambiguous, single match.
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Use Credentials' })).toBeTruthy()
    })

    // Click Use Credentials
    fireEvent.click(screen.getByRole('button', { name: 'Use Credentials' }))

    // The form inputs are now filled with the admin credentials
    const emailInput = screen.getByLabelText('Email address') as HTMLInputElement
    const passwordInput = screen.getByLabelText('Password') as HTMLInputElement
    expect(emailInput.value).toBe('admin@admin.com')
    expect(passwordInput.value).toBe('admin12345678')
  })

  it('does not render the demo section in setup mode', async () => {
    authApiMock.setupStatus.mockResolvedValue({ setup_required: true })
    renderLogin()

    await waitFor(() => {
      expect(screen.getByText('Create Admin Account')).toBeTruthy()
    })

    // getDemoUsers should NOT be called in setup mode
    expect(authApiMock.getDemoUsers).not.toHaveBeenCalled()
    expect(screen.queryByText('Demo Credentials')).toBeNull()
  })

  it('displays a single Admin role badge, never analyst/viewer', async () => {
    authApiMock.getDemoUsers.mockResolvedValue([
      { email: 'admin@admin.com', role: 'admin', has_demo_password: true, demo_password: 'admin12345678' },
    ])
    renderLogin()

    await waitFor(() => {
      expect(screen.getByText('admin')).toBeTruthy()
    })
    expect(screen.queryByText('analyst')).toBeNull()
    expect(screen.queryByText('viewer')).toBeNull()
  })
})

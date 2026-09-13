import api from './client'

export interface LoginRequest { email: string; password: string }
export interface RegisterRequest { email: string; username: string; password: string }
export interface TokenResponse { access_token: string; token_type: string; expires_in: number }
export interface UserResponse {
  id: string; email: string; username: string; role: string
  is_active: boolean; must_change_password: boolean
  last_login: string | null; created_at: string
}

export interface DemoUser {
  email: string
  role: string
  has_demo_password: boolean
  demo_password: string | null
}

export const authApi = {
  login: (data: LoginRequest) =>
    api.post<TokenResponse>('/auth/login', data).then((r) => r.data),

  register: (data: RegisterRequest) =>
    api.post<UserResponse>('/auth/register', data).then((r) => r.data),

  logout: () => api.post('/auth/logout'),

  me: () => api.get<UserResponse>('/auth/me').then((r) => r.data),

  setupStatus: () =>
    api.get<{ setup_required: boolean }>('/auth/setup-status').then((r) => r.data),

  listUsers: () => api.get<UserResponse[]>('/auth/users').then((r) => r.data),

  updateUser: (id: string, data: Partial<{ role: string; is_active: boolean }>) =>
    api.put<UserResponse>(`/auth/users/${id}`, data).then((r) => r.data),

  getDemoUsers: () => api.get<DemoUser[]>('/auth/demo-users').then((r) => r.data),
}

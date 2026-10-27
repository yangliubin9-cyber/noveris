const API = '/api'
let csrfToken: string | null = null

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

function getErrorMessage(payload: unknown, fallback: string): string {
  const localized: Record<string, string> = {
    'Invalid email or password': '邮箱或密码错误',
    'Registration is disabled': '平台已关闭自主注册',
    'Email is already registered': '该邮箱已注册',
    'Login required': '请先登录',
    'Session expired': '登录会话已过期，请重新登录',
    'Operator role required': '当前账户没有操作权限',
    'Administrator role required': '此操作需要管理员权限',
    'CSRF token is missing or invalid': '安全令牌已失效，请刷新页面重试',
    'Current password is incorrect': '当前密码不正确',
    'This SSO account has no local password': '企业 SSO 账户没有本地密码',
    'Reset token is invalid or expired': '重置令牌无效或已过期',
    'Password reset email is not configured': '邮件服务未配置，暂时无法重置密码',
    'Password reset email could not be sent': '重置邮件发送失败，请稍后重试',
    'Upstream host must match the selected node address': '上游地址的主机必须与所选节点地址一致',
  }
  if (payload && typeof payload === 'object' && 'detail' in payload) {
    const detail = (payload as { detail: unknown }).detail
    if (typeof detail === 'string') return localized[detail] || detail
    if (Array.isArray(detail)) return detail.map((entry) => {
      if (entry && typeof entry === 'object' && 'msg' in entry) return String(entry.msg)
      return String(entry)
    }).join('；')
  }
  return fallback
}

async function getCsrf(): Promise<string> {
  if (csrfToken) return csrfToken
  const response = await fetch(`${API}/auth/csrf`, { credentials: 'include' })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) throw new ApiError(getErrorMessage(payload, '无法获取安全令牌'), response.status)
  csrfToken = String(payload.csrf_token || '')
  return csrfToken
}

export function clearCsrf() { csrfToken = null }

async function request<T>(path: string, method = 'GET', body?: unknown, publicWrite = false): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (!['GET', 'HEAD'].includes(method) && !publicWrite) headers['X-CSRF-Token'] = await getCsrf()
  let response: Response
  try {
    response = await fetch(`${API}${path}`, {
      method, credentials: 'include', headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError('无法连接到服务，请检查后端是否运行', 0)
  }
  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    if (response.status === 403) clearCsrf()
    throw new ApiError(getErrorMessage(payload, `请求失败（HTTP ${response.status}）`), response.status)
  }
  return payload as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown, publicWrite = false) => request<T>(path, 'POST', body, publicWrite),
  put: <T>(path: string, body?: unknown) => request<T>(path, 'PUT', body),
  delete: <T>(path: string) => request<T>(path, 'DELETE'),
}

export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : '操作失败，请稍后重试'
}

import { createContext, useContext, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { ArrowLeft, ArrowRight, KeyRound, LoaderCircle, LockKeyhole, ShieldCheck } from 'lucide-react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { api, clearCsrf, errorText } from './api'
import type { Settings, SsoConfig, User } from './types'
import { Field, FormError, SubmitButton, useToast } from './ui'

type AuthState = { user: User | null; loading: boolean; refresh: () => Promise<void>; logout: () => Promise<void> }
const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const refresh = async () => {
    try { setUser(await api.get<User>('/auth/me')) }
    catch { setUser(null) }
    finally { setLoading(false) }
  }
  useEffect(() => { void refresh() }, [])
  const logout = async () => {
    await api.post('/auth/logout')
    clearCsrf(); setUser(null)
  }
  return <AuthContext.Provider value={{ user, loading, refresh, logout }}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const state = useContext(AuthContext)
  if (!state) throw new Error('AuthProvider missing')
  return state
}

export function Protected({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) return <div className="auth-loading"><div className="brand-mark">N</div><LoaderCircle className="spin" size={25} /><span>正在连接控制台</span></div>
  if (!user) return <Navigate to="/login" replace />
  return <>{children}</>
}

type AuthMode = 'login' | 'register' | 'forgot' | 'reset'
const content: Record<AuthMode, { eyebrow: string; title: string; subtitle: string }> = {
  login: { eyebrow: 'SECURE ACCESS / 01', title: '欢迎回到控制台', subtitle: '统一管理模型、节点与调用入口。' },
  register: { eyebrow: 'CREATE ACCOUNT / 02', title: '创建平台账户', subtitle: '建立工作身份，开始接入 AI 能力。' },
  forgot: { eyebrow: 'RECOVER ACCESS / 03', title: '找回访问权限', subtitle: '输入邮箱以获取密码重置指引。' },
  reset: { eyebrow: 'RESET PASSWORD / 04', title: '设置新密码', subtitle: '完成验证后重新进入控制台。' },
}

export function AuthPage({ mode }: { mode: AuthMode }) {
  const { user, refresh } = useAuth()
  const navigate = useNavigate()
  const notify = useToast()
  const [params] = useSearchParams()
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [token, setToken] = useState(params.get('token') || '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState('')
  const [demoToken, setDemoToken] = useState('')
  const [sso, setSso] = useState<SsoConfig | null>(null)
  const [settings, setSettings] = useState<Settings | null>(null)

  useEffect(() => {
    void api.get<SsoConfig>('/sso/config').then(setSso).catch(() => setSso(null))
    void api.get<Settings>('/settings/public').then(setSettings).catch(() => setSettings(null))
  }, [])
  useEffect(() => { document.title = `${content[mode].title} · ${settings?.site_name || 'Noveris AI'}` }, [mode, settings?.site_name])

  if (user) return <Navigate to="/" replace />
  const registrationClosed = mode === 'register' && settings?.allow_registration === false
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError(''); setDone('')
    if (mode === 'register' && password !== confirm) { setError('两次输入的密码不一致'); return }
    if (mode === 'reset' && password !== confirm) { setError('两次输入的密码不一致'); return }
    if ((mode === 'register' || mode === 'reset') && password.length < 8) { setError('密码至少需要 8 个字符'); return }
    setBusy(true)
    try {
      if (mode === 'login') {
        await api.post('/auth/login', { email, password }, true)
        clearCsrf(); await refresh(); navigate('/', { replace: true }); notify('已安全登录')
      } else if (mode === 'register') {
        await api.post('/auth/register', { email, password, name }, true)
        clearCsrf(); await refresh(); navigate('/', { replace: true }); notify('账户已创建')
      } else if (mode === 'forgot') {
        const result = await api.post<{ message?: string; reset_token?: string }>('/auth/forgot-password', { email }, true)
        setDemoToken(result.reset_token || '')
        setDone('如果该邮箱已注册，重置指引将很快送达。')
      } else {
        await api.post('/auth/reset-password', { token, password }, true)
        setDone('密码已更新，现在可以登录。')
      }
    } catch (err) { setError(errorText(err)) }
    finally { setBusy(false) }
  }
  const data = content[mode]
  return <div className="auth-page">
    <header className="auth-header">
      <Link to="/login" className="auth-brand"><span className="brand-mark">N</span><span>NOVERIS<span className="brand-dot">.</span>AI</span></Link>
      <span className="auth-header-note"><ShieldCheck size={16} />企业模型控制台</span>
    </header>
    <div className="auth-content">
      <div className="auth-card">
        <div className="auth-site-label"><span>当前站点</span><strong>{settings?.site_name || 'Noveris AI'}</strong></div>
        <div className="eyebrow">{data.eyebrow}</div>
        <h1>{data.title}</h1><p className="auth-subtitle">{data.subtitle}</p>
        {registrationClosed ? <div className="form-error">平台已关闭自主注册，请联系管理员。</div> :
          <form onSubmit={submit} className="auth-form">
            {mode === 'register' && <Field label="姓名" required><input value={name} onChange={(event) => setName(event.target.value)} placeholder="请输入姓名" required autoComplete="name" /></Field>}
            {mode !== 'reset' && <Field label="工作邮箱" required><input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="name@company.com" required autoComplete="email" /></Field>}
            {mode === 'reset' && <Field label="重置令牌" required><input value={token} onChange={(event) => setToken(event.target.value)} placeholder="输入邮件中的令牌" required /></Field>}
            {mode !== 'forgot' && <Field label={mode === 'reset' ? '新密码' : '密码'} required><input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="至少 8 个字符" required autoComplete={mode === 'login' ? 'current-password' : 'new-password'} /></Field>}
            {(mode === 'register' || mode === 'reset') && <Field label="确认密码" required><input type="password" value={confirm} onChange={(event) => setConfirm(event.target.value)} placeholder="再次输入密码" required autoComplete="new-password" /></Field>}
            {mode === 'login' && <div className="auth-secondary"><Link to="/forgot-password">忘记密码？</Link></div>}
            <FormError error={error} />
            {done && <div className="form-success"><ShieldCheck size={17} />{done}</div>}
            {demoToken && <div className="demo-token"><span>演示环境重置令牌</span><code>{demoToken}</code><Link to={`/reset-password?token=${encodeURIComponent(demoToken)}`}>使用此令牌重置 <ArrowRight size={14} /></Link></div>}
            <SubmitButton busy={busy} icon={<ArrowRight size={17} />}>{mode === 'login' ? '登录控制台' : mode === 'register' ? '创建账户' : mode === 'forgot' ? '发送重置指引' : '确认新密码'}</SubmitButton>
          </form>}
        {mode === 'login' && sso?.enabled && <div className="sso-section"><div className="divider"><span>或使用企业身份</span></div><a className="button button-outline sso-button" href="/api/auth/oidc/start"><KeyRound size={17} />通过 {sso.provider_name || '企业 SSO'} 登录</a></div>}
        <div className="auth-footer">
          {mode === 'login' ? <span>还没有账户？ <Link to="/register">申请注册</Link></span> :
            <Link to="/login"><ArrowLeft size={15} />返回登录</Link>}
        </div>
      </div>
      <div className="auth-security"><LockKeyhole size={15} />加密连接 · 安全会话 · 权限隔离</div>
    </div>
    <footer className="auth-page-footer"><span>© 2026 NOVERIS.AI</span><span>MODEL CONTROL PLANE / MVP</span></footer>
  </div>
}

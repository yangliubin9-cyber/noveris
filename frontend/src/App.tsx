import { useEffect, useState } from 'react'
import {
  Activity, ArrowUpRight, Boxes, ChevronDown, CircleHelp, Command, FlaskConical,
  LayoutDashboard, LogOut, Menu, Network, RadioTower, Settings2,
  ShieldCheck, Store, UserCircle2, UsersRound, X,
} from 'lucide-react'
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { api } from './api'
import { AuthPage, AuthProvider, Protected, useAuth } from './auth'
import type { Settings } from './types'
import { ToastProvider, useToast } from './ui'
import { DashboardPage } from './pages/Dashboard'
import { NodesPage, MarketplacePage, DeploymentsPage } from './pages/Resources'
import { ForwardingPage, TestPage } from './pages/Forwarding'
import { UsersPage, SettingsPage, ProfilePage } from './pages/System'

const sections = [
  { label: '总览', items: [{ to: '/', label: '控制塔', icon: LayoutDashboard }] },
  { label: '资源与模型', items: [
    { to: '/nodes', label: '节点管理', icon: Network },
    { to: '/marketplace', label: '模型市场', icon: Store },
    { to: '/deployments', label: '模型部署', icon: Boxes },
  ] },
  { label: '访问与调用', items: [
    { to: '/forwarding', label: '模型转发', icon: RadioTower },
    { to: '/test', label: '模型测试', icon: FlaskConical },
  ] },
  { label: '平台管理', items: [
    { to: '/users', label: '权限管理', icon: UsersRound },
    { to: '/settings', label: '设置', icon: Settings2 },
  ] },
]

const titles: Record<string, string> = {
  '/': '控制塔', '/nodes': '节点管理', '/marketplace': '模型市场',
  '/deployments': '模型部署', '/forwarding': '模型转发',
  '/test': '模型测试', '/users': '权限管理', '/settings': '设置', '/profile': '个人中心',
}

function Shell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const notify = useToast()
  const [menuOpen, setMenuOpen] = useState(false)
  const [profileMenu, setProfileMenu] = useState(false)
  const [health, setHealth] = useState<'ok' | 'error' | 'loading'>('loading')
  const [siteName, setSiteName] = useState('Noveris AI')
  useEffect(() => { setMenuOpen(false); setProfileMenu(false) }, [location.pathname])
  useEffect(() => {
    void api.get<Settings>('/settings/public').then((value) => setSiteName(value.site_name)).catch(() => undefined)
    const onSiteName = (event: Event) => setSiteName((event as CustomEvent<string>).detail)
    window.addEventListener('noveris:site-name', onSiteName)
    return () => window.removeEventListener('noveris:site-name', onSiteName)
  }, [])
  useEffect(() => { document.title = `${titles[location.pathname] || '控制台'} · ${siteName}` }, [location.pathname, siteName])
  useEffect(() => {
    const check = () => { void api.get('/health').then(() => setHealth('ok')).catch(() => setHealth('error')) }
    check()
    const timer = window.setInterval(check, 30000)
    return () => window.clearInterval(timer)
  }, [])
  const signOut = async () => {
    try { await logout(); navigate('/login', { replace: true }); notify('已退出登录') }
    catch { notify('退出请求失败，请重试', 'error') }
  }
  return <div className="app-shell">
    {menuOpen && <button className="mobile-scrim" aria-label="关闭导航" onClick={() => setMenuOpen(false)} />}
    <aside className={`sidebar ${menuOpen ? 'sidebar-open' : ''}`}>
      <div className="sidebar-top">
        <Link to="/" className="brand"><div className="brand-mark">N</div><div className="brand-word"><strong>NOVERIS<span>.</span>AI</strong><small>MODEL CONTROL PLANE</small></div></Link>
        <button className="icon-button mobile-close" onClick={() => setMenuOpen(false)} aria-label="关闭导航"><X size={19} /></button>
      </div>
      <div className="workspace-chip"><div className="workspace-symbol"><Command size={17} /></div><div><small>当前工作区</small><strong>默认空间</strong></div><ChevronDown size={15} /></div>
      <nav className="side-nav" aria-label="主导航">
        {sections.map((section) => <div className="nav-section" key={section.label}>
          <div className="nav-label">{section.label}</div>
          {section.items.filter((item) => user?.role === 'admin' || !['/users', '/settings'].includes(item.to)).filter((item) => user?.role !== 'viewer' || item.to !== '/test').map((item) => {
            const Icon = item.icon
            return <NavLink key={item.to} to={item.to} end={item.to === '/'} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}><Icon size={18} strokeWidth={1.8} /><span>{item.label}</span><ArrowUpRight className="nav-arrow" size={14} /></NavLink>
          })}
        </div>)}
      </nav>
      <div className="sidebar-bottom">
        <div className="sidebar-notice"><div className="sidebar-notice-icon"><ShieldCheck size={18} /></div><strong>私有化 AI 控制台</strong><p>统一接入、治理与验证模型服务。</p></div>
        <div className="sidebar-version"><span className="online-dot" />NOVERIS MVP <span>V 0.1</span></div>
      </div>
    </aside>
    <div className="main-column">
      <header className="topbar">
        <div className="topbar-left"><button className="icon-button mobile-menu" onClick={() => setMenuOpen(true)} aria-label="打开导航"><Menu size={21} /></button><span className="breadcrumb-root">{siteName} / 工作台</span><span className="breadcrumb-separator">/</span><strong>{titles[location.pathname] || '控制台'}</strong></div>
        <div className="topbar-right">
          <div className={`health-pill health-${health}`}><span className="health-pulse" />{health === 'ok' ? '系统在线' : health === 'loading' ? '连接中' : '服务异常'}</div>
          <Link className="topbar-help" to="/settings" title="平台设置"><CircleHelp size={18} /></Link>
          <div className="profile-wrap"><button className="profile-trigger" aria-expanded={profileMenu} onClick={() => setProfileMenu(!profileMenu)}><div className="avatar">{user?.name?.slice(0, 1)?.toUpperCase() || 'U'}</div><span>{user?.name || user?.email}</span><ChevronDown size={14} /></button>
            {profileMenu && <div className="profile-menu"><div className="profile-menu-head"><strong>{user?.name || '用户'}</strong><span>{user?.email}</span></div><Link to="/profile"><UserCircle2 size={16} />个人中心</Link><button onClick={() => void signOut()}><LogOut size={16} />退出登录</button></div>}
          </div>
        </div>
      </header>
      <main className="main-content">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/nodes" element={<NodesPage />} />
          <Route path="/marketplace" element={<MarketplacePage />} />
          <Route path="/deployments" element={<DeploymentsPage />} />
          <Route path="/forwarding" element={<ForwardingPage />} />
          <Route path="/test" element={user?.role !== 'viewer' ? <TestPage /> : <Navigate to="/" replace />} />
          <Route path="/users" element={user?.role === 'admin' ? <UsersPage /> : <Navigate to="/" replace />} />
          <Route path="/settings" element={user?.role === 'admin' ? <SettingsPage /> : <Navigate to="/" replace />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
      <footer className="content-footer"><span>© 2026 Noveris AI</span><span><Activity size={13} /> 控制平面运行中</span></footer>
    </div>
  </div>
}

export default function App() {
  return <ToastProvider><AuthProvider><Routes>
    <Route path="/login" element={<AuthPage mode="login" />} />
    <Route path="/register" element={<AuthPage mode="register" />} />
    <Route path="/forgot-password" element={<AuthPage mode="forgot" />} />
    <Route path="/reset-password" element={<AuthPage mode="reset" />} />
    <Route path="/*" element={<Protected><Shell /></Protected>} />
  </Routes></AuthProvider></ToastProvider>
}

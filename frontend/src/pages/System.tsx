import { useEffect, useState, type FormEvent } from 'react'
import { KeyRound, LockKeyhole, Mail, RefreshCw, Settings2, Shield, ShieldCheck, UserCircle2, UsersRound } from 'lucide-react'
import { api, clearCsrf, errorText } from '../api'
import { useAuth } from '../auth'
import type { Role, Settings, SsoConfig, User } from '../types'
import { Busy, Empty, Failure, Field, FormError, PageHeader, Panel, Select, StatusBadge, SubmitButton, useCollection, useMutation, useToast } from '../ui'

const roleLabel: Record<Role, string> = { admin: '管理员', operator: '操作员', viewer: '只读成员' }
const roleDescription: Record<Role, string> = {
  admin: '管理成员、平台设置及全部资源',
  operator: '管理节点、模型、部署和转发配置',
  viewer: '浏览资源与运行状态',
}

export function UsersPage() {
  const { user } = useAuth()
  const notify = useToast()
  const { data, loading, error, reload } = useCollection<User>('/users')
  const [updating, setUpdating] = useState<number | null>(null)
  const changeRole = async (target: User, role: Role) => {
    if (target.role === role) return
    setUpdating(target.id)
    try {
      await api.put<User>(`/users/${target.id}/role`, { role })
      notify(`${target.name || target.email} 的角色已更新`)
      void reload()
    } catch (err) { notify(errorText(err), 'error') }
    finally { setUpdating(null) }
  }
  return <>
    <PageHeader eyebrow="IDENTITY / 06" title="权限管理" description="按角色分配平台访问权限，控制资源的查看与变更。" action={<button className="button button-outline" onClick={() => void reload()}><RefreshCw size={16} />刷新</button>} />
    <div className="role-grid">{(['admin', 'operator', 'viewer'] as const).map((role, index) => <div className="role-card" key={role}><div className="role-top"><span>0{index + 1} / ROLE</span><Shield size={20} /></div><h3>{roleLabel[role]}</h3><p>{roleDescription[role]}</p><strong>{data.filter((member) => member.role === role).length} <small>位成员</small></strong></div>)}</div>
    <Panel title={`平台成员 · ${data.length}`} aside={<span className="section-tag">ROLE BASED ACCESS</span>}>
      {loading ? <Busy /> : error ? <Failure error={error} retry={() => void reload()} /> : data.length === 0 ?
        <Empty icon={<UsersRound size={26} />} title="暂无平台成员" description="注册的用户会出现在这里。" /> :
        <div className="table-scroll"><table className="data-table"><thead><tr><th>成员</th><th>邮箱</th><th>当前角色</th><th className="action-cell">权限分配</th></tr></thead><tbody>{data.map((member) => <tr key={member.id}><td><div className="table-name"><span className="member-avatar">{member.name?.slice(0, 1)?.toUpperCase() || 'U'}</span><div><strong>{member.name || '未设置姓名'}</strong><small>{member.id === user?.id ? '当前账户' : '平台成员'}</small></div></div></td><td className="muted">{member.email}</td><td><span className={`role-pill role-${member.role}`}>{roleLabel[member.role]}</span></td><td className="action-cell"><Select value={member.role} onChange={(event) => void changeRole(member, event.target.value as Role)} disabled={updating === member.id || member.id === user?.id} aria-label={`设置${member.name || member.email}的角色`}><option value="admin">管理员</option><option value="operator">操作员</option><option value="viewer">只读成员</option></Select></td></tr>)}</tbody></table></div>}
    </Panel>
    <div className="page-note"><ShieldCheck size={16} />当前账户不可在此修改自己的角色，防止意外失去管理权限。</div>
  </>
}

export function SettingsPage() {
  const notify = useToast()
  const [settings, setSettings] = useState<Settings | null>(null)
  const [sso, setSso] = useState<SsoConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const mutation = useMutation()
  const load = async () => {
    setLoading(true); setError('')
    try {
      const [value, provider] = await Promise.all([api.get<Settings>('/settings'), api.get<SsoConfig>('/sso/config')])
      setSettings(value); setSso(provider)
    } catch (err) { setError(errorText(err)) }
    finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [])
  const save = (event: FormEvent) => {
    event.preventDefault()
    if (!settings) return
    void mutation.run(() => api.put<Settings>('/settings', settings), () => {
      window.dispatchEvent(new CustomEvent('noveris:site-name', { detail: settings.site_name }))
      notify('平台设置已保存')
    })
  }
  return <>
    <PageHeader eyebrow="PLATFORM / 07" title="设置" description="调整控制台名称、注册策略，查看单点登录状态。" />
    {loading ? <Busy /> : error ? <Failure error={error} retry={() => void load()} /> : settings && <div className="settings-layout">
      <Panel title="基础配置" aside={<Settings2 size={20} />}><form className="settings-form" onSubmit={save}><Field label="平台名称" hint="显示在平台页面与登录入口。" required><input value={settings.site_name} onChange={(e) => setSettings({ ...settings, site_name: e.target.value })} required /></Field><div className="setting-switch-row"><div><strong>开放自主注册</strong><span>开启后，访客可从登录页创建账户。</span></div><label className="switch" aria-label="开放自主注册"><input type="checkbox" checked={settings.allow_registration} onChange={(e) => setSettings({ ...settings, allow_registration: e.target.checked })} /><span /></label></div><FormError error={mutation.error} /><SubmitButton busy={mutation.busy}>保存设置</SubmitButton></form></Panel>
      <Panel title="企业单点登录" aside={<KeyRound size={20} />}><div className={`sso-status ${sso?.enabled ? 'is-enabled' : ''}`}><div className="sso-status-icon"><ShieldCheck size={25} /></div><div><strong>{sso?.enabled ? 'SSO 已启用' : 'SSO 未启用'}</strong><p>{sso?.enabled ? `当前身份提供方：${sso.provider_name || '企业身份系统'}` : '配置身份提供方后，登录页会显示企业 SSO 入口。'}</p></div><StatusBadge status={sso?.enabled ? 'enabled' : 'disabled'} /></div><div className="settings-facts"><div><span>登录协议</span><strong>OpenID Connect</strong></div><div><span>登录入口</span><strong>{sso?.enabled ? '已在登录页展示' : '配置后自动开放'}</strong></div><div><span>账户关联</span><strong>按企业身份绑定</strong></div></div></Panel>
    </div>}
  </>
}

export function ProfilePage() {
  const { user, refresh } = useAuth()
  const notify = useToast()
  const [name, setName] = useState(user?.name || '')
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const profileMutation = useMutation()
  const passwordMutation = useMutation()
  useEffect(() => { setName(user?.name || '') }, [user?.name])
  const saveProfile = (event: FormEvent) => {
    event.preventDefault()
    void profileMutation.run(() => api.put<User>('/auth/profile', { name }), () => { void refresh(); notify('个人资料已更新') })
  }
  const savePassword = (event: FormEvent) => {
    event.preventDefault()
    passwordMutation.setError('')
    if (newPassword.length < 8) { passwordMutation.setError('新密码至少需要 8 个字符'); return }
    if (newPassword !== confirmPassword) { passwordMutation.setError('两次输入的新密码不一致'); return }
    void passwordMutation.run(() => api.put('/auth/password', { current_password: currentPassword, new_password: newPassword }), () => {
      setCurrentPassword(''); setNewPassword(''); setConfirmPassword('')
      clearCsrf()
      notify('密码已更新，请重新登录')
      void refresh()
    })
  }
  return <>
    <PageHeader eyebrow="ACCOUNT / 08" title="个人中心" description="维护个人资料与登录安全。" />
    <div className="profile-hero"><div className="profile-avatar">{user?.name?.slice(0, 1)?.toUpperCase() || 'U'}</div><div><span className="eyebrow">MEMBER PROFILE</span><h2>{user?.name || '平台成员'}</h2><p>{user?.email}</p></div><span className={`role-pill role-${user?.role || 'viewer'}`}>{roleLabel[user?.role || 'viewer']}</span></div>
    <div className="settings-layout">
      <Panel title="个人资料" aside={<UserCircle2 size={20} />}><form className="settings-form" onSubmit={saveProfile}><Field label="姓名" required><input value={name} onChange={(e) => setName(e.target.value)} required autoComplete="name" /></Field><Field label="邮箱"><div className="readonly-field"><Mail size={17} />{user?.email}</div></Field><FormError error={profileMutation.error} /><SubmitButton busy={profileMutation.busy}>保存资料</SubmitButton></form></Panel>
      <Panel title="账户安全" aside={<LockKeyhole size={20} />}><form className="settings-form" onSubmit={savePassword}><Field label="当前密码" required><input type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} required autoComplete="current-password" /></Field><Field label="新密码" hint="至少 8 个字符。" required><input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} required autoComplete="new-password" /></Field><Field label="确认新密码" required><input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} required autoComplete="new-password" /></Field><FormError error={passwordMutation.error} /><SubmitButton busy={passwordMutation.busy}>更新密码</SubmitButton></form></Panel>
    </div>
  </>
}

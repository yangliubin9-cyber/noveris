import { useState, type FormEvent } from 'react'
import { ArrowRight, Check, Copy, FlaskConical, KeyRound, Pencil, Plus, RadioTower, RefreshCw, Send, ShieldCheck, Trash2, WandSparkles } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import type { ApiKey, Deployment, Route } from '../types'
import { Busy, ConfirmDialog, dateText, Dialog, Empty, Failure, Field, FormError, PageHeader, Panel, Select, StatusBadge, SubmitButton, useCollection, useMutation, useToast } from '../ui'

type RouteForm = { name: string; model_alias: string; deployment_id: string; status: string }
const blankRoute: RouteForm = { name: '', model_alias: '', deployment_id: '', status: 'active' }

export function ForwardingPage() {
  const { user } = useAuth()
  const notify = useToast()
  const routes = useCollection<Route>('/routes')
  const deployments = useCollection<Deployment>('/deployments')
  const keys = useCollection<ApiKey>('/api-keys')
  const [activeTab, setActiveTab] = useState<'routes' | 'keys'>('routes')
  const [routeOpen, setRouteOpen] = useState(false)
  const [keyOpen, setKeyOpen] = useState(false)
  const [editing, setEditing] = useState<Route | null>(null)
  const [form, setForm] = useState<RouteForm>(blankRoute)
  const [keyName, setKeyName] = useState('')
  const [generatedSecret, setGeneratedSecret] = useState('')
  const [copied, setCopied] = useState(false)
  const [deletingRoute, setDeletingRoute] = useState<Route | null>(null)
  const [deletingKey, setDeletingKey] = useState<ApiKey | null>(null)
  const mutation = useMutation()
  const editable = user?.role === 'admin' || user?.role === 'operator'
  const deploymentName = (id: number) => deployments.data.find((item) => item.id === id)?.name || '未知部署'
  const openCreate = () => { setEditing(null); setForm(blankRoute); mutation.setError(''); setRouteOpen(true) }
  const openEdit = (item: Route) => { setEditing(item); setForm({ name: item.name, model_alias: item.model_alias, deployment_id: String(item.deployment_id), status: item.status }); mutation.setError(''); setRouteOpen(true) }
  const saveRoute = (event: FormEvent) => {
    event.preventDefault()
    void mutation.run(
      () => editing ? api.put<Route>(`/routes/${editing.id}`, form) : api.post<Route>('/routes', form),
      () => { setRouteOpen(false); notify(editing ? '路由已更新' : '转发路由已创建'); void routes.reload() },
    )
  }
  const saveKey = (event: FormEvent) => {
    event.preventDefault()
    void mutation.run(async () => {
      const created = await api.post<ApiKey>('/api-keys', { name: keyName })
      if (!created.secret) throw new Error('密钥已创建，但服务没有返回完整密钥。请撤销后重试。')
      setGeneratedSecret(created.secret)
    }, () => { notify('API Key 已创建，请立即保存'); void keys.reload() })
  }
  const copySecret = async () => {
    try { await navigator.clipboard.writeText(generatedSecret); setCopied(true); notify('密钥已复制'); window.setTimeout(() => setCopied(false), 2000) }
    catch { notify('复制失败，请手动选择密钥', 'error') }
  }
  const removeRoute = async () => {
    if (!deletingRoute) return
    const item = deletingRoute
    await mutation.run(() => api.delete(`/routes/${item.id}`), () => { setDeletingRoute(null); notify('路由已删除'); void routes.reload() })
  }
  const removeKey = async () => {
    if (!deletingKey) return
    const item = deletingKey
    await mutation.run(() => api.delete(`/api-keys/${item.id}`), () => { setDeletingKey(null); notify('API Key 已撤销'); void keys.reload() })
  }
  return <>
    <PageHeader eyebrow="API GATEWAY / 04" title="模型转发" description="为模型服务配置统一别名，创建外部调用凭证。"
      action={editable && <button className="button button-primary" onClick={activeTab === 'routes' ? openCreate : () => { setKeyName(''); setGeneratedSecret(''); mutation.setError(''); setKeyOpen(true) }}><Plus size={17} />{activeTab === 'routes' ? '新建路由' : '创建 API Key'}</button>} />
    <div className="gateway-strip"><div className="gateway-strip-icon"><RadioTower size={24} /></div><div><span>统一接入地址</span><code>{window.location.origin}/v1/chat/completions</code></div><div className="gateway-strip-meta">OPENAI COMPATIBLE <ShieldCheck size={16} /></div></div>
    <div className="tabs"><button className={activeTab === 'routes' ? 'selected' : ''} onClick={() => setActiveTab('routes')}><RadioTower size={17} />路由管理 <span>{routes.data.length}</span></button><button className={activeTab === 'keys' ? 'selected' : ''} onClick={() => setActiveTab('keys')}><KeyRound size={17} />API Key <span>{keys.data.length}</span></button></div>
    {activeTab === 'routes' ?
      <Panel title="模型路由" aside={<button className="icon-button" onClick={() => void routes.reload()} title="刷新"><RefreshCw size={17} /></button>}>
        {routes.loading ? <Busy /> : routes.error ? <Failure error={routes.error} retry={() => void routes.reload()} /> : routes.data.length === 0 ?
          <Empty icon={<RadioTower size={26} />} title="还没有转发路由" description="为已登记的部署设置模型别名，即可通过统一 Base URL 访问。" action={editable && <button className="button button-outline" onClick={openCreate}><Plus size={16} />创建路由</button>} /> :
          <div className="table-scroll"><table className="data-table"><thead><tr><th>路由名称</th><th>模型别名</th><th>目标部署</th><th>状态</th><th className="action-cell">操作</th></tr></thead><tbody>{routes.data.map((item) => <tr key={item.id}><td><div className="table-name"><span className="table-icon"><RadioTower size={18} /></span><div><strong>{item.name}</strong><small>{dateText(item.created_at)}</small></div></div></td><td><code>{item.model_alias}</code></td><td>{deploymentName(item.deployment_id)}</td><td><StatusBadge status={item.status} /></td><td className="action-cell"><div className="row-actions"><Link to="/test" className="table-action">测试 <ArrowRight size={14} /></Link>{editable && <><button className="icon-button" title="编辑" aria-label={`编辑${item.name}`} onClick={() => openEdit(item)}><Pencil size={16} /></button><button className="icon-button danger-hover" title="删除" aria-label={`删除${item.name}`} onClick={() => setDeletingRoute(item)}><Trash2 size={16} /></button></>}</div></td></tr>)}</tbody></table></div>}
      </Panel> :
      <Panel title="访问凭证" aside={<button className="icon-button" onClick={() => void keys.reload()} title="刷新"><RefreshCw size={17} /></button>}>
        <div className="panel-explainer"><KeyRound size={18} />完整密钥只在创建时显示一次；此处仅保留前缀用于识别。</div>
        {keys.loading ? <Busy /> : keys.error ? <Failure error={keys.error} retry={() => void keys.reload()} /> : keys.data.length === 0 ?
          <Empty icon={<KeyRound size={26} />} title="尚未创建 API Key" description="创建凭证后，使用 Authorization: Bearer 请求统一网关。" action={editable && <button className="button button-outline" onClick={() => { setKeyOpen(true); setGeneratedSecret('') }}><Plus size={16} />创建凭证</button>} /> :
          <div className="table-scroll"><table className="data-table"><thead><tr><th>名称</th><th>密钥前缀</th><th>状态</th><th>创建时间</th><th className="action-cell">操作</th></tr></thead><tbody>{keys.data.map((item) => <tr key={item.id}><td><div className="table-name"><span className="table-icon"><KeyRound size={18} /></span><div><strong>{item.name}</strong></div></div></td><td><code>{item.prefix}••••••••</code></td><td><StatusBadge status={item.status} /></td><td className="muted">{dateText(item.created_at)}</td><td className="action-cell">{editable && <button className="table-action destructive" onClick={() => setDeletingKey(item)}>撤销</button>}</td></tr>)}</tbody></table></div>}
      </Panel>}
    <Dialog open={routeOpen} title={editing ? '编辑转发路由' : '创建转发路由'} subtitle="将一个模型别名映射到已登记的推理服务。" onClose={() => setRouteOpen(false)}>
      <form className="dialog-form" onSubmit={saveRoute}><Field label="路由名称" required><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="例如：默认对话模型" required /></Field><Field label="对外模型别名" hint="客户端在 model 参数中填写此别名。" required><input value={form.model_alias} onChange={(e) => setForm({ ...form, model_alias: e.target.value })} placeholder="例如：qwen-chat" required /></Field><Field label="目标部署" required><Select value={form.deployment_id} onChange={(e) => setForm({ ...form, deployment_id: e.target.value })} required><option value="">选择部署</option>{deployments.data.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.status}</option>)}</Select></Field>{deployments.data.length === 0 && <div className="form-hint-block">尚无部署。<Link to="/deployments" onClick={() => setRouteOpen(false)}>先登记服务 <ArrowRight size={14} /></Link></div>}<Field label="路由状态"><Select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}><option value="active">启用</option><option value="disabled">停用</option></Select></Field><FormError error={mutation.error} /><div className="dialog-actions"><button type="button" className="button button-ghost" onClick={() => setRouteOpen(false)}>取消</button><SubmitButton busy={mutation.busy}>{editing ? '保存路由' : '创建路由'}</SubmitButton></div></form>
    </Dialog>
    <Dialog open={keyOpen} title={generatedSecret ? '保存 API Key' : '创建 API Key'} subtitle={generatedSecret ? '关闭此窗口后将无法再次查看完整密钥。' : '为外部调用创建独立的访问凭证。'} onClose={() => setKeyOpen(false)}>
      {generatedSecret ? <div className="secret-content"><div className="secret-warning"><ShieldCheck size={18} />请立即复制并安全保存。平台不会再次显示此密钥。</div><div className="secret-box"><code>{generatedSecret}</code><button className="icon-button" aria-label="复制密钥" onClick={() => void copySecret()}>{copied ? <Check size={18} /> : <Copy size={18} />}</button></div><div className="dialog-actions"><button className="button button-primary" onClick={() => setKeyOpen(false)}>我已保存</button></div></div> :
        <form className="dialog-form" onSubmit={saveKey}><Field label="凭证名称" hint="建议按应用或负责人命名，方便日后撤销。" required><input value={keyName} onChange={(e) => setKeyName(e.target.value)} placeholder="例如：内部测试应用" required /></Field><FormError error={mutation.error} /><div className="dialog-actions"><button type="button" className="button button-ghost" onClick={() => setKeyOpen(false)}>取消</button><SubmitButton busy={mutation.busy}>生成密钥</SubmitButton></div></form>}
    </Dialog>
    <ConfirmDialog open={Boolean(deletingRoute)} title="删除转发路由" description={`确定删除“${deletingRoute?.name || ''}”吗？正在使用此模型别名的调用将失败。`} onCancel={() => setDeletingRoute(null)} onConfirm={() => void removeRoute()} busy={mutation.busy} />
    <ConfirmDialog open={Boolean(deletingKey)} title="撤销 API Key" description={`确定撤销“${deletingKey?.name || ''}”吗？使用此凭证的调用会立即失效。`} onCancel={() => setDeletingKey(null)} onConfirm={() => void removeKey()} busy={mutation.busy} />
  </>
}

type Completion = {
  id?: string; model?: string
  choices?: Array<{ message?: { content?: string | Array<{ text?: string }> }; text?: string }>
  usage?: { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number }
}

export function TestPage() {
  const routes = useCollection<Route>('/routes')
  const [routeId, setRouteId] = useState('')
  const [prompt, setPrompt] = useState('')
  const [result, setResult] = useState<Completion | null>(null)
  const [elapsed, setElapsed] = useState<number | null>(null)
  const mutation = useMutation()
  const activeRoutes = routes.data.filter((route) => route.status === 'active')
  const output = result?.choices?.[0]?.message?.content
  const content = typeof output === 'string' ? output : Array.isArray(output) ? output.map((part) => part.text || '').join('') : result?.choices?.[0]?.text || ''
  const runTest = (event: FormEvent) => {
    event.preventDefault(); setResult(null); setElapsed(null)
    const started = performance.now()
    void mutation.run(async () => {
      const response = await api.post<Completion>('/test', { route_id: routeId, prompt })
      setResult(response); setElapsed(Math.round(performance.now() - started))
    })
  }
  return <>
    <PageHeader eyebrow="INFERENCE LAB / 05" title="模型测试" description="通过真实网关路由发送请求，查看模型响应与用量。" />
    <div className="test-layout">
      <Panel title="请求配置" aside={<span className="section-tag">CHAT COMPLETION</span>} className="test-input-panel">
        <form className="test-form" onSubmit={runTest}>
          <Field label="测试路由" required><Select value={routeId} onChange={(e) => setRouteId(e.target.value)} required><option value="">选择启用的路由</option>{activeRoutes.map((route) => <option key={route.id} value={route.id}>{route.name} · {route.model_alias}</option>)}</Select></Field>
          {routes.loading ? <p className="form-note">正在加载路由…</p> : routes.error ? <p className="form-error">{routes.error}</p> : activeRoutes.length === 0 && <div className="form-hint-block">没有可测试的启用路由。<Link to="/forwarding">去创建路由 <ArrowRight size={14} /></Link></div>}
          <Field label="测试提示词" required><textarea className="prompt-input" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="输入想让模型回答的问题…" rows={9} required /></Field>
          <div className="prompt-suggestion"><span>快速填入</span><button type="button" onClick={() => setPrompt('请用三句话介绍你的主要能力。')}><WandSparkles size={14} />能力介绍</button><button type="button" onClick={() => setPrompt('请解释什么是模型推理网关，并给出一个实际应用场景。')}>技术问答</button></div>
          <FormError error={mutation.error} />
          <SubmitButton busy={mutation.busy} icon={<Send size={16} />}>发送测试请求</SubmitButton>
          <p className="test-disclaimer">请求将转发至所选路由关联的真实上游服务。</p>
        </form>
      </Panel>
      <Panel title="响应结果" aside={result && <span className="section-tag">SUCCESS / 200</span>} className="test-output-panel">
        {mutation.busy ? <div className="test-waiting"><span className="test-pulse" /><h3>模型正在生成响应</h3><p>等待上游服务返回内容…</p></div> :
          result ? <div className="test-result"><div className="response-header"><span className="response-icon"><FlaskConical size={18} /></span><div><strong>模型响应</strong><small>{result.model || '未知模型'}</small></div></div><div className="response-content">{content || '上游返回了空内容。'}</div><div className="response-meta"><div><span>耗时</span><strong>{elapsed == null ? '—' : `${elapsed} ms`}</strong></div><div><span>输入 Token</span><strong>{result.usage?.prompt_tokens ?? '—'}</strong></div><div><span>输出 Token</span><strong>{result.usage?.completion_tokens ?? '—'}</strong></div><div><span>合计 Token</span><strong>{result.usage?.total_tokens ?? '—'}</strong></div></div>{result.id && <div className="response-id">REQUEST ID <code>{result.id}</code></div>}</div> :
            <div className="test-placeholder"><div className="test-placeholder-graphic"><FlaskConical size={35} strokeWidth={1.3} /><i /><i /><i /></div><h3>等待你的第一次测试</h3><p>选择路由、输入提示词并发送请求，响应会显示在这里。</p></div>}
      </Panel>
    </div>
  </>
}

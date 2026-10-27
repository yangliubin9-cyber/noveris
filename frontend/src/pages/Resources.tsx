import { useMemo, useState, type FormEvent } from 'react'
import { ArrowRight, Boxes, CheckCircle2, Cpu, ExternalLink, Eye, HardDrive, KeyRound, Network, Pencil, Plus, RefreshCw, Search, Server, ShieldCheck, Store, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api, errorText } from '../api'
import { useAuth } from '../auth'
import type { Deployment, Model, Node } from '../types'
import { Busy, ConfirmDialog, dateText, Dialog, Empty, Failure, Field, FormError, PageHeader, Panel, Select, StatusBadge, SubmitButton, useCollection, useMutation, useToast } from '../ui'

const canEdit = (role?: string) => role === 'admin' || role === 'operator'

type NodeForm = { name: string; address: string; port: number; description: string; username: string; password: string }
const blankNode: NodeForm = { name: '', address: '', port: 22, description: '', username: '', password: '' }

export function NodesPage() {
  const { user } = useAuth()
  const notify = useToast()
  const { data, loading, error, reload } = useCollection<Node>('/nodes')
  const [query, setQuery] = useState('')
  const [editing, setEditing] = useState<Node | null>(null)
  const [form, setForm] = useState<NodeForm>(blankNode)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [detail, setDetail] = useState<Node | null>(null)
  const [deleting, setDeleting] = useState<Node | null>(null)
  const [checking, setChecking] = useState<number | null>(null)
  const mutation = useMutation()
  const filtered = useMemo(() => data.filter((item) => `${item.name} ${item.address} ${item.username || ''} ${item.description || ''}`.toLowerCase().includes(query.toLowerCase())), [data, query])
  const openCreate = () => { setEditing(null); setForm(blankNode); mutation.setError(''); setDialogOpen(true) }
  const openEdit = (item: Node) => { setEditing(item); setForm({ name: item.name, address: item.address, port: item.port || 22, description: item.description || '', username: item.username || '', password: '' }); mutation.setError(''); setDetail(null); setDialogOpen(true) }
  const closeEditor = () => { setForm((previous) => ({ ...previous, password: '' })); setDialogOpen(false) }
  const save = (event: FormEvent) => {
    event.preventDefault()
    if (form.password && !form.username.trim()) {
      mutation.setError('填写 SSH 密码前，请先填写 SSH 用户名。')
      return
    }
    const body: Record<string, string | number | null> = editing ? {} : {
      name: form.name, address: form.address, port: form.port, description: form.description,
    }
    if (editing) {
      if (form.name !== editing.name) body.name = form.name
      if (form.address !== editing.address) body.address = form.address
      if (form.port !== (editing.port || 22)) body.port = form.port
      if (form.description !== (editing.description || '')) body.description = form.description
      if (form.username.trim() !== (editing.username || '')) body.username = form.username.trim() || null
    } else if (form.username.trim()) body.username = form.username.trim()
    if (form.password) body.password = form.password
    if (editing && Object.keys(body).length === 0) {
      mutation.setError('没有可保存的修改。')
      return
    }
    void mutation.run(
      () => editing ? api.put<Node>(`/nodes/${editing.id}`, body) : api.post<Node>('/nodes', body),
      () => { closeEditor(); notify(editing ? '节点信息已更新' : '节点已登记'); void reload() },
    )
  }
  const check = async (item: Node) => {
    setChecking(item.id)
    try {
      const checked = await api.post<Node>(`/nodes/${item.id}/check`)
      const healthy = checked.status === 'online'
      notify(healthy ? checked.last_check_mode === 'ssh' ? 'SSH 登录成功，已采集只读节点信息' : 'TCP 端口可达；尚未验证 SSH 登录' : checked.last_error || '连接检查失败', healthy ? 'success' : 'error')
      if (detail?.id === checked.id) setDetail(checked)
      void reload()
    } catch (err) { notify(errorText(err), 'error') }
    finally { setChecking(null) }
  }
  const remove = async () => {
    if (!deleting) return
    const deleted = deleting
    await mutation.run(() => api.delete(`/nodes/${deleted.id}`), () => { setDeleting(null); notify('节点已删除'); void reload() })
  }
  return <>
    <PageHeader eyebrow="INFRASTRUCTURE / 01" title="节点管理" description="登记节点并检查 TCP 或 SSH 连接；SSH 检查会只读采集系统与硬件信息。"
      action={canEdit(user?.role) && <button className="button button-primary" onClick={openCreate}><Plus size={17} />添加节点</button>} />
    <div className="summary-strip"><div><span className="summary-mark"><Server size={18} /></span><strong>{data.length}</strong><span>节点总数</span></div><div><span className="summary-mark healthy"><CheckCircle2 size={18} /></span><strong>{data.filter((n) => n.status === 'online').length}</strong><span>连接在线</span></div><div className="summary-strip-note">仅 TCP 可达不代表 SSH 登录成功。</div></div>
    <Panel title="节点目录" aside={<div className="table-tools"><div className="search-box"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索名称或地址" aria-label="搜索节点" /></div><button className="icon-button" onClick={() => void reload()} title="刷新"><RefreshCw size={17} /></button></div>}>
      {loading ? <Busy /> : error ? <Failure error={error} retry={() => void reload()} /> : filtered.length === 0 ?
        <Empty icon={<Network size={26} />} title={query ? '没有匹配的节点' : '尚未登记节点'} description={query ? '换个名称或地址试试。' : '添加一台可访问的计算节点，以便记录模型服务的运行位置。'} action={!query && canEdit(user?.role) && <button className="button button-outline" onClick={openCreate}><Plus size={16} />添加第一个节点</button>} /> :
        <div className="table-scroll"><table className="data-table"><thead><tr><th>节点名称</th><th>访问地址</th><th>SSH 凭证</th><th>只读采集概览</th><th>状态</th><th className="action-cell">操作</th></tr></thead><tbody>{filtered.map((item) => <tr key={item.id}>
          <td><div className="table-name"><span className="table-icon"><HardDrive size={18} /></span><div><strong>{item.name}</strong><small>{item.description || '暂无描述'}</small></div></div></td>
          <td><code>{item.address}:{item.port || 22}</code></td>
          <td><div className="stacked-cell"><strong>{item.username || '未设置用户'}</strong><small>{item.has_password ? '密码已配置' : '未配置密码'}</small></div></td>
          <td><div className="stacked-cell"><strong>{item.facts ? `${item.facts.cpu_cores ?? '—'} 核 · ${item.facts.memory_gb ?? '—'} GB` : '尚未采集'}</strong><small>{item.facts ? `${item.facts.gpus?.length ?? 0} 块 NVIDIA GPU · ${item.facts.os || '未知系统'}` : 'SSH 检查后显示'}</small></div></td>
          <td><StatusBadge status={item.status} /><small className="node-check-mode">{item.last_check_mode === 'ssh' ? 'SSH 已验证' : item.last_check_mode === 'tcp' ? '仅 TCP 可达' : '尚未检查'}</small>{item.last_error && <small className="cell-error" title={item.last_error}>{item.last_error}</small>}</td>
          <td className="action-cell"><div className="row-actions"><button className="table-action" onClick={() => setDetail(item)}><Eye size={14} />详情</button>{canEdit(user?.role) && <><button className="table-action" onClick={() => void check(item)} disabled={checking === item.id}>{checking === item.id ? '检查中…' : '检查连接'}</button><button className="icon-button" title="编辑" aria-label={`编辑${item.name}`} onClick={() => openEdit(item)}><Pencil size={16} /></button><button className="icon-button danger-hover" title="删除" aria-label={`删除${item.name}`} onClick={() => setDeleting(item)}><Trash2 size={16} /></button></>}</div></td>
        </tr>)}</tbody></table></div>}
    </Panel>
    <Dialog open={dialogOpen} title={editing ? '编辑节点' : '添加计算节点'} subtitle="可选配 SSH 凭证，以采集只读系统与硬件信息。" onClose={closeEditor} size="wide">
      <form className="dialog-form" onSubmit={save}>
        <Field label="节点名称" required><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="例如：GPU-01" required /></Field>
        <div className="form-grid">
          <Field label="节点 IP 地址" hint="生产环境仅支持 IP，不支持 DNS 主机名。" required><input value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} placeholder="例如：192.0.2.10" required /></Field>
          <Field label="SSH / 探测端口" hint="默认 22；TCP 和 SSH 检查使用此端口。" required><input type="number" min={1} max={65535} value={form.port} onChange={(e) => setForm({ ...form, port: Number(e.target.value) })} required /></Field>
        </div>
        <div className="credential-heading"><KeyRound size={16} /><strong>SSH 登录凭证</strong><span>可选</span></div>
        <div className="form-grid">
          <Field label="SSH 用户名"><input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} placeholder="例如：root" autoComplete="off" /></Field>
          <Field label="SSH 密码" hint={editing ? '留空表示保留已配置的密码；旧密码不会回显。' : '不填写时仅检查 TCP 端口，不会登录 SSH。'}><input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder={editing?.has_password ? '已配置 · 留空保持不变' : '输入 SSH 密码'} autoComplete="off" /></Field>
        </div>
        <div className="credential-note"><ShieldCheck size={17} /><span>配置用户名和密码后，“检查连接”会执行 SSH 登录并只读采集主机名、操作系统、CPU、内存和 NVIDIA GPU 信息。仅 TCP 可达不代表 SSH 登录成功。</span></div>
        <Field label="描述"><textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} rows={3} placeholder="用途、机房或硬件说明" /></Field>
        <FormError error={mutation.error} /><div className="dialog-actions"><button type="button" className="button button-ghost" onClick={closeEditor}>取消</button><SubmitButton busy={mutation.busy}>{editing ? '保存修改' : '添加节点'}</SubmitButton></div>
      </form>
    </Dialog>
    <Dialog open={Boolean(detail)} title={detail?.name || '节点详情'} subtitle={detail ? `${detail.address}:${detail.port || 22}` : ''} onClose={() => setDetail(null)} size="wide">
      {detail && <div className="node-detail">
        <div className="node-detail-status"><StatusBadge status={detail.status} /><span>{detail.last_check_mode === 'ssh' ? 'SSH 登录已验证，采集信息为只读' : detail.last_check_mode === 'tcp' ? '仅 TCP 端口可达，尚未验证 SSH 登录' : '尚未执行连接检查'}</span></div>
        {detail.last_error && <div className="form-error">{detail.last_error}</div>}
        <div className="node-detail-grid">
          <div><span>SSH 用户名</span><strong>{detail.username || '未设置'}</strong></div>
          <div><span>SSH 密码</span><strong>{detail.has_password ? '已配置 · 不回显' : '未配置'}</strong></div>
          <div><span>最近检查</span><strong>{dateText(detail.last_check_at)}</strong></div>
          <div><span>节点描述</span><strong>{detail.description || '—'}</strong></div>
        </div>
        <div className="node-facts-heading"><Cpu size={17} /><strong>只读采集信息</strong></div>
        {detail.facts ? <>
          <div className="node-detail-grid">
            <div><span>主机名</span><strong>{detail.facts.hostname || '—'}</strong></div>
            <div><span>操作系统</span><strong>{detail.facts.os || '—'}</strong></div>
            <div><span>内核版本</span><strong>{detail.facts.kernel || '—'}</strong></div>
            <div><span>CPU 核心 / 内存</span><strong>{detail.facts.cpu_cores ?? '—'} 核 / {detail.facts.memory_gb ?? '—'} GB</strong></div>
          </div>
          <div className="node-gpu-list"><span>NVIDIA GPU 设备 · {detail.facts.gpus?.length || 0}</span>
            {detail.facts.gpus?.length ? detail.facts.gpus.map((gpu, index) => <div key={index}><strong>{gpu.name || `GPU ${index + 1}`}</strong><small>{gpu.memory_mb ? `${gpu.memory_mb} MB` : '显存未知'} · 驱动 {gpu.driver_version || '未知'}</small></div>) : <p>未检测到 NVIDIA GPU</p>}
          </div>
        </> : <div className="node-facts-empty">尚无 SSH 采集结果。配置凭证后执行“检查连接”，即可查看只读节点信息。</div>}
        <div className="dialog-actions">{canEdit(user?.role) && <button className="button button-outline" disabled={checking === detail.id} onClick={() => void check(detail)}>{checking === detail.id ? '检查中…' : '检查连接并采集'}</button>}<button className="button button-ghost" onClick={() => setDetail(null)}>关闭</button></div>
      </div>}
    </Dialog>
    <ConfirmDialog open={Boolean(deleting)} title="删除节点" description={`确定删除“${deleting?.name || ''}”吗？已关联的模型部署可能需要先删除或调整。`} onCancel={() => setDeleting(null)} onConfirm={() => void remove()} busy={mutation.busy} />
  </>
}

type ModelForm = { name: string; model_id: string; description: string; category: string; source: string }
const blankModel: ModelForm = { name: '', model_id: '', description: '', category: '对话生成', source: '自定义' }

export function MarketplacePage() {
  const { user } = useAuth()
  const notify = useToast()
  const { data, loading, error, reload } = useCollection<Model>('/models')
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('')
  const [dialogOpen, setDialogOpen] = useState(false)
  const [form, setForm] = useState<ModelForm>(blankModel)
  const mutation = useMutation()
  const categories = [...new Set(data.map((model) => model.category).filter(Boolean))] as string[]
  const filtered = data.filter((model) => `${model.name} ${model.model_id} ${model.description || ''}`.toLowerCase().includes(query.toLowerCase()) && (!category || model.category === category))
  const save = (event: FormEvent) => {
    event.preventDefault()
    const body = { ...form, model_id: form.model_id.trim() || form.name.trim() }
    void mutation.run(() => api.post<Model>('/models', body), () => { setDialogOpen(false); setForm(blankModel); notify('模型已加入市场'); void reload() })
  }
  return <>
    <PageHeader eyebrow="MODEL CATALOG / 02" title="模型市场" description="维护模型资产目录。当前 MVP 网关支持对话生成接口转发。"
      action={canEdit(user?.role) && <button className="button button-primary" onClick={() => { setForm(blankModel); mutation.setError(''); setDialogOpen(true) }}><Plus size={17} />录入模型</button>} />
    <div className="catalog-banner"><div><div className="eyebrow">CURATED MODEL REGISTRY</div><h2>你的模型资产，集中管理。</h2><p>在这里登记模型元数据，再将模型绑定到已有推理服务。</p></div><Store size={84} strokeWidth={0.9} /></div>
    <Panel title={`模型目录 · ${data.length}`} aside={<div className="table-tools"><div className="search-box"><Search size={17} /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索名称、模型 ID" aria-label="搜索模型" /></div><Select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="模型分类"><option value="">全部分类</option>{categories.map((item) => <option key={item}>{item}</option>)}</Select><button className="icon-button" onClick={() => void reload()} title="刷新"><RefreshCw size={17} /></button></div>}>
      {loading ? <Busy /> : error ? <Failure error={error} retry={() => void reload()} /> : filtered.length === 0 ?
        <Empty icon={<Store size={26} />} title={query || category ? '没有匹配的模型' : '模型市场还是空的'} description={query || category ? '调整搜索条件以查看其他模型。' : '先录入一个模型，再登记它的推理服务。'} action={!query && !category && canEdit(user?.role) && <button className="button button-outline" onClick={() => setDialogOpen(true)}><Plus size={16} />录入模型</button>} /> :
        <div className="model-grid">{filtered.map((model) => <article key={model.id} className="model-card"><div className="model-card-top"><span className="model-symbol"><Cpu size={23} /></span><span className="model-category">{model.category || '未分类'}</span></div><h3>{model.name}</h3><code title={model.model_id}>{model.model_id}</code><p>{model.description || '暂无模型描述。'}</p><div className="model-card-bottom"><span>{model.source || '自定义来源'}</span><Link to="/deployments">登记部署 <ArrowRight size={15} /></Link></div></article>)}</div>}
    </Panel>
    <Dialog open={dialogOpen} title="录入模型" subtitle="保存模型名称及来源，供部署页面选择。" onClose={() => setDialogOpen(false)}>
      <form className="dialog-form" onSubmit={save}><div className="form-grid"><Field label="展示名称" required><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="例如：Qwen 2.5 7B" required /></Field><Field label="模型 ID" hint="上游 /v1/models 中的 ID。"><input value={form.model_id} onChange={(e) => setForm({ ...form, model_id: e.target.value })} placeholder="例如：Qwen/Qwen2.5-7B-Instruct" /></Field></div><div className="form-grid"><Field label="分类"><Select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}><option>对话生成</option><option>文本嵌入</option><option>重排序</option><option>多模态</option><option>其他</option></Select></Field><Field label="来源"><input value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} placeholder="Hugging Face / 内部模型" /></Field></div><Field label="描述"><textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} rows={3} placeholder="模型能力与使用场景" /></Field><FormError error={mutation.error} /><div className="dialog-actions"><button type="button" className="button button-ghost" onClick={() => setDialogOpen(false)}>取消</button><SubmitButton busy={mutation.busy}>保存模型</SubmitButton></div></form>
    </Dialog>
  </>
}

type DeployForm = { name: string; model_id: string; node_id: string; upstream_url: string; upstream_api_key: string }
const blankDeploy: DeployForm = { name: '', model_id: '', node_id: '', upstream_url: '', upstream_api_key: '' }

export function DeploymentsPage() {
  const { user } = useAuth()
  const notify = useToast()
  const deployments = useCollection<Deployment>('/deployments')
  const models = useCollection<Model>('/models')
  const nodes = useCollection<Node>('/nodes')
  const [query, setQuery] = useState('')
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<Deployment | null>(null)
  const [deleting, setDeleting] = useState<Deployment | null>(null)
  const [checking, setChecking] = useState<number | null>(null)
  const [form, setForm] = useState<DeployForm>(blankDeploy)
  const mutation = useMutation()
  const nameOfModel = (id: number) => models.data.find((model) => model.id === id)?.name || '未知模型'
  const nameOfNode = (id: number) => nodes.data.find((node) => node.id === id)?.name || '未知节点'
  const filtered = deployments.data.filter((item) => `${item.name} ${item.upstream_url} ${nameOfModel(item.model_id)}`.toLowerCase().includes(query.toLowerCase()))
  const openCreate = () => { setEditing(null); setForm(blankDeploy); mutation.setError(''); setDialogOpen(true) }
  const openEdit = (item: Deployment) => { setEditing(item); setForm({ name: item.name, model_id: String(item.model_id), node_id: String(item.node_id), upstream_url: item.upstream_url, upstream_api_key: '' }); mutation.setError(''); setDialogOpen(true) }
  const save = (event: FormEvent) => {
    event.preventDefault()
    const body: Record<string, string> = { name: form.name, model_id: form.model_id, node_id: form.node_id, upstream_url: form.upstream_url }
    if (form.upstream_api_key) body.upstream_api_key = form.upstream_api_key
    void mutation.run(
      () => editing ? api.put<Deployment>(`/deployments/${editing.id}`, body) : api.post<Deployment>('/deployments', body),
      () => { setDialogOpen(false); notify(editing ? '部署配置已更新' : '模型服务已登记'); void deployments.reload() },
    )
  }
  const check = async (item: Deployment) => {
    setChecking(item.id)
    try {
      const checked = await api.post<Deployment>(`/deployments/${item.id}/check`)
      const healthy = ['running', 'healthy', 'online'].includes(checked.status)
      notify(healthy ? '模型服务可访问' : checked.last_error || '健康检查已完成', healthy ? 'success' : 'error')
      void deployments.reload()
    } catch (err) { notify(errorText(err), 'error') }
    finally { setChecking(null) }
  }
  const remove = async () => {
    if (!deleting) return
    const item = deleting
    await mutation.run(() => api.delete(`/deployments/${item.id}`), () => { setDeleting(null); notify('部署已删除'); void deployments.reload() })
  }
  return <>
    <PageHeader eyebrow="MODEL SERVING / 03" title="模型部署" description="登记已运行的 OpenAI 兼容推理服务，并检查可用状态。"
      action={canEdit(user?.role) && <button className="button button-primary" onClick={openCreate}><Plus size={17} />登记部署</button>} />
    <div className="info-callout"><div className="info-icon"><Boxes size={19} /></div><div><strong>部署方式</strong><p>当前 MVP 负责登记与验证已有服务。请先在节点上启动推理服务，再填写其 Base URL。</p></div><ExternalLink size={16} /></div>
    <Panel title={`服务部署 · ${deployments.data.length}`} aside={<div className="table-tools"><div className="search-box"><Search size={17} /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索部署或地址" aria-label="搜索部署" /></div><button className="icon-button" onClick={() => void deployments.reload()} title="刷新"><RefreshCw size={17} /></button></div>}>
      {deployments.loading ? <Busy /> : deployments.error ? <Failure error={deployments.error} retry={() => void deployments.reload()} /> : filtered.length === 0 ?
        <Empty icon={<Boxes size={26} />} title={query ? '没有匹配的部署' : '尚未登记模型服务'} description={query ? '调整搜索关键词。' : '登记已运行的上游地址，并在此检查服务可用性。'} action={!query && canEdit(user?.role) && <button className="button button-outline" onClick={openCreate}><Plus size={16} />登记服务</button>} /> :
        <div className="table-scroll"><table className="data-table"><thead><tr><th>部署名称</th><th>模型 / 节点</th><th>上游地址</th><th>状态</th><th className="action-cell">操作</th></tr></thead><tbody>{filtered.map((item) => <tr key={item.id}><td><div className="table-name"><span className="table-icon"><Boxes size={18} /></span><div><strong>{item.name}</strong><small>登记于 {dateText(item.created_at)}</small></div></div></td><td><div className="stacked-cell"><strong>{nameOfModel(item.model_id)}</strong><small>{nameOfNode(item.node_id)}</small></div></td><td><code title={item.upstream_url} className="url-code">{item.upstream_url}</code></td><td><StatusBadge status={item.status} />{item.last_error && <small className="cell-error" title={item.last_error}>{item.last_error}</small>}</td><td className="action-cell"><div className="row-actions">{canEdit(user?.role) && <><button className="table-action" onClick={() => void check(item)} disabled={checking === item.id}>{checking === item.id ? '检查中…' : '健康检查'}</button><button className="icon-button" title="编辑" aria-label={`编辑${item.name}`} onClick={() => openEdit(item)}><Pencil size={16} /></button><button className="icon-button danger-hover" title="删除" aria-label={`删除${item.name}`} onClick={() => setDeleting(item)}><Trash2 size={16} /></button></>}</div></td></tr>)}</tbody></table></div>}
    </Panel>
    <Dialog open={dialogOpen} title={editing ? '编辑服务部署' : '登记模型服务'} subtitle="填写已运行的 OpenAI 兼容上游服务。" onClose={() => setDialogOpen(false)} size="wide">
      <form className="dialog-form" onSubmit={save}>
        <Field label="部署名称" required><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="例如：Qwen 生产推理" required /></Field>
        <div className="form-grid"><Field label="关联模型" required><Select value={form.model_id} onChange={(e) => setForm({ ...form, model_id: e.target.value })} required><option value="">选择模型</option>{models.data.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</Select></Field><Field label="运行节点" required><Select value={form.node_id} onChange={(e) => setForm({ ...form, node_id: e.target.value })} required><option value="">选择节点</option>{nodes.data.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.address}</option>)}</Select></Field></div>
        {models.data.length === 0 && <div className="form-hint-block">还没有模型资产。<Link to="/marketplace" onClick={() => setDialogOpen(false)}>先去模型市场录入 <ArrowRight size={14} /></Link></div>}
        {nodes.data.length === 0 && <div className="form-hint-block">还没有节点。<Link to="/nodes" onClick={() => setDialogOpen(false)}>先去添加节点 <ArrowRight size={14} /></Link></div>}
        <Field label="上游 Base URL" hint="主机必须与所选节点 IP 一致。填写 http://IP:port 或 http://IP:port/v1。" required><input type="url" value={form.upstream_url} onChange={(e) => setForm({ ...form, upstream_url: e.target.value })} placeholder="http://10.0.10.25:8000/v1" required /></Field>
        <Field label="上游 API Key" hint={editing ? '留空表示保留原有密钥。' : '上游无需鉴权时可留空。'}><input type="password" value={form.upstream_api_key} onChange={(e) => setForm({ ...form, upstream_api_key: e.target.value })} placeholder="可选" autoComplete="new-password" /></Field>
        <FormError error={mutation.error} /><div className="dialog-actions"><button className="button button-ghost" type="button" onClick={() => setDialogOpen(false)}>取消</button><SubmitButton busy={mutation.busy}>{editing ? '保存配置' : '登记服务'}</SubmitButton></div>
      </form>
    </Dialog>
    <ConfirmDialog open={Boolean(deleting)} title="删除部署" description={`确定删除“${deleting?.name || ''}”吗？使用此部署的路由需要先调整或删除。`} onCancel={() => setDeleting(null)} onConfirm={() => void remove()} busy={mutation.busy} />
  </>
}

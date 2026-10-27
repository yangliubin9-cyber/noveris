import { useEffect, useState } from 'react'
import { ArrowRight, ArrowUpRight, Boxes, Cpu, FlaskConical, KeyRound, Network, RadioTower, RefreshCw, Store } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api, errorText } from '../api'
import type { Dashboard } from '../types'
import { Busy, Failure, PageHeader, Panel } from '../ui'

const metrics = [
  { key: 'nodes', title: '已纳管节点', unit: '台', icon: Network, to: '/nodes', marker: '01' },
  { key: 'models', title: '模型资产', unit: '个', icon: Store, to: '/marketplace', marker: '02' },
  { key: 'deployments', title: '服务部署', unit: '项', icon: Boxes, to: '/deployments', marker: '03' },
  { key: 'routes', title: '转发路由', unit: '条', icon: RadioTower, to: '/forwarding', marker: '04' },
] as const

export function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const load = async () => {
    setLoading(true); setError('')
    try { setData(await api.get<Dashboard>('/dashboard')) }
    catch (err) { setError(errorText(err)) }
    finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [])
  return <>
    <PageHeader eyebrow="OVERVIEW / 运行总览" title="AI 控制塔" description="集中查看算力、模型服务与接入状态。"
      action={<button className="button button-outline" onClick={() => void load()}><RefreshCw size={16} />刷新数据</button>} />
    {loading ? <Busy /> : error ? <Failure error={error} retry={() => void load()} /> : data && <>
      <div className="dashboard-hero">
        <div className="dashboard-hero-copy"><div className="hero-caption"><span className="live-dash" />CONTROL PLANE / LIVE</div><h2>从资源到调用，<br /><em>保持全链路可见。</em></h2><p>选择下一项操作，快速完成模型上线与验证。</p><Link to="/deployments" className="button button-light">管理模型部署 <ArrowRight size={17} /></Link></div>
        <div className="dashboard-hero-visual"><div className="hero-ring ring-one" /><div className="hero-ring ring-two" /><div className="hero-ring ring-three" /><div className="hero-center"><Cpu size={37} strokeWidth={1.3} /><span>AI CORE</span></div><div className="hero-float float-a">NODE <strong>{data.healthy_nodes ?? 0}</strong></div><div className="hero-float float-b">DEPLOY <strong>{data.running_deployments ?? 0}</strong></div></div>
      </div>
      <div className="metric-grid">{metrics.map(({ key, title, unit, icon: Icon, to, marker }) => <Link key={key} to={to} className="metric-card"><div className="metric-top"><span>{marker} / RESOURCE</span><Icon size={20} strokeWidth={1.7} /></div><div className="metric-value">{data[key] ?? 0}<small>{unit}</small></div><div className="metric-footer"><span>{title}</span><ArrowUpRight size={16} /></div></Link>)}</div>
      <div className="dashboard-bottom">
        <Panel title="运行态势" aside={<span className="section-tag">实时统计</span>} className="status-panel">
          <div className="status-row"><div className="status-row-icon status-green"><Network size={18} /></div><div><strong>健康节点</strong><span>通过最近一次连接检查</span></div><b>{data.healthy_nodes ?? 0}<small> / {data.nodes ?? 0}</small></b></div>
          <div className="status-row"><div className="status-row-icon status-blue"><Boxes size={18} /></div><div><strong>运行中的部署</strong><span>可供路由绑定的模型服务</span></div><b>{data.running_deployments ?? 0}<small> / {data.deployments ?? 0}</small></b></div>
          <div className="status-row"><div className="status-row-icon status-orange"><KeyRound size={18} /></div><div><strong>已创建 API Key</strong><span>用于外部系统访问转发网关</span></div><b>{data.api_keys ?? 0}</b></div>
          <div className="status-row"><div className="status-row-icon status-dark"><RadioTower size={18} /></div><div><strong>最近调用</strong><span>由模型网关记录</span></div><b>{data.recent_requests ?? 0}</b></div>
        </Panel>
        <Panel title="快速开始" aside={<span className="section-tag">推荐操作</span>} className="quick-panel">
          <Link to="/nodes" className="quick-link"><div className="quick-index">01</div><div><strong>接入计算节点</strong><span>登记 IP 地址并检查连接</span></div><ArrowUpRight size={18} /></Link>
          <Link to="/marketplace" className="quick-link"><div className="quick-index">02</div><div><strong>录入模型资产</strong><span>整理即将使用的模型信息</span></div><ArrowUpRight size={18} /></Link>
          <Link to="/forwarding" className="quick-link"><div className="quick-index">03</div><div><strong>发布转发路由</strong><span>为现有服务配置统一调用别名</span></div><ArrowUpRight size={18} /></Link>
          <Link to="/test" className="quick-link"><div className="quick-index">04</div><div><strong>发送测试请求</strong><span>验证路由与模型输出</span></div><FlaskConical size={18} /></Link>
        </Panel>
      </div>
    </>}
  </>
}

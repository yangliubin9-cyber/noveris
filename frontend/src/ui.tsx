import { createContext, useCallback, useContext, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { AlertCircle, Check, ChevronDown, LoaderCircle, Plus, X } from 'lucide-react'
import { api, errorText } from './api'

type Toast = { id: number; text: string; tone: 'success' | 'error' }
const ToastContext = createContext<(text: string, tone?: Toast['tone']) => void>(() => undefined)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const notify = useCallback((text: string, tone: Toast['tone'] = 'success') => {
    const id = Date.now() + Math.random()
    setToasts((current) => [...current, { id, text, tone }])
    window.setTimeout(() => setToasts((current) => current.filter((item) => item.id !== id)), 4200)
  }, [])
  return <ToastContext.Provider value={notify}>
    {children}
    <div className="toast-stack" aria-live="polite">
      {toasts.map((toast) => <div key={toast.id} className={`toast toast-${toast.tone}`}>
        {toast.tone === 'success' ? <Check size={17} /> : <AlertCircle size={17} />}
        <span>{toast.text}</span>
        <button type="button" aria-label="关闭通知" onClick={() => setToasts((current) => current.filter((item) => item.id !== toast.id))}><X size={15} /></button>
      </div>)}
    </div>
  </ToastContext.Provider>
}
export const useToast = () => useContext(ToastContext)

export function useCollection<T>(path: string) {
  const [data, setData] = useState<T[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const reload = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const result = await api.get<T[]>(path)
      setData(Array.isArray(result) ? result : [])
    } catch (err) {
      setError(errorText(err))
    } finally {
      setLoading(false)
    }
  }, [path])
  useEffect(() => { void reload() }, [reload])
  return { data, loading, error, reload, setData }
}

export function PageHeader({ eyebrow, title, description, action }: {
  eyebrow: string; title: string; description: string; action?: ReactNode
}) {
  return <header className="page-header">
    <div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>
    {action && <div className="page-actions">{action}</div>}
  </header>
}

export function Panel({ title, children, aside, className = '' }: {
  title?: string; children: ReactNode; aside?: ReactNode; className?: string
}) {
  return <section className={`panel ${className}`}>
    {(title || aside) && <div className="panel-header"><h2>{title}</h2>{aside}</div>}
    {children}
  </section>
}

export function StatusBadge({ status }: { status?: string | null }) {
  const raw = (status || 'unknown').toLowerCase()
  const tone = ['healthy', 'online', 'running', 'active', 'enabled', 'ok', 'ready'].includes(raw)
    ? 'good' : ['error', 'failed', 'offline', 'unhealthy', 'unavailable', 'disabled'].includes(raw) ? 'bad' : 'neutral'
  const label: Record<string, string> = {
    healthy: '健康', online: '在线', running: '运行中', active: '已启用', enabled: '已启用',
    ok: '正常', ready: '就绪', error: '错误', failed: '失败', offline: '离线',
    unhealthy: '异常', unavailable: '不可用', disabled: '已停用', pending: '待检查', unknown: '未检查',
  }
  return <span className={`status-badge status-${tone}`}><i />{label[raw] || status || '未知'}</span>
}

export function Busy({ text = '正在读取数据' }: { text?: string }) {
  return <div className="state-card"><LoaderCircle size={22} className="spin" /><span>{text}</span></div>
}
export function Failure({ error, retry }: { error: string; retry?: () => void }) {
  return <div className="state-card state-error"><AlertCircle size={22} /><strong>数据加载失败</strong><span>{error}</span>{retry && <button className="text-button" onClick={retry}>重试</button>}</div>
}
export function Empty({ icon, title, description, action }: {
  icon?: ReactNode; title: string; description: string; action?: ReactNode
}) {
  return <div className="empty-state">
    <div className="empty-icon">{icon || <Plus size={25} />}</div>
    <h3>{title}</h3><p>{description}</p>{action}
  </div>
}

export function Dialog({ open, title, subtitle, onClose, children, size = 'normal' }: {
  open: boolean; title: string; subtitle?: string; onClose: () => void; children: ReactNode; size?: 'normal' | 'wide'
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null
  return <div className="dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <div className={`dialog dialog-${size}`} role="dialog" aria-modal="true" aria-label={title}>
      <header className="dialog-header"><div><div className="eyebrow">NOVERIS / 操作面板</div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div><button className="icon-button" type="button" aria-label="关闭" onClick={onClose}><X size={19} /></button></header>
      {children}
    </div>
  </div>
}

export function ConfirmDialog({ open, title, description, onCancel, onConfirm, busy }: {
  open: boolean; title: string; description: string; onCancel: () => void; onConfirm: () => void; busy?: boolean
}) {
  return <Dialog open={open} title={title} onClose={onCancel}>
    <p className="confirm-copy">{description}</p>
    <div className="dialog-actions"><button className="button button-ghost" onClick={onCancel} disabled={busy}>取消</button><button className="button button-danger" onClick={onConfirm} disabled={busy}>{busy ? <LoaderCircle size={16} className="spin" /> : null}确认删除</button></div>
  </Dialog>
}

export function Field({ label, hint, children, required }: { label: string; hint?: string; children: ReactNode; required?: boolean }) {
  return <label className="field"><span className="field-label">{label}{required && <em>*</em>}</span>{children}{hint && <small>{hint}</small>}</label>
}

export function Select({ children, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <div className="select-wrap"><select {...props}>{children}</select><ChevronDown size={16} /></div>
}

export function SubmitButton({ busy, children, icon }: { busy?: boolean; children: ReactNode; icon?: ReactNode }) {
  return <button className="button button-primary" type="submit" disabled={busy}>{busy ? <LoaderCircle size={16} className="spin" /> : icon}{children}</button>
}

export function FormError({ error }: { error: string }) {
  return error ? <div className="form-error"><AlertCircle size={15} />{error}</div> : null
}

export function dateText(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

export function useMutation() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const run = async (action: () => Promise<unknown>, onSuccess?: () => void) => {
    setBusy(true); setError('')
    try { await action(); onSuccess?.(); return true }
    catch (err) { setError(errorText(err)); return false }
    finally { setBusy(false) }
  }
  return { busy, error, setError, run }
}

export function preventSubmit(handler: () => void) {
  return (event: FormEvent) => { event.preventDefault(); handler() }
}

export type Role = 'admin' | 'operator' | 'viewer'
export type User = { id: number; email: string; name: string; role: Role }
export type Node = {
  id: number; name: string; address: string; port?: number; description?: string | null
  username?: string | null; has_password?: boolean
  last_check_mode?: 'ssh' | 'tcp' | null
  facts?: {
    hostname?: string | null; os?: string | null; kernel?: string | null
    cpu_cores?: number | null; memory_gb?: number | null
    gpus?: Array<{ name?: string | null; memory_mb?: number | null; driver_version?: string | null }>
  } | null
  status: string; last_check_at?: string | null; last_error?: string | null; created_at?: string
}
export type Model = {
  id: number; name: string; model_id: string; description?: string | null
  category?: string | null; source?: string | null; status: string; created_at?: string
}
export type Deployment = {
  id: number; name: string; model_id: number; node_id: number; upstream_url: string
  status: string; last_check_at?: string | null; last_error?: string | null; created_at?: string
}
export type Route = {
  id: number; name: string; model_alias: string; deployment_id: number
  status: string; created_at?: string
}
export type ApiKey = {
  id: number; name: string; prefix: string; status: string; created_at?: string
  secret?: string
}
export type Dashboard = {
  nodes: number; models: number; deployments: number; routes: number
  api_keys: number; healthy_nodes: number; running_deployments: number; recent_requests: number
}
export type Settings = { site_name: string; allow_registration: boolean }
export type SsoConfig = { enabled: boolean; provider_name?: string | null }

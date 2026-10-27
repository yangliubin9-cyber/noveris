# Noveris AI 最小 MVP

根据 `E:\GIT` 中的 Noveris AI 产品文档新建的可运行最小版本。后端使用 FastAPI 和 SQLite，前端使用 React 和 Vite。覆盖注册、登录、重置密码、首页、节点管理、模型市场、模型部署登记、模型转发、模型测试、权限管理、设置、SSO 和个人中心。

## 本地运行

需要 Python 3.11+ 和 Node.js 20+。当前工作区已生成 `backend/.env` 与 `backend/noveris.db`：其中保存站点密钥和已登记节点的加密凭证，**不要用示例文件覆盖现有 `.env`**。在 PowerShell 中分别启动两个终端：

```powershell
cd E:\GIT\noveris-mvp
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

新部署时才复制 `backend/.env.example` 为 `backend/.env`，生成至少 32 字符的随机 `SECRET_KEY` 并妥善保留；更换密钥会使已有会话、API Key 和已加密的节点/上游凭证失效。当前配置的 `DEMO_MODE=1` 只用于本地体验。

```powershell
cd E:\GIT\noveris-mvp\frontend
npm install
npm run dev
```

打开 `http://localhost:5173`。Vite 默认把 `/api` 和 `/v1` 转发到 `http://127.0.0.1:8000`；需要更改后端地址时，设置 `VITE_API_TARGET`。后端交互文档位于 `http://127.0.0.1:8000/docs`。

首次注册的用户自动成为管理员；正式环境应在限制访问的条件下完成首次注册。后续用户由管理员在权限管理中分配角色。数据库默认保存在后端目录的 `noveris.db`，删除这个文件会丢失本地数据。

## 配置

| 环境变量 | 作用 |
| --- | --- |
| `DATABASE_URL` | SQLite 连接串，默认 `sqlite:///./noveris.db`。 |
| `SECRET_KEY` | 会话签名密钥，部署前必须设置为随机值。 |
| `DEMO_MODE` | `1` 时用于本地演示，找回密码接口可返回重置令牌；正式环境设置为 `0`。 |
| `ALLOW_LOOPBACK_UPSTREAMS` | 非演示模式需要连接本机上游服务时设为 `1`；仅对可信的本地环境开启。 |
| `FRONTEND_URL`、`CORS_ORIGINS` | 前端访问地址与允许携带会话 Cookie 的来源。 |
| `FRONTEND_DIST` | 可选的前端构建目录绝对路径；设置后由 FastAPI 提供页面和静态资源。 |
| `BIND_HOST`、`BIND_PORT` | `deploy/noveris.service` 使用的监听地址与端口。 |
| `COOKIE_SECURE` | 正式 HTTPS 环境设为 `1`，使会话 Cookie 只通过 HTTPS 发送。 |
| `SSH_KNOWN_HOSTS` | OpenSSH `known_hosts` 文件的绝对路径；先通过可信渠道核对服务器主机密钥指纹，再把公钥加入该文件。 |
| `SMTP_HOST`、`SMTP_PORT`、`SMTP_USER`、`SMTP_PASSWORD`、`SMTP_FROM`、`SMTP_TLS` | 邮件服务配置；非演示模式通过邮件发送密码重置链接。 |
| `OIDC_DISCOVERY_URL`、`OIDC_CLIENT_ID`、`OIDC_CLIENT_SECRET`、`OIDC_PROVIDER_NAME` | 可选 OIDC 单点登录配置。需先在真实身份提供商中注册应用和回调地址。 |
| `VITE_API_TARGET` | 前端开发代理的后端地址，默认 `http://127.0.0.1:8000`。 |

OIDC 身份提供商中的回调 URI 应与用户启动 SSO 时访问的地址一致。经本地 Vite 代理访问时使用 `http://localhost:5173/api/auth/oidc/callback`；直接访问后端时使用 `http://127.0.0.1:8000/api/auth/oidc/callback`。正式环境同时配置 HTTPS、`COOKIE_SECURE=1` 和准确的 `FRONTEND_URL`、`CORS_ORIGINS`。

## 最小业务流程与边界

1. 注册首位管理员，登录后登记节点和模型。
2. 将**已经运行**的 OpenAI 兼容模型服务地址登记为部署，再创建模型转发路由。`upstream_url` 的主机必须与选中节点的 `address` 一致。此 MVP 为防止 DNS 重绑定，仅接受 IP 地址；`localhost` 只在演示或显式允许本机上游时可用。
3. 创建 API Key，并在模型测试页或通过 `/v1/chat/completions` 验证调用。转发请求会真实发送到已配置的上游服务；没有可用上游时无法获得模型回答。

节点和部署管理只保存现有资源与上游服务的记录，不负责安装模型、启动 GPU 容器或调度硬件。模型市场是本地模型目录。SSO 依赖外部 OIDC 身份提供商；只填写平台内的配置不会创建 IdP。密码重置在演示模式显示一次性令牌，在正式环境需要可用的 SMTP 服务。
管理员在「设置」修改站点名称后，登录页标识与页面顶栏会同步显示新名称。

仅供本地联调，可另开终端运行 `python tests\mock_upstream.py --port 8765`。它模拟 `mock-chat` 模型；登记节点 `127.0.0.1:8765`、模型 ID `mock-chat` 和部署地址 `http://127.0.0.1:8765/v1` 后即可测试转发，不会调用真实模型。

## 添加 SSH 节点

先通过可信渠道核对目标主机的 SSH 指纹，把主机公钥加入 `SSH_KNOWN_HOSTS` 指向的文件；平台不会自动信任未知主机密钥。在「节点管理 → 添加计算节点」填写节点 IP、SSH 端口和已授权的 SSH 用户名。文档专用地址 `192.0.2.10` 仅用于说明，实际操作时应填写自己的节点地址。

密码只在 UI 输入框手动输入，编辑时留空会保留原密码；API 仅显示是否已配置密码。有凭证时「检查连接」会校验主机密钥、SSH 登录并只读采集系统与硬件信息。无凭证时仅探测 TCP 端口，不能视为 SSH 登录成功。保持 `SECRET_KEY` 稳定，否则已有加密凭证无法解密。节点运行数据保存在本地 SQLite 数据库中，不随源码发布。

## 简要部署

构建前端后，将 `FRONTEND_DIST` 设为其 `dist` 目录的绝对路径，FastAPI 即可在同一进程提供静态页面、`/api` 和 `/v1`。生产配置使用 `DEMO_MODE=0`、持久的随机 `SECRET_KEY`，并按需要配置 SMTP、OIDC 与 `SSH_KNOWN_HOSTS`。[systemd 单元](deploy/noveris.service)使用专用非 root 用户，监听 `.env` 中的 `BIND_HOST` 和 `BIND_PORT`。对公网开放前应使用 HTTPS 反向代理，并设置 `COOKIE_SECURE=1`。

## 测试

从项目根目录运行：

```powershell
cd E:\GIT\noveris-mvp
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest -q tests
```

集成测试使用临时 SQLite 数据库和模拟的上游 HTTP 服务，不需要 GPU 或外部模型。

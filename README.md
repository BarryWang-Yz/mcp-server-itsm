# mcp-server-itsm

本项目提供 Ivanti 系统相关的 MCP 工具（`login_ivanti`、`get_ticket_detail`、`get_user_detail`），以 STDIO 管道模式对外提供服务。

---

## 🍀 前置条件

- 已安装 Python ≥ 3.12  
- 已安装 [uv](https://astral.sh/uv)（可选：若本机未安装，后续命令会自动在容器或虚拟环境中下载）  
- Ivanti 平台 API 凭据（tenant、username、password、role）  
- 环境变量配置工具：`python-dotenv`

---

## 📂 目录结构

```plaintext
mcp-server-itsm/
├── Dockerfile
├── README.md
├── docker-compose.yml
├── main.py
├── pyproject.toml
├── src/
│   └── mcp_server_itsm/
│       ├── __init__.py
│       └── server.py
└── uv.lock
```

## 🚀 本地启动步骤（STDIO 模式）

以下所有命令假设你已在同一根目录下 `git clone` 了两个项目（server 与 client），并分别位于：

```bash
/root/path/
├── mcp-server-itsm
└── mcp-client-itsm
```

### 1. 进入服务器项目
cd /root/path/mcp-server-itsm

### 2. 安装依赖并激活虚拟环境
#### 使用 uv 安装并锁定依赖
uv lock
uv sync --locked
#### 激活项目虚拟环境
source .venv/bin/activate

如果尚未安装 uv，可参考官网一键脚本安装：
curl -sSL https://astral.sh/uv/install.sh | sh
.venv 为 uv 创建的本地虚拟环境目录，激活后会自动使用项目依赖。

### 3. 配置环境变量
在项目根目录创建或编辑 .env 文件，至少包含以下内容：
```
.env
```

#### 其他可选配置...
注意：Ivanti 的 tenant、username、password、role 参数在调用工具时通过 MCP 消息传入，不需要在 .env 中配置。

### 4. 启动 MCP Server（STDIO 模式）
uv run src/mcp_server_itsm/server.py --transport stdio
--transport stdio：以标准输入/输出管道方式提供服务

此时服务端已在当前终端等待来自客户端的调用请求。

## 📖 工具说明
login_ivanti(tenant, username, password, role)
登录 Ivanti 并缓存 Session Key。

get_ticket_detail(ticket_number)
获取指定工单详情，需先调用 login_ivanti。

get_user_detail(login_id)
获取指定用户详情，需先调用 login_ivanti。


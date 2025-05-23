# ─── Builder stage ─────────────────────────
FROM python:3.12-slim AS builder
WORKDIR /app

# 安装 curl 和 ca-certificates（用于下载安装 uv）
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv（替换 pip-tools）
RUN curl -sSL https://astral.sh/uv/install.sh | sh  

# 将 uv 二进制放到 PATH
ENV PATH="/root/.local/bin:${PATH}"

# 复制项目依赖清单
COPY pyproject.toml uv.lock ./

# 使用 uv 构建虚拟环境并安装依赖
RUN uv sync --locked

# ─── Final stage ────────────────────────────
FROM python:3.12-slim
WORKDIR /app

# 拷贝 builder 生成的虚拟环境
COPY --from=builder /root/.local/share/uv/.venv /opt/.venv
ENV PATH="/opt/.venv/bin:${PATH}"

# 复制项目源码
COPY . .

# 默认以 stdio 模式运行 server.py
CMD ["uv", "run", "src/mcp_server_itsm/server.py", "--transport", "stdio"]

FROM python:3.11-slim

# —— 系统依赖：编译 & MySQL client ——
RUN apt-get update \
 && apt-get install -y build-essential default-libmysqlclient-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# —— 复制代码并安装依赖 ——
COPY . /app
RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir -e .

EXPOSE 8000

# —— 用 Uvicorn 启动 ASGI App ——
CMD ["uvicorn", "src.mcp_server_itsm.server:app", "--host", "0.0.0.0", "--port", "8000"]

import os
import re
import json
import httpx
import asyncio
import aiomysql
from aiomysql import DictCursor
from typing import Any, Dict, List
# from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv
from fastmcp import FastMCP

# Load environment variables
load_dotenv()

db_pool: aiomysql.Pool | None = None
ivanti_session_key: str | None = None
ivanti_tenant: str | None = None
_rag_query_engine = None
_rag_persist_path = None

mcp_server = FastMCP("UnifiedTools")

# ========== Database Connection Initialization ==========
async def get_db_pool():
    global db_pool
    if db_pool is None:
        db_pool = await aiomysql.create_pool(
            host=os.getenv("DB_HOST"),
            port=int(os.getenv("DB_PORT", 3305)),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            db=os.getenv("DB_NAME"),
            minsize=1, maxsize=10, autocommit=True,
        )
    return db_pool

# ========== General SQL Execution ==========
async def sql_query(query: str, params: tuple = (), *, as_dict: bool = False):
    db_pool = await get_db_pool()
    if not re.match(r"^\s*(select|show|describe|desc|explain)\b", query, re.I):
        raise ValueError("Only read-only queries are permitted.")

    async with db_pool.acquire() as conn:
        cursor_cls = DictCursor if as_dict else aiomysql.Cursor
        async with conn.cursor(cursor_cls) as cur:
            await cur.execute(query, params)
            return await cur.fetchall()

# ========== MCP Tool Definitions ==========
@mcp_server.tool(description="可以将数据库中所有的表格都列举出来，并且能获取所有表格的大致信息。")
async def list_tables() -> List[Dict]:
    """列出当前数据库所有表的精确行数和大小（MB），不依赖 information_schema。"""

    # 1. 列出所有表名
    rows = await sql_query("SHOW TABLES", as_dict=True)
    # 不同 MySQL 客户端返回的字段名可能不同，我们取行中第一个 value
    table_names = [list(r.values())[0] for r in rows]

    # 2. 对每张表并发获取行数和大小
    async def fetch_info(tbl: str) -> Dict:
        # 精确计数
        cnt_res = await sql_query(f"SELECT COUNT(*) AS cnt FROM `{tbl}`", as_dict=True)
        row_count = cnt_res[0]["cnt"]

        # 获取物理大小
        status_res = await sql_query("SHOW TABLE STATUS LIKE %s", params=[tbl], as_dict=True)
        status = status_res[0]
        size_mb = round((status["Data_length"] + status["Index_length"]) / 1024 / 1024, 2)

        return {
            "table_name": tbl,
            "row_count": row_count,
            "size_mb": size_mb,
        }

    # 并发执行，返回列表
    return await asyncio.gather(*(fetch_info(t) for t in table_names))




@mcp_server.tool(description="可以将表格的所有column值都解析出来。请注意：该表格所需参数名为'table'。")
async def describe_table(table: str) -> dict:
    rows = await sql_query(f"SHOW COLUMNS FROM `{table}`", as_dict=True)
    return {
        "columns": [
            {"name": c["Field"], "type": c["Type"], "null": c["Null"], "key": c["Key"]}
            for c in rows
        ]
    }

select_regex = re.compile(r"^select\s.+\sfrom\s.+", re.I | re.S)

@mcp_server.tool(description="可以执行一个安全的SELECT query以确保能够从数据库中调取合理的数据。请注意：该表可所需参数名为'query'。")
async def query_mysql(query: str) -> dict:
    if not select_regex.match(query.strip()):
        raise ValueError("Only SELECT queries are allowed.")
    rows = await sql_query(query, as_dict=True)
    return {"payload": {"query": query, "rows": rows}}

# ========== Ivanti API Tools ==========

@mcp_server.tool(description="可以登录Ivanti系统并获取Session Key。成功登录后会缓存Session Key供后续接口使用。参数需要提供tenant、username、password、role。")
async def login_ivanti(tenant: str, username: str, password: str, role: str) -> str:
    global ivanti_session_key, ivanti_tenant
    async with httpx.AsyncClient() as client:
        try:
            url = f"https://{tenant}/api/rest/authentication/login"
            payload = {"tenant": tenant, "username": username, "password": password, "role": role}
            response = await client.post(url, json=payload, timeout=30.0)
            response.raise_for_status()
            # Parse session key from response
            session_val = None
            try:
                session_val = response.json()
            except Exception:
                session_val = response.text.strip()
            if isinstance(session_val, dict):
                key = None
                if "sessionId" in session_val:
                    key = session_val["sessionId"]
                elif "SessionId" in session_val:
                    key = session_val["SessionId"]
                elif "token" in session_val:
                    key = session_val["token"]
                else:
                    return f"登录成功，但无法解析Session Key: {session_val}"
                session_val = key
            if not isinstance(session_val, str) or session_val == "":
                return "登录失败: 未获取到Session Key"
            # Store session key and tenant globally
            if tenant in session_val:
                ivanti_session_key = session_val
            else:
                ivanti_session_key = f"{tenant}#{session_val}#2"
            ivanti_tenant = tenant
            return "登录成功，Session Key 已缓存。"
        except httpx.HTTPStatusError as e:
            error_msg = ""
            try:
                err_json = e.response.json()
                if isinstance(err_json, dict):
                    if "error" in err_json:
                        error_msg = err_json.get("error")
                    elif "message" in err_json:
                        error_msg = err_json.get("message")
                    else:
                        error_msg = str(err_json)
                else:
                    error_msg = str(err_json)
            except Exception:
                error_msg = e.response.text
            return f"登录失败: HTTP {e.response.status_code} - {error_msg}"
        except Exception as e:
            return f"登录请求异常: {str(e)}"

@mcp_server.tool(description="可以根据工单单号获取Ivanti工单的详细信息。请确保已登录后再调用此工具，参数名为ticket_number。")
async def get_ticket_detail(ticket_number: int) -> dict:
    if not ivanti_session_key:
        return {"error": "未登录Ivanti，请先调用login_ivanti进行登录。"}
    async with httpx.AsyncClient() as client:
        try:
            url = f"https://{ivanti_tenant}/api/odata/businessobject/incidents"
            params = {"$filter": f"incidentnumber eq {ticket_number}"}
            headers = {"Authorization": ivanti_session_key}
            response = await client.get(url, params=params, headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            try:
                err_json = e.response.json()
                error_msg = err_json.get("error") if isinstance(err_json, dict) else str(err_json)
            except Exception:
                error_msg = e.response.text
            return {"error": f"HTTP {e.response.status_code} - {error_msg}"}
        except Exception as e:
            return {"error": f"请求失败: {str(e)}"}

@mcp_server.tool(description="可以根据用户登录ID获取Ivanti用户的详细信息。请确保已登录后再调用此工具，参数名为login_id。")
async def get_user_detail(login_id: str) -> dict:
    if not ivanti_session_key:
        return {"error": "未登录Ivanti，请先调用login_ivanti进行登录。"}
    async with httpx.AsyncClient() as client:
        try:
            url = f"https://{ivanti_tenant}/api/odata/businessobject/employees"
            params = {"$filter": f"LoginID eq '{login_id}'"}
            headers = {"Authorization": ivanti_session_key}
            response = await client.get(url, params=params, headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            try:
                err_json = e.response.json()
                error_msg = err_json.get("error") if isinstance(err_json, dict) else str(err_json)
            except Exception:
                error_msg = e.response.text
            return {"error": f"HTTP {e.response.status_code} - {error_msg}"}
        except Exception as e:
            return {"error": f"请求失败: {str(e)}"}

# ========== Retrieve Augmented Generation ==========
from src.mcp_server_itsm.rag import indexing, create_query_engine
from llama_index.core import StorageContext, load_index_from_storage
from llama_index.embeddings.dashscope import DashScopeEmbedding,DashScopeTextEmbeddingModels

@mcp_server.tool(description="可以创建一个索引，参数名为document_path和persist_path。")
async def build_rag_index(document_path: str = "./docs", persist_path: str = "knowledge_base/test") -> dict:
    try:
        indexing(document_path=document_path, persist_path=persist_path)
        return {"status": "success",
                "message": f"索引已成功创建并存储到 {persist_path}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    
@mcp_server.tool(description="加载以持久化的索引，并创建流式RAG搜索引擎。参数名为persist_path。")
async def init_rag_index(persist_path: str = "knowledge_base/test") -> dict:
    global _rag_query_engine, _rag_persist_path
    try:
        storage_context = StorageContext.from_defaults(persist_dir=persist_path)
        index = load_index_from_storage(storage_context, embed_model=DashScopeEmbedding(
      model_name=DashScopeTextEmbeddingModels.TEXT_EMBEDDING_V2))

        _rag_query_engine = create_query_engine(index)
        _rag_persist_path = persist_path
        return {"status": "success", "message": "RAG索引已成功加载并创建查询引擎。"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    
@mcp_server.tool(description="执行RAG查询。参数为query_str（用户问题）")
async def run_rag_query(query_str: str) -> dict:
    if _rag_query_engine is None or _rag_persist_path is None:
        return {"status": "error", "message": "RAG索引未初始化，请先调用init_rag_index。"}
    
    try:
        response = await _rag_query_engine.query(query_str)
        return {"status": "success", "response": str(response)}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    

app = mcp_server.streamable_http_app(path="/")
# ========== Main Entrypoint ==========
if __name__ == "__main__":
    # mcp_server.run(transport="stdio")
    port = int(os.getenv("PORT", 8000))

    mcp_server.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=port,
    )
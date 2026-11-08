"""MCP server：把 DevOps 工具暴露成标准 MCP 协议，跨框架复用。

任何 MCP 客户端（Claude Desktop / Cursor / 其他 agent 框架）都能通过标准协议
调用这些工具（k8s_* + kb_search），无需依赖 LangChain。逻辑复用 `enterprise_kb.core`
（框架无关的单一真相源），与 LangChain 适配器 `tools.py` 共用同一份实现。

运行（stdio，供 MCP 客户端 spawn）：
    kb mcp

运行（SSE，供远程客户端，默认 0.0.0.0:8000）：
    kb mcp --transport sse --port 8000
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from enterprise_kb.core import k8s, search, web

# 创建 MCP server（名字 + 描述，供 MCP 客户端识别）
mcp = MCPServer(
    name="enterprise-kb",
    title="Enterprise KB DevOps Tools",
    description=(
        "企业知识库 DevOps 助手工具集：查 Kubernetes 集群（kubectl 薄封装）"
        " + 查知识库文档（RAG 混合检索 + 精排）+ 联网搜索补充（Brave）。"
    ),
    version="0.1.0",
)

# 直接把 core 函数注册为 MCP tool（自动继承 name + 签名 + docstring）
mcp.tool()(k8s.k8s_get)
mcp.tool()(k8s.k8s_describe)
mcp.tool()(k8s.k8s_logs)
mcp.tool()(k8s.k8s_events)
mcp.tool()(search.kb_search)
mcp.tool()(web.web_search)


if __name__ == "__main__":
    mcp.run(transport="stdio")

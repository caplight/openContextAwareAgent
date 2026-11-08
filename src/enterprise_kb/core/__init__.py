"""框架无关的核心工具逻辑（单一真相源）。

这里的函数不依赖任何 agent 框架（LangChain / MCP / 等），只做纯业务逻辑：
查集群（kubectl 薄封装）+ 查文档（复用检索链路）。

上层适配器（LangChain `tools.py` / MCP `mcp_server.py` / 未来 Skills）都复用这一层，
保证逻辑只有一份实现。
"""

from enterprise_kb.core import k8s, search, web

__all__ = ["k8s", "search", "web"]

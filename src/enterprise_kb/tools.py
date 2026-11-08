"""DevOps 助手工具集（LangChain 适配层）。

真正的工具逻辑在 `enterprise_kb.core`（框架无关的单一真相源）。这里只做一件事：
把 core 函数包装成 LangChain `StructuredTool`，供 LangGraph ReAct agent 使用。

`@tool` 装饰器内部就是 `StructuredTool.from_function`，这里直接用它，
自动继承 core 函数的签名（类型注解）+ docstring（工具描述），保证与重构前行为一致。

MCP server（`enterprise_kb.mcp_server`）复用同一份 core，逻辑只有一份实现。
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool

from enterprise_kb.core import k8s, search, web


def _wrap(func) -> StructuredTool:
    """从 core 函数生成 LangChain tool（自动继承 name + 签名 + docstring）。"""
    return StructuredTool.from_function(
        func=func,
        name=func.__name__,
        description=func.__doc__,
    )


k8s_get = _wrap(k8s.k8s_get)
k8s_describe = _wrap(k8s.k8s_describe)
k8s_logs = _wrap(k8s.k8s_logs)
k8s_events = _wrap(k8s.k8s_events)
kb_search = _wrap(search.kb_search)
web_search = _wrap(web.web_search)

# 全部工具（agent 的工具池）
ALL_TOOLS = [k8s_get, k8s_describe, k8s_logs, k8s_events, kb_search, web_search]

"""端到端验证 MCP server：stdio 模式连接 + 调用工具。"""

import asyncio
import os

from mcp import StdioServerParameters
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client

PYTHON = "/data/venvs/enterprise-kb/bin/python"


async def main() -> None:
    env = dict(os.environ)
    env.pop("ALL_PROXY", None)
    env.pop("all_proxy", None)

    params = StdioServerParameters(
        command=PYTHON,
        args=["-m", "enterprise_kb.mcp_server"],
        env=env,
        cwd="/mnt/hgfs/VMWareShare/remote_jobs_research/demo",
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("已注册工具:", [t.name for t in tools.tools])

            # 调用 k8s_get（连 KWOK 集群）
            result = await session.call_tool(
                "k8s_get", {"kind": "node", "name": "fake-node-0"}
            )
            text = result.content[0].text if result.content else ""
            print("\n=== k8s_get('node','fake-node-0') 返回 ===")
            print(text[:300])

            # 调用 kb_search（知识库可能为空，验证不报错）
            result2 = await session.call_tool("kb_search", {"query": "OOM 怎么调 limits"})
            text2 = result2.content[0].text if result2.content else ""
            print("\n=== kb_search 返回（前 200 字）===")
            print(text2[:200])


if __name__ == "__main__":
    asyncio.run(main())

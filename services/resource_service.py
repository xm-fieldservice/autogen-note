from __future__ import annotations
from typing import Any, Dict, List, Tuple
from repositories.tools_repo import ToolsRepository
from repositories.mcp_repo import MCPRepository
from repositories.vectorstores_repo import VectorStoresRepository

class ResourceService:
    """聚合 Tools/MCP/VectorStores 的轻量读取与基础校验。"""

    def __init__(self, tools: ToolsRepository | None = None, mcp: MCPRepository | None = None, vs: VectorStoresRepository | None = None):
        self.tools = tools or ToolsRepository()
        self.mcp = mcp or MCPRepository()
        self.vs = vs or VectorStoresRepository()

    # Tools
    def list_tools(self) -> Dict[str, Any]:
        return self.tools.get_registry()

    def get_tool(self, ref: str) -> Dict[str, Any] | None:
        return self.tools.get_tool(ref)

    # MCP
    def list_mcp_servers(self) -> Dict[str, Any]:
        return self.mcp.get_servers()

    def find_mcp_server(self, name: str) -> Dict[str, Any] | None:
        return self.mcp.find_server(name)

    # VectorStores
    def list_vectorstores(self) -> Dict[str, Any]:
        return self.vs.get_registry()

    def get_vectorstore(self, store_id: str) -> Dict[str, Any] | None:
        return self.vs.get_store(store_id)

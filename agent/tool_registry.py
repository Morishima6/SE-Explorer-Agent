from dataclasses import dataclass
from typing import Any, Callable


ToolHandler = Callable[..., Any]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    handler: ToolHandler


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, name: str, description: str, handler: ToolHandler) -> None:
        print(f"[tool_registry] register tool: {name}")
        self._tools[name] = ToolSpec(name=name, description=description, handler=handler)

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def get(self, name: str) -> ToolSpec:
        return self._tools[name]

    def list_tools(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def describe_tools(self) -> str:
        return "\n".join(f"- {tool.name}: {tool.description}" for tool in self.list_tools())

    def run(self, name: str, **kwargs: Any) -> Any:
        print(f"[tool_registry] run tool: {name}, args={kwargs}")
        if not self.has_tool(name):
            return {"success": False, "error": f"Unknown tool: {name}"}
        try:
            return self.get(name).handler(**kwargs)
        except Exception as exc:
            return {"success": False, "error": str(exc), "tool": name}

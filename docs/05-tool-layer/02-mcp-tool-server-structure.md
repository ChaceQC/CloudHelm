# MCP Tool Server 示例结构

> 来源：[设计书 9.5](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：提供自定义 MCP Tool Server 的最小实现参考。
## 实现提醒

示例只展示最小结构，真实实现必须增加路径归一化、权限检查、参数校验、审计、超时和异常处理。

## M5 本地 Registry 形态

M5 尚未启动独立 MCP Tool Server，而是在 `modules/tool-gateway` 中以本地
registry 提供等价声明：

- `ToolDeclaration.name`：工具名，例如 `repo.read_file`。
- `ToolDeclaration.input_model`：Pydantic 参数模型，可导出 JSON Schema。
- `ToolDeclaration.risk_level` / `requires_approval`：执行前风险与审批判断。
- `ToolDeclaration.handler`：通过策略后执行的本地工具函数。

后续接入 MCP 时，应保持现有工具名、参数 schema、风险等级和审计字段兼容。

## 设计书摘录

### 9.5 MCP Tool Server 示例结构

```python
from fastmcp import FastMCP

mcp = FastMCP("repo-tool")

@mcp.tool()
def read_file(path: str) -> dict:
    """Read a UTF-8 text file from current sandbox workspace."""
    # 真实实现需要路径归一化、权限检查、审计
    with open(path, "r", encoding="utf-8") as f:
        return {
            "path": path,
            "content": f.read()
        }

@mcp.tool()
def write_file(path: str, content: str) -> dict:
    """Write a UTF-8 text file in current sandbox workspace."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    return {
        "path": path,
        "written": True
    }

if __name__ == "__main__":
    mcp.run()
```

---

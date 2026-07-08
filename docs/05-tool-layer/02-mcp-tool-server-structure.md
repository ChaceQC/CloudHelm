# MCP Tool Server 示例结构

> 来源：[设计书 9.5](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：提供自定义 MCP Tool Server 的最小实现参考。
## 实现提醒

示例只展示最小结构，真实实现必须增加路径归一化、权限检查、参数校验、审计、超时和异常处理。

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

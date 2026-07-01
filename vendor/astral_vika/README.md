# Astral Vika

`astral_vika` 是一个异步优先的 Vika 维格表 Fusion API Python SDK。它基于 `asyncio`、`httpx` 和 `aiohttp`，为 Python 项目提供空间站、数据表、记录、字段、视图、附件、节点和组织单元相关 API 的封装。

项目最初服务于 AstrBot 与 Vika 的集成，但主包保持为独立 SDK。常见 `vika.py` 使用习惯会尽量保留兼容包装；新的代码建议直接使用异步接口。

## 当前状态

- 版本：`1.1.3`
- Python：`3.8+`
- 主包：`astral_vika`
- MCP：`vika_mcp` 仅作为可选集成，不是默认运行时依赖
- 参考资料：`agent-skills-reference/` 仅用于本地参考，不属于 SDK 包内容

## 安装

```bash
pip install astral-vika
```

运行时依赖由 `pyproject.toml` 声明，包括 `httpx`、`anyio`、`aiohttp` 和 `pydantic`。

## 快速开始

```python
import asyncio
from astral_vika import Vika


async def main():
    async with Vika("your_api_token") as vika:
        datasheet = vika.datasheet("dstXXXXXXXXXXXXXX")
        records = await datasheet.records.all().limit(10).aall()
        for record in records:
            print(record.record_id, record.fields)


asyncio.run(main())
```

## 记录 CRUD

```python
async with Vika("your_api_token") as vika:
    datasheet = vika.datasheet("dstXXXXXXXXXXXXXX")

    created = await datasheet.records.acreate({"标题": "hello"})
    record = created[0]

    fetched = await datasheet.records.aget(record_id=record.record_id)
    await fetched.asave()

    await datasheet.records.aupdate({
        "recordId": record.record_id,
        "fields": {"标题": "updated"},
    })

    await record.adelete()
```

`Record.save()`、`Record.delete()` 和 `RecordBuilder.save()` 仅作为同步兼容包装保留。若当前线程已有事件循环，请使用 `await record.asave()`、`await record.adelete()` 或 `await builder.asave()`。

## 已覆盖能力

- 空间站：列出空间、按名称查找、获取默认空间。
- 数据表：获取实例、创建数据表、列出空间下的数据表、读取字段/视图元信息。
- 记录：查询、分页、排序、字段选择、公式过滤、创建、更新、删除、批量操作。
- 字段和视图：列表、按名称/ID 获取、字段创建/删除、视图类型过滤。
- 附件：上传、下载、流式写入和路径安全校验。
- 节点：节点列表、v2 搜索、按类型过滤、嵌入链接管理。
- 组织单元：成员、角色、团队的读取、创建、更新、删除和常用关系维护。
- MCP 工具层：提供 Vika 连接检查、空间/节点发现、Catalog 缓存检索、schema 读取、记录分页/批量读取和安全 dry-run 写操作。

## 测试

默认测试不需要真实 Vika token：

```bash
python -m pytest -q
```

Live SDK 测试需要设置环境变量：

```bash
set VIKA_API_TOKEN=your_token
set VIKA_WORKBENCH_URL=https://vika.cn/workbench/dst.../viw...
python -m pytest -q tests/test_astral_vika.py
```

若未安装 `vika_mcp`，MCP 测试会自动跳过。

## MCP 能力

`vika_mcp` 是可选工具层，目标是让上层 agent 能可靠调用 Vika，而不是在本项目内实现自然语言语义解析或文档写入。

核心工具包括：

- `vika.healthcheck`：真实检查 Vika API 是否可达。
- `vika.spaces.list`、`vika.nodes.list/search/tree/get`：发现空间、文件夹和表格节点。
- `vika.catalog.refresh/status/search/get/clear`：使用 SQLite 缓存低频变化的空间、节点、表格、字段和视图索引。
- `vika.schema.get`：优先从缓存读取字段和视图结构。
- `vika.records.query/read_all`：分页读取或按上限聚合读取记录。
- 数据表发现统一使用 `vika.nodes.search` 或 `vika.catalog.search`；字段/视图列表统一使用 `vika.schema.get`。
- 写操作默认 `dry_run=true`，只返回 `executed=false` / `preview_only=true` 的预览结果；只有传入 `dry_run=false` 且 `confirm=true` 才真实执行。`confirm=true` 表示调用方已完成上层确认，不是 MCP 自己发起用户确认。

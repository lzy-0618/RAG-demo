#!/usr/bin/env python3
"""用 Dify 自身的 pydantic 节点模型校验 DSL 文件。

必须在 Dify api 容器内运行（依赖 graphon / core 包）：
    docker cp dify/scripts/validate_dsl.py docker-api-1:/tmp/validate_dsl.py
    docker cp dify/dsl/合同审查.yml docker-api-1:/tmp/app.yml
    docker exec -w /app/api -e PYTHONPATH=/app/api docker-api-1 \\
        /app/api/.venv/bin/python /tmp/validate_dsl.py /tmp/app.yml

或直接使用 dify/scripts/validate.sh（自动完成拷贝与执行）。

校验内容：
  1. 节点顶层 type 必须为 custom（Dify 前端按 custom 渲染节点）
  2. 每个节点 data.type 必须是 Dify 已知节点类型，且能通过其 pydantic 模型校验
  3. 边引用的 source/target 节点必须存在
  4. start / end 节点各恰好一个
"""
import sys

import yaml
from core.workflow.nodes.knowledge_retrieval.entities import KnowledgeRetrievalNodeData
from graphon.nodes.answer.entities import AnswerNodeData
from graphon.nodes.code.entities import CodeNodeData
from graphon.nodes.end.entities import EndNodeData
from graphon.nodes.if_else.entities import IfElseNodeData
from graphon.nodes.llm.entities import LLMNodeData
from graphon.nodes.start.entities import StartNodeData
from graphon.nodes.variable_aggregator.entities import VariableAggregatorNodeData

MODELS = {
    "start": StartNodeData,
    "llm": LLMNodeData,
    "code": CodeNodeData,
    "if-else": IfElseNodeData,
    "variable-aggregator": VariableAggregatorNodeData,
    "end": EndNodeData,
    "answer": AnswerNodeData,
    "knowledge-retrieval": KnowledgeRetrievalNodeData,
}


def check(path: str) -> int:
    with open(path, encoding="utf-8") as f:
        dsl = yaml.safe_load(f)
    print(f"=== {path} | version: {dsl.get('version')} | kind: {dsl.get('kind')}")
    graph = dsl["workflow"]["graph"]
    nodes, edges = graph["nodes"], graph["edges"]
    ids = {n["id"] for n in nodes}
    failures = 0

    for node in nodes:
        node_type = node["data"].get("type")
        if node.get("type") != "custom":
            print(f"  FAIL 节点 {node['id']}: 顶层 type 应为 custom，实际 {node.get('type')}")
            failures += 1
        if node_type not in MODELS:
            print(f"  FAIL 节点 {node['id']}: 未知 data.type: {node_type}")
            failures += 1
            continue
        try:
            MODELS[node_type].model_validate(node["data"])
        except Exception as e:  # noqa: BLE001 - 校验脚本需要打印原始 schema 错误
            print(f"  FAIL 节点 {node['id']} ({node_type}) schema 校验失败:")
            print(f"    {str(e)[:600]}")
            failures += 1

    for edge in edges:
        if edge["source"] not in ids or edge["target"] not in ids:
            print(f"  FAIL 边 {edge.get('id')}: 引用了不存在的节点")
            failures += 1

    types = [n["data"]["type"] for n in nodes]
    print(
        f"  节点数: {len(nodes)} | 边数: {len(edges)}"
        f" | start: {types.count('start')} | end: {types.count('end')}"
        f" | answer: {types.count('answer')}"
    )
    if types.count("start") != 1:
        print("  FAIL start 节点数量必须为 1")
        failures += 1
    # workflow 用 end 收尾；advanced-chat（Chatflow）用 answer 收尾
    mode = dsl.get("app", {}).get("mode")
    if mode == "advanced-chat":
        if types.count("answer") < 1:
            print("  FAIL Chatflow 至少需要 1 个 answer 节点")
            failures += 1
    elif types.count("end") != 1:
        print("  FAIL Workflow 的 end 节点数量必须为 1")
        failures += 1

    print("  结果:", "全部通过" if failures == 0 else f"{failures} 项失败")
    return failures


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: validate_dsl.py <dsl.yml> [more.yml ...]", file=sys.stderr)
        sys.exit(2)
    sys.exit(1 if sum(check(p) for p in sys.argv[1:]) else 0)

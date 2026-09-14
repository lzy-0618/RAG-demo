#!/usr/bin/env python3
"""Render a Dify 1.17 DSL as a flow diagram.

Reads the node kind from ``data.type`` (not the top-level ReactFlow ``type``, which is
always ``custom``) and draws the graph as an ASCII tree or Mermaid flowchart.

Usage::

    python scripts/render_flow.py app.yml               # ASCII tree
    python scripts/render_flow.py app.yml --mermaid      # Mermaid (containers as subgraphs)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict, deque
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("PyYAML is required: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

SHORT_TYPE = {
    "start": "START",
    "end": "END",
    "answer": "ANSWER",
    "llm": "LLM",
    "knowledge-retrieval": "KB",
    "if-else": "IF",
    "question-classifier": "CLS",
    "agent": "AGENT",
    "code": "CODE",
    "http-request": "HTTP",
    "iteration": "ITER",
    "loop": "LOOP",
    "variable-aggregator": "AGG",
    "variable-assigner": "AGG",
    "assigner": "SET",
    "template-transform": "TPL",
    "parameter-extractor": "EXTRACT",
    "document-extractor": "DOC",
    "list-operator": "LIST",
    "tool": "TOOL",
    "datasource": "SOURCE",
    "human-input": "HUMAN",
    "iteration-start": "iter-start",
    "loop-start": "loop-start",
    "loop-end": "loop-end",
}

CONTAINER_TYPES = frozenset({"iteration", "loop"})


def load_dsl(path: Path):
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yml", ".yaml"):
        return yaml.safe_load(text)
    return json.loads(text)


def kind_of(node) -> str:
    """The semantic node kind. Falls back to the top-level type for legacy files."""
    data = node.get("data")
    if isinstance(data, dict) and data.get("type"):
        return str(data["type"])
    return str(node.get("type", "?"))


def describe(node) -> str:
    node_id = node.get("id", "?")
    kind = kind_of(node)
    title = (node.get("data") or {}).get("title") or ""
    short = SHORT_TYPE.get(kind, kind.upper())
    return f"[{short}] {node_id}" + (f" — {title}" if title else "")


def handle_tag(handle) -> str:
    return "" if handle in (None, "", "source", "target") else str(handle)


def render_ascii(dsl) -> None:
    graph = (dsl.get("workflow") or {}).get("graph") or {}
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    if not nodes:
        print("(no nodes)")
        return

    by_id = {n.get("id"): n for n in nodes}
    out: dict[str, list[tuple[str, str]]] = defaultdict(list)
    in_degree: dict[str, int] = defaultdict(int)
    for e in edges:
        out[e.get("source")].append((e.get("target"), handle_tag(e.get("sourceHandle"))))
        in_degree[e.get("target")] += 1
    for node_id in by_id:
        in_degree.setdefault(node_id, 0)

    app = dsl.get("app") or {}
    print("=" * 68)
    print(f"{app.get('name', '(unnamed)')}  ·  mode={app.get('mode', '?')}  ·  "
          f"version={dsl.get('version', '?')}")
    print("=" * 68)

    containers = {n["id"]: n for n in nodes if kind_of(n) in CONTAINER_TYPES}
    entries = [nid for nid in by_id if in_degree[nid] == 0]
    start_entries = [nid for nid in entries if kind_of(by_id[nid]) == "start"]
    entries = start_entries or entries
    if not entries:
        print("(no entry node found)")
        return

    printed: set[str] = set()

    def walk(node_id: str, prefix: str, connector: str, branch: str, depth: int) -> None:
        node = by_id.get(node_id)
        if node is None:
            print(f"{prefix}{connector}?? unknown node {node_id}")
            return
        note = f"  ⟨{branch}⟩" if branch else ""
        if node_id in printed:
            print(f"{prefix}{connector}{describe(node)}{note}  ↻ (见上文)")
            return
        printed.add(node_id)
        print(f"{prefix}{connector}{describe(node)}{note}")

        child_prefix = prefix + ("   " if connector in ("└─ ", "") else "│  ")
        children: list[tuple[str, str]] = []
        if kind_of(node) in CONTAINER_TYPES:
            inner_start = (node.get("data") or {}).get("start_node_id")
            if inner_start:
                children.append((inner_start, "container body"))
        children.extend(out.get(node_id, ()))
        for index, (target, tag) in enumerate(children):
            last = index == len(children) - 1
            walk(target, child_prefix, "└─ " if last else "├─ ", tag, depth + 1)

    for index, entry in enumerate(entries):
        walk(entry, "", "└─ " if index == len(entries) - 1 else "├─ ", "", 0)

    orphans = [
        n for n in nodes
        if n.get("id") not in printed
        and kind_of(n) not in CONTAINER_TYPES
        and n.get("parentId") not in containers
        and kind_of(n) not in ("iteration-start", "loop-start", "loop-end")
    ]
    if orphans:
        print("\n不可达（永远不会执行）:")
        for node in orphans:
            print(f"  ! {describe(node)}")

    print("-" * 68)
    print(f"nodes: {len(nodes)}   edges: {len(edges)}   containers: {len(containers)}")
    print(f"[{', '.join(f'{k}:{v}' for k, v in sorted(_kind_counts(nodes).items()))}]")


def _kind_counts(nodes) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for node in nodes:
        counts[kind_of(node)] += 1
    return dict(counts)


def _mermaid_id(node_id: str) -> str:
    return "n_" + "".join(ch if ch.isalnum() else "_" for ch in str(node_id))


def render_mermaid(dsl) -> None:
    graph = (dsl.get("workflow") or {}).get("graph") or {}
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []

    containers = {n["id"]: n for n in nodes if kind_of(n) in CONTAINER_TYPES}
    children: dict[str, list[dict]] = defaultdict(list)
    top_level: list[dict] = []
    for node in nodes:
        parent = node.get("parentId")
        if parent in containers:
            children[parent].append(node)
        elif kind_of(node) not in ("iteration-start", "loop-start", "loop-end"):
            top_level.append(node)

    print("```mermaid")
    print("graph TD")
    for node in top_level:
        node_id = _mermaid_id(node.get("id"))
        title = (node.get("data") or {}).get("title") or ""
        print(f'  {node_id}["<b>{kind_of(node)}</b><br/>{node.get("id")}'
              + (f"<br/><i>{title}</i>" if title else "") + '"]')
        if node.get("id") in containers:
            print(f'  subgraph {node_id}_body["container {node.get("id")}"]')
            for child in children[node["id"]]:
                child_id = _mermaid_id(child.get("id"))
                print(f'    {child_id}["{kind_of(child)}<br/>{child.get("id")}"]')
            print("  end")

    for edge in edges:
        source = _mermaid_id(edge.get("source"))
        target = _mermaid_id(edge.get("target"))
        tag = handle_tag(edge.get("sourceHandle"))
        arrow = f"-- {tag} -->" if tag else "-->"
        extra = []
        data = edge.get("data") or {}
        if data.get("isInIteration"):
            extra.append("iteration")
        if data.get("isInLoop"):
            extra.append("loop")
        print(f"  {source} {arrow} {target}" + (f"  %% {'/'.join(extra)}" if extra else ""))
    print("```")


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a Dify 1.17 DSL as a flow diagram")
    parser.add_argument("path", help="Path to the DSL file")
    parser.add_argument("--mermaid", action="store_true", help="Output Mermaid instead of ASCII")
    args = parser.parse_args()

    path = Path(args.path)
    if not path.exists():
        print(f"file not found: {path}", file=sys.stderr)
        return 2

    dsl = load_dsl(path)
    if not isinstance(dsl, dict):
        print("file is not a DSL object", file=sys.stderr)
        return 2
    if args.mermaid:
        render_mermaid(dsl)
    else:
        render_ascii(dsl)
    return 0


if __name__ == "__main__":
    sys.exit(main())

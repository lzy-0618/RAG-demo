#!/usr/bin/env python3
"""Generate a starter DSL from a bundled template.

Copies a canonical 1.17 template and applies overrides to the app metadata and to
every model-bearing node (llm / question-classifier / parameter-extractor / agent), so
you never have to hand-edit a node envelope.

Usage::

    python scripts/generate_dsl.py --list
    python scripts/generate_dsl.py -t rag-qa -o my-rag.yml --app-name "Policy Bot" \
        --llm-model deepseek-flash
    python scripts/generate_dsl.py -i                        # interactive
    python scripts/generate_dsl.py -t rag-qa --print         # stdout instead of a file

Then::

    python scripts/validate_dsl.py x.yml
    bash scripts/validate.sh x.yml
"""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import yaml
except ImportError:  # pragma: no cover
    print("PyYAML is required: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

from dify_dsl import MODEL_PRESETS  # noqa: E402

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

TEMPLATES = {
    "chatflow-basic": "Single LLM call with conversation memory (chatflow)",
    "rag-qa": "Knowledge-base retrieval with citation cards (chatflow)",
    "workflow-branching": "Classify with an LLM, branch, then merge",
    "agent-with-tools": "Tool-calling agent driven by a plugin strategy",
    "notification-multi": "Severity routing to SMS / IM / email",
    "multi-agent-router": "Intent classification into specialist agents (chatflow)",
    "data-analysis": "Natural-language question to guarded SQL to emailed report",
    "content-generator": "Parallel drafting, assembled brief, write and edit",
    "iteration-loop": "Process every item in a list inside an iteration",
}

#: Node data types that carry a ``model`` block.
MODEL_NODE_TYPES = ("llm", "question-classifier", "parameter-extractor")


def list_templates() -> None:
    print("\nAvailable templates:\n")
    width = max(len(name) for name in TEMPLATES)
    for name, desc in TEMPLATES.items():
        print(f"  {name:<{width}}  {desc}")
    print("\nModel presets:\n  " + ", ".join(sorted(MODEL_PRESETS)))
    print()


def resolve_model(spec: str) -> tuple[str, str] | None:
    """Map a preset name, or ``provider/model``, to a (provider, name) pair."""
    if spec in MODEL_PRESETS:
        return MODEL_PRESETS[spec]
    if "/" in spec:
        provider, _, name = spec.rpartition("/")
        return provider, name
    return None


def normalize_params(provider: str, params: dict) -> dict:
    """Add the provider-specific params that are unsafe to leave at their defaults.

    DeepSeek is the case that matters: if thinking mode is left on, the plugin ignores
    ``temperature`` and writes the reasoning chain into ``llm.text``, burying any JSON
    the node was supposed to return. Verify the model name is one the plugin declares —
    see references/llm-providers.md.
    """
    if provider == "langgenius/deepseek/deepseek":
        params.setdefault("thinking", False)
        params.setdefault("max_tokens", 4096)
        params.pop("top_p", None)
    return params


def apply_overrides(
    dsl: dict,
    *,
    app_name: str | None = None,
    app_description: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    dataset_ids: list[str] | None = None,
) -> dict:
    result = copy.deepcopy(dsl)

    app = result.setdefault("app", {})
    if app_name:
        app["name"] = app_name
    if app_description:
        app["description"] = app_description

    resolved = resolve_model(model) if model else None
    for node in (result.get("workflow") or {}).get("graph", {}).get("nodes", []):
        data = node.get("data") or {}
        kind = data.get("type")

        if resolved and kind in MODEL_NODE_TYPES and isinstance(data.get("model"), dict):
            provider, name = resolved
            data["model"]["provider"] = provider
            data["model"]["name"] = name
            params = data["model"].setdefault("completion_params", {})
            if temperature is not None:
                params["temperature"] = temperature
            normalize_params(provider, params)

        if resolved and kind == "agent":
            # agent_parameters is a MAP, not a list.
            model_param = (data.get("agent_parameters") or {}).get("model")
            if isinstance(model_param, dict) and isinstance(model_param.get("value"), dict):
                provider, name = resolved
                value = model_param["value"]
                value["provider"] = provider
                value["name"] = name
                if isinstance(value.get("completion_params"), dict):
                    normalize_params(provider, value["completion_params"])

        if dataset_ids and kind == "knowledge-retrieval":
            data["dataset_ids"] = list(dataset_ids)

    return result


def run(
    *,
    template: str,
    out: Path | None,
    app_name: str | None,
    app_description: str | None,
    model: str | None,
    temperature: float | None,
    dataset_ids: list[str] | None,
    to_stdout: bool,
) -> int:
    source = TEMPLATES_DIR / f"{template}.yml"
    if not source.exists():
        print(f"template not found: {source}", file=sys.stderr)
        return 2

    dsl = yaml.safe_load(source.read_text(encoding="utf-8"))
    dsl = apply_overrides(
        dsl,
        app_name=app_name,
        app_description=app_description,
        model=model,
        temperature=temperature,
        dataset_ids=dataset_ids,
    )
    rendered = yaml.safe_dump(dsl, allow_unicode=True, sort_keys=False, default_flow_style=False, width=4096)

    if to_stdout or out is None:
        print(rendered, end="")
        return 0

    out.write_text(rendered, encoding="utf-8")
    script_dir = Path(__file__).parent
    print(f"wrote {out}")
    print("next:")
    print(f"  python {script_dir / 'validate_dsl.py'} {out}")
    print(f"  bash {script_dir / 'validate.sh'} {out}")
    print(f"  python {script_dir / 'render_flow.py'} {out}")
    return 0


def interactive() -> int:
    list_templates()
    default_template = next(iter(TEMPLATES))
    template = input(f"Template key [{default_template}]: ").strip() or default_template
    if template not in TEMPLATES:
        print(f"unknown template: {template}", file=sys.stderr)
        return 2
    app_name = input("App name [My App]: ").strip() or "My App"
    app_description = input("Description [Generated from template]: ").strip() or "Generated from template"
    default_model = next(iter(MODEL_PRESETS))
    model = input(f"Model preset [{default_model}]: ").strip() or default_model
    out = input(f"Output file [{template}.yml]: ").strip() or f"{template}.yml"
    return run(
        template=template,
        out=Path(out),
        app_name=app_name,
        app_description=app_description,
        model=model,
        temperature=None,
        dataset_ids=None,
        to_stdout=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a starter Dify 1.17 DSL from a template")
    parser.add_argument("--template", "-t", choices=sorted(TEMPLATES), help="Template to copy")
    parser.add_argument("--out", "-o", help="Output file path")
    parser.add_argument("--app-name", help="Override app.name")
    parser.add_argument("--app-description", help="Override app.description")
    parser.add_argument("--llm-model", help="Model preset (see --list) or provider/model")
    parser.add_argument("--temperature", type=float, help="Override temperature on model nodes")
    parser.add_argument("--dataset-ids", nargs="*", help="Dataset UUIDs for knowledge-retrieval nodes")
    parser.add_argument("--interactive", "-i", action="store_true", help="Prompt for values")
    parser.add_argument("--print", dest="to_stdout", action="store_true", help="Write to stdout")
    parser.add_argument("--list", action="store_true", help="List templates and presets")
    args = parser.parse_args()

    if args.list:
        list_templates()
        return 0
    if args.interactive or not args.template:
        return interactive()

    if args.llm_model and resolve_model(args.llm_model) is None:
        print(
            f"unknown model {args.llm_model!r}; use a preset from --list or 'provider/model'",
            file=sys.stderr,
        )
        return 2

    out = None if args.to_stdout else Path(args.out or f"{args.template}.yml")
    return run(
        template=args.template,
        out=out,
        app_name=args.app_name,
        app_description=args.app_description,
        model=args.llm_model,
        temperature=args.temperature,
        dataset_ids=args.dataset_ids,
        to_stdout=args.to_stdout,
    )


if __name__ == "__main__":
    sys.exit(main())

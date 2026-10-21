#!/usr/bin/env python3
"""Branchback CLI. Run from any worktree; --repo identifies the target project."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

from bb_engine import Engine
from bb_storage import Error, Store


def payload(path):
    try:
        if path == "-":
            value = json.load(sys.stdin)
        else:
            with Path(path).expanduser().open(encoding="utf-8") as stream:
                value = json.load(stream)
    except (ValueError, UnicodeError) as exc:
        raise Error(f"Input is not valid JSON: {exc}") from None
    if not isinstance(value, dict):
        raise Error("Input must be a JSON object")
    return value


def lines_for(label, value):
    if value in (None, "", []):
        return []
    if isinstance(value, list):
        return [label + ":"] + ["  - " + str(v) for v in value]
    return [label + ": " + str(value)]


def render_contract(n):
    out = [f'{n["id"]} [{n["status"]}] {n["question"]}']
    for key in ("scope", "constraints", "sources", "parent_link", "return_when", "case", "coverage", "decision_effect", "notes"):
        out += lines_for(key, n.get(key))
    for assessment in n.get("assessments", []):
        out.append("Parent assessment " + assessment["id"] + " (sources: " + ", ".join(assessment["source_results"]) + "):")
        for key in ("answers", "local_only", "next"):
            out += lines_for(key, assessment[key])
    return out


def render_result(r):
    out = [f'{r["id"]}: {r["summary"]}']
    for key in ("evidence", "conditions", "limitations", "unknowns", "uncovered"):
        out += lines_for(key, r.get(key))
    out.append("execution: " + json.dumps(r["execution"], ensure_ascii=False))
    for n in r.get("unresolved_nodes", []):
        out.append(f'unresolved: {n["id"]} [{n["status"]}] {n["question"]}')
    return out


def render_context(value):
    s, current = value["session"], value["current"]
    out = [f'tree: {value["tree"]} [{value["tree_status"]}]',
           f'session: {s["id"]} ({s["label"]}) [{s["status"]}]; boundary: {s["boundary"]}',
           f'context_token: {value["context_token"]}', "", "Root:"]
    out += render_contract(value["root"])
    for ancestor in value["ancestors"]:
        if ancestor["id"] != value["root"]["id"]:
            out += ["", "Ancestor:"] + render_contract(ancestor)
    out += ["", "Current:"]
    out += render_contract(current) if current["id"] != value["root"]["id"] else [current["id"] + " (root)"]
    if current.get("latest_result"):
        out += ["Latest result:"] + render_result(current["latest_result"])
    groups = [("Children", value["children"]), ("Siblings", value["siblings"])]
    if len(value["ancestors"]) > 1:
        groups.append(("Root branches", value["root_branches"]))
    for title, items in groups:
        if items:
            out += ["", title + ":"]
            for item in items:
                out.append(f'  {item["id"]} [{item["status"]}] {item["question"]}; results={item["results"]}; active={",".join(item["active_sessions"]) or "none"}')
    if value["pending_results"]:
        out += ["", "Returned results awaiting parent assessment (answers, local_only, next):"]
        for p in value["pending_results"]:
            out += [f'Source {p["source_node"]}: {p["question"]}'] + render_result(p["result"])
    if value.get("returned_to"):
        parent = value["returned_to"]["parent"]
        out += ["", f'Delegated boundary returned to {parent["id"]}: {parent["question"]}',
                "Full parent scope is shown above in root/ancestors."]
        out += lines_for("Parent pending result IDs", value["returned_to"]["pending_result_ids"])
        out += [value["next_action"]]
    out += ["", value["detail_note"]]
    return "\n".join(out)


def render(value):
    if "delegation" in value:
        return render_context(value["context"]) + "\n\nSeparate participant context:\n" + render_context(value["delegation"])
    if "context_token" in value:
        return render_context(value)
    return json.dumps(value, ensure_ascii=False, indent=2)


def deduplicate_context(value):
    """Normalize context projections without changing engine state or summarizing text.

    Contracts and branch briefs have different fields even for the same node.
    Keep separate tables so neither projection can overwrite the other.
    Non-context responses retain their existing shape.
    """
    if "context_token" not in value and "delegation" not in value:
        return deepcopy(value)
    contracts, branches = {}, {}

    def reference(table, item):
        identifier = item["id"]
        if identifier in table and table[identifier] != item:
            raise Error(f"Conflicting context projections for {identifier}")
        table[identifier] = item
        return identifier

    def convert(original):
        c = deepcopy(original)
        c["root"] = reference(contracts, c["root"])
        c["ancestors"] = [reference(contracts, n) for n in c["ancestors"]]
        current = c["current"]
        latest = current.pop("latest_result")
        c["current"] = {"node": reference(contracts, current), "latest_result": latest}
        for group in ("children", "siblings", "root_branches"):
            c[group] = [reference(branches, n) for n in c[group]]
        return c

    if "delegation" in value:
        contexts = {"context": convert(value["context"]), "delegation": convert(value["delegation"])}
    else:
        contexts = {"context": convert(value)}
    return {"context_format": "deduplicated-v1", "contracts": contracts, "branches": branches, **contexts}


def parser():
    p = argparse.ArgumentParser(description="Persist exploration branches and recover their parent scope (single-user local state).")
    p.add_argument("--home", help="State root (default BRANCHBACK_HOME or ~/.branchback)")
    p.add_argument("--repo", help="Repository/worktree to inspect (default current directory)")
    p.add_argument("--project-root", help="Explicit project root for non-Git work")
    p.add_argument("--json", action="store_true", help="Return structured output")
    p.add_argument("--context-format", choices=("legacy", "deduplicated"), default="legacy",
                   help="JSON context representation (default: legacy; deduplicated requires --json)")
    sub = p.add_subparsers(dest="command", required=True)
    for name, help_text in (("start", "Start a bounded exploration"), ("enter", "Enter or delegate a child question"),
                            ("return", "Save a scoped result and return/pause"), ("revise", "Revise the current contract with a reason"),
                            ("finish", "Close the root with evidence and uncovered scope"), ("attach", "Attach an independent session or resume one")):
        command = sub.add_parser(name, help=help_text)
        if name != "start":
            command.add_argument("--tree", required=True)
        if name not in ("start", "attach"):
            command.add_argument("--session", required=True)
        command.add_argument("--input", required=True, help="JSON file, or - for stdin")
    read = sub.add_parser("read", help="Read context or list existing work; never creates project state")
    read.add_argument("--tree")
    read.add_argument("--session")
    read.add_argument("--view", choices=("context", "tree", "node", "history"), default="context")
    read.add_argument("--node")
    read.add_argument("--limit", type=int, default=50)
    read.add_argument("--offset", type=int, default=0)
    projects = sub.add_parser("projects", help="List repository mappings or rebind after a local move")
    actions = projects.add_subparsers(dest="project_action", required=True)
    actions.add_parser("list")
    rebind = actions.add_parser("rebind")
    rebind.add_argument("--from-key", required=True, help="Exact old key from projects list")
    return p


def main(argv=None):
    cli_parser = parser()
    args = cli_parser.parse_args(argv)
    if args.context_format == "deduplicated" and not args.json:
        cli_parser.error("--context-format deduplicated requires --json")
    try:
        if args.command == "projects" and args.project_action == "list":
            # Listing the registry must work even outside a Git repository.
            store = Store(home=args.home, project_root=Path.cwd())
            output = store.registry()
        else:
            store = Store(args.home, args.repo, args.project_root)
            engine = Engine(store)
            if args.command == "projects":
                output = store.rebind(args.from_key)
            elif args.command == "read":
                if not 1 <= args.limit <= 1000 or args.offset < 0:
                    raise Error("limit must be between 1 and 1000; offset must be nonnegative")
                output = engine.read(args.tree, args.session, args.view, args.node, args.limit, args.offset)
            else:
                body = payload(args.input)
                if args.command == "start":
                    output = engine.start(body)
                elif args.command == "attach":
                    output = engine.attach(args.tree, body)
                else:
                    action = engine.return_ if args.command == "return" else getattr(engine, args.command)
                    output = action(args.tree, args.session, body)
        if args.context_format == "deduplicated":
            output = deduplicate_context(output)
        print(json.dumps(output, ensure_ascii=False, indent=2) if args.json else render(output))
        return 0
    except (Error, OSError) as exc:
        print(f"branchback: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

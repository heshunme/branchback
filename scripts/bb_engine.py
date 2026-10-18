"""Exploration transitions. All persisted mutations happen under a tree lock."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json

from bb_storage import Error, atomic_json, locked, uid


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def string(body, key, required=True):
    value = body.get(key)
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise Error(f"{key} must be a nonempty string" if required else f"{key} must be a string")
    return value.strip()


def strings(body, key):
    value = body.get(key, [])
    if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
        raise Error(f"{key} must be an array of nonempty strings")
    return value


def fields(body, allowed):
    if not isinstance(body, dict):
        raise Error("Input must be a JSON object")
    extra = set(body) - set(allowed)
    if extra:
        raise Error("Unknown input fields: " + ", ".join(sorted(extra)))


def node(tree, node_id):
    try:
        return tree["nodes"][node_id]
    except (KeyError, TypeError):
        raise Error(f"Unknown node: {node_id}") from None


def session(tree, session_id):
    try:
        return tree["sessions"][session_id]
    except (KeyError, TypeError):
        raise Error(f"Unknown session: {session_id}; read the tree overview to recover IDs") from None


def lineage(tree, node_id):
    result, seen = [], set()
    while node_id is not None:
        if node_id in seen:
            raise Error("Invalid cycle in exploration state")
        seen.add(node_id)
        current = node(tree, node_id)
        result.append(current)
        node_id = current["parent"]
    return list(reversed(result))


def children(tree, node_id):
    return [n for n in tree["nodes"].values() if n["parent"] == node_id]


def pending(tree, node_id):
    reviewed = node(tree, node_id)["reviewed_results"]
    return [{"source_node": child["id"], "question": child["question"], "result": r}
            for child in children(tree, node_id) for r in child["results"] if r["id"] not in reviewed]


def contract(n):
    keys = ("id", "parent", "question", "scope", "constraints", "sources", "parent_link",
            "return_when", "case", "coverage", "decision_effect", "notes", "version", "status")
    value = {k: deepcopy(n[k]) for k in keys if k in n}
    value["assessments"] = [{k: deepcopy(a[k]) for k in ("id", "source_results", "source_nodes", "answers", "local_only", "next")}
                            for a in n["assessments"]]
    return value


def brief(tree, n):
    active = active_under(tree, n["id"])
    return {"id": n["id"], "question": n["question"], "status": n["status"],
            "version": n["version"], "results": len(n["results"]), "active_sessions": active}


def token(tree, s):
    n = node(tree, s["node"])
    # Ancestor content revisions matter; unrelated sibling experiments do not invalidate a leaf.
    value = {"tree": tree["id"], "status": tree["status"], "session": s,
             "path": [(a["id"], a["version"]) for a in lineage(tree, n["id"])],
             "children": [(c["id"], c["version"]) for c in children(tree, n["id"])],
             "pending": [p["result"]["id"] for p in pending(tree, n["id"])]}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]


def context(tree, s):
    n = node(tree, s["node"])
    path = lineage(tree, n["id"])
    parent_id = n["parent"]
    return {"tree": tree["id"], "tree_status": tree["status"], "session": deepcopy(s),
            "context_token": token(tree, s), "root": contract(node(tree, tree["root"])),
            "ancestors": [contract(a) for a in path[:-1]],
            "current": {**contract(n), "latest_result": deepcopy(n["results"][-1]) if n["results"] else None},
            "children": [brief(tree, c) for c in children(tree, n["id"])],
            "siblings": [brief(tree, c) for c in children(tree, parent_id) if c["id"] != n["id"]] if parent_id else [],
            "root_branches": [brief(tree, c) for c in children(tree, tree["root"])],
            "pending_results": deepcopy(pending(tree, n["id"])),
            "detail_note": "Branch bodies and historical results are available via read --view node/history; omitted details still exist."}


def new_node(question, parent=None, **values):
    return {"id": uid("n_"), "parent": parent, "question": question, "status": "open", "version": 1,
            "results": [], "reviewed_results": {}, "assessments": [], **values}


def new_session(n, label, boundary):
    return {"id": uid("s_"), "label": label, "node": n["id"], "boundary": boundary,
            "status": "active", "version": 1}


def event(tree, action, actor, detail, provenance):
    tree["updated_at"] = now()
    tree["events"].append({"at": tree["updated_at"], "action": action, "session": actor,
                           "detail": deepcopy(detail), "execution": provenance})


def result(body, provenance):
    value = body.get("result")
    fields(value, ("summary", "evidence", "conditions", "limitations", "unknowns"))
    return {"id": uid("r_"), "at": now(), "summary": string(value, "summary"),
            **{k: strings(value, k) for k in ("evidence", "conditions", "limitations", "unknowns")},
            "execution": provenance}


def assess(tree, s, body, provenance):
    outstanding = pending(tree, s["node"])
    value = body.get("assessment")
    if outstanding and value is None:
        raise Error("Returned results need a parent assessment: answers, local_only, next. Read context, then include it with this action.")
    if value is None:
        return
    fields(value, ("answers", "local_only", "next"))
    value = {k: string(value, k) for k in ("answers", "local_only", "next")}
    n = node(tree, s["node"])
    record = {"id": uid("a_"), "at": now(), "session": s["id"],
              "source_results": [p["result"]["id"] for p in outstanding],
              "source_nodes": list(dict.fromkeys(p["source_node"] for p in outstanding)),
              **value, "execution": provenance}
    n["assessments"].append(record)
    for item in outstanding:
        n["reviewed_results"][item["result"]["id"]] = record["id"]
    n["version"] += 1


def ready(tree, session_id, body):
    s = session(tree, session_id)
    if tree["status"] != "open" or s["status"] != "active":
        raise Error("Exploration or session is inactive; use attach to resume explicitly")
    if body.get("context_token") != token(tree, s):
        raise Error("Context changed or context_token is missing. Run read for this tree/session and reconsider the action.")
    return s


def active_under(tree, node_id, except_session=None):
    return [s["id"] for s in tree["sessions"].values()
            if s["status"] == "active" and s["id"] != except_session
            and node_id in [n["id"] for n in lineage(tree, s["node"])]]


class Engine:
    def __init__(self, store):
        self.store = store

    def start(self, body):
        fields(body, ("goal", "scope", "constraints", "sources", "label"))
        root = new_node(string(body, "goal"), scope=string(body, "scope"),
                        constraints=strings(body, "constraints"), sources=strings(body, "sources"))
        label = string(body, "label", False) or "primary"
        s = new_session(root, label, root["id"])
        tree = {"schema": 1, "id": uid("t_"), "status": "open", "root": root["id"],
                "created_at": now(), "updated_at": now(), "nodes": {root["id"]: root},
                "sessions": {s["id"]: s}, "events": []}
        event(tree, "start", s["id"], body, self.store.provenance())
        project = self.store.project(create=True)
        path = project / "trees" / (tree["id"] + ".json")
        with locked(path.with_suffix(".lock")):
            if path.exists():
                raise Error("Exploration ID collision; retry start")
            atomic_json(path, tree)
        return context(tree, s)

    def read(self, tree_id=None, session_id=None, view="context", node_id=None, limit=50, offset=0):
        if not tree_id:
            if session_id or node_id or view != "context":
                raise Error("--tree is required for this read")
            return self.store.list_trees()
        tree = self.store.read_tree(tree_id)
        if view == "context" and session_id:
            return context(tree, session(tree, session_id))
        if view == "node":
            if not node_id:
                raise Error("--node is required for read --view node")
            return {"tree": tree_id, "node": deepcopy(node(tree, node_id))}
        if view == "history":
            events = tree["events"]
            return {"tree": tree_id, "total": len(events), "offset": offset,
                    "events": deepcopy(events[offset:offset + limit]),
                    "more": offset + limit < len(events)}
        nodes = list(tree["nodes"].values())
        return {"tree": tree_id, "status": tree["status"], "root": contract(node(tree, tree["root"])),
                "sessions": deepcopy(list(tree["sessions"].values())), "total_nodes": len(nodes),
                "offset": offset, "nodes": [{**brief(tree, n), "parent": n["parent"]} for n in nodes[offset:offset + limit]],
                "more": offset + limit < len(nodes)}

    def attach(self, tree_id, body):
        fields(body, ("node", "label", "boundary", "resume", "reopen_reason"))
        with self.store.transaction(tree_id) as tree:
            if body.get("resume"):
                if any(k in body for k in ("node", "boundary")):
                    raise Error("resume retains its existing node and boundary")
                s = session(tree, string(body, "resume"))
                n = node(tree, s["node"])
            else:
                n = node(tree, body.get("node", tree["root"]))
                boundary = body.get("boundary", tree["root"])
                if boundary not in [a["id"] for a in lineage(tree, n["id"])]:
                    raise Error("Session boundary must be an ancestor of its node")
                s = new_session(n, string(body, "label", False) or "participant", boundary)
                tree["sessions"][s["id"]] = s
            reason = string(body, "reopen_reason", False)
            if tree["status"] == "closed":
                if n["id"] != tree["root"] or not reason:
                    raise Error("Reopen a completed exploration at its root with reopen_reason")
                tree["status"] = "open"
            if n["status"] == "closed" and not reason:
                raise Error("Closed node requires reopen_reason; previous results remain preserved")
            closed_ancestors = [a for a in lineage(tree, n["id"])[:-1] if a["status"] == "closed"]
            if closed_ancestors:
                raise Error("Closed ancestor must be reopened first: " + closed_ancestors[0]["id"])
            if n["status"] != "open":
                n["status"] = "open"
                n["version"] += 1
            s["status"] = "active"
            s["version"] += 1
            if body.get("label"):
                s["label"] = string(body, "label")
            event(tree, "attach", s["id"], body, self.store.provenance())
            output = context(tree, s)
        return output

    def enter(self, tree_id, session_id, body):
        fields(body, ("context_token", "assessment", "node", "question", "parent_link", "return_when",
                      "case", "coverage", "decision_effect", "constraints", "sources", "fork", "label", "reopen_reason"))
        if "fork" in body and not isinstance(body["fork"], bool):
            raise Error("fork must be true or false")
        provenance = self.store.provenance()
        with self.store.transaction(tree_id) as tree:
            s = ready(tree, session_id, body)
            parent = node(tree, s["node"])
            if body.get("node"):
                if any(k in body for k in ("question", "parent_link", "return_when", "case", "coverage", "decision_effect", "constraints", "sources")):
                    raise Error("Existing nodes retain their contract; use revise to change it")
                target = node(tree, body["node"])
                if target["parent"] != parent["id"]:
                    raise Error("enter selects a direct child; return through parents to change branches")
                if target["status"] == "closed" and not string(body, "reopen_reason", False):
                    raise Error("Closed node requires reopen_reason")
            else:
                target = new_node(string(body, "question"), parent["id"],
                                  parent_link=string(body, "parent_link"), return_when=string(body, "return_when"),
                                  constraints=strings(body, "constraints"), sources=strings(body, "sources"))
                for key in ("case", "coverage", "decision_effect"):
                    if key in body:
                        target[key] = string(body, key, False)
                tree["nodes"][target["id"]] = target
            assess(tree, s, body, provenance)
            if target["status"] != "open":
                target["status"] = "open"
                target["version"] += 1
            if body.get("fork"):
                participant = new_session(target, string(body, "label", False) or "participant", target["id"])
                tree["sessions"][participant["id"]] = participant
                s["version"] += 1
                output = {"context": context(tree, s), "delegation": context(tree, participant)}
            else:
                s["node"] = target["id"]
                s["version"] += 1
                output = context(tree, s)
            event(tree, "enter", s["id"], {**body, "entered_node": target["id"]}, provenance)
        return output

    def return_(self, tree_id, session_id, body):
        fields(body, ("context_token", "assessment", "mode", "result"))
        mode = string(body, "mode")
        if mode not in ("paused", "closed"):
            raise Error("mode must be paused or closed")
        provenance = self.store.provenance()
        r = result(body, provenance)
        with self.store.transaction(tree_id) as tree:
            s = ready(tree, session_id, body)
            n = node(tree, s["node"])
            if n["parent"] is None and mode == "closed":
                raise Error("Use finish to close the root, or return with mode paused for a handoff")
            if mode == "closed" and active_under(tree, n["id"], s["id"]):
                raise Error("Other sessions are active in this subtree; have them return/pause before closing it")
            assess(tree, s, body, provenance)
            n["results"].append(r)
            n["version"] += 1
            n["status"] = mode
            s["version"] += 1
            if n["id"] == s["boundary"]:
                s["status"] = "returned" if n["parent"] else "paused"
                output = context(tree, s)
                if n["parent"]:
                    parent = node(tree, n["parent"])
                    # Full parent contracts are already in root/ancestors. The parent
                    # executor reads its own pending results; don't repeat sibling bodies here.
                    output["returned_to"] = {"parent": {k: parent[k] for k in ("id", "question", "status")},
                                             "pending_result_ids": [p["result"]["id"] for p in pending(tree, parent["id"])]}
                    output["next_action"] = "Hand back tree/session/node IDs. The executor of the parent question reviews this result in its own context."
            else:
                s["node"] = n["parent"]
                output = context(tree, s)
            event(tree, "return", s["id"], {"node": n["id"], "mode": mode, "result": r}, provenance)
        return output

    def revise(self, tree_id, session_id, body):
        fields(body, ("context_token", "assessment", "reason", "changes", "sources"))
        reason = string(body, "reason")
        changes = body.get("changes")
        fields(changes, ("question", "scope", "constraints", "sources", "parent_link", "return_when",
                         "case", "coverage", "decision_effect", "notes"))
        if not changes:
            raise Error("changes must contain at least one field")
        for key in changes:
            if key in ("constraints", "sources"):
                strings(changes, key)
            else:
                string(changes, key, key not in ("case", "coverage", "decision_effect", "notes"))
        provenance = self.store.provenance()
        with self.store.transaction(tree_id) as tree:
            s = ready(tree, session_id, body)
            n = node(tree, s["node"])
            if n["id"] == tree["root"] and set(changes) & {"question", "scope", "constraints"} and not strings(body, "sources"):
                raise Error("Changing root scope requires sources for the changed goal or constraints")
            if set(changes) != {"notes"} or body.get("assessment") is not None:
                assess(tree, s, body, provenance)
            if n["id"] == tree["root"] and set(changes) & {"question", "scope", "constraints"}:
                changes = deepcopy(changes)
                changes["sources"] = list(dict.fromkeys(changes.get("sources", n.get("sources", [])) + strings(body, "sources")))
            before = {k: deepcopy(n.get(k)) for k in changes}
            n.update(deepcopy(changes))
            n["version"] += 1
            s["version"] += 1
            event(tree, "revise", s["id"], {"node": n["id"], "reason": reason, "before": before,
                                           "changes": changes, "sources": strings(body, "sources")}, provenance)
            output = context(tree, s)
        return output

    def finish(self, tree_id, session_id, body):
        fields(body, ("context_token", "assessment", "result", "uncovered"))
        provenance = self.store.provenance()
        r = result(body, provenance)
        uncovered = strings(body, "uncovered")
        with self.store.transaction(tree_id) as tree:
            s = ready(tree, session_id, body)
            n = node(tree, s["node"])
            if n["id"] != tree["root"]:
                raise Error("finish is only available at the root; return through the parent questions")
            if active_under(tree, n["id"], s["id"]):
                raise Error("Other sessions are still active; have them return/pause before finishing")
            unresolved = [brief(tree, c) for c in tree["nodes"].values() if c["id"] != n["id"] and c["status"] != "closed"]
            if unresolved and not uncovered:
                raise Error("Open or paused branches remain; describe the uncovered scope in uncovered")
            assess(tree, s, body, provenance)
            r["uncovered"] = uncovered
            r["unresolved_nodes"] = unresolved
            n["results"].append(r)
            n["status"] = "closed"
            n["version"] += 1
            s["status"] = "finished"
            s["version"] += 1
            tree["status"] = "closed"
            event(tree, "finish", s["id"], {"result": r}, provenance)
            output = context(tree, s)
        return output

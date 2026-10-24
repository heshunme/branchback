# CLI reference

Run `python3 <skill-directory>/scripts/branchback.py` on Linux, WSL or macOS with Python 3.10+. Git projects require Git; explicit non-Git projects do not. Native Windows file locking is not implemented.

## Invocation and recovery

```text
branchback.py [--home PATH] [--repo PATH | --project-root PATH] [--json [--context-format legacy|deduplicated]] COMMAND ...
```

Global options precede the command. `--home` defaults to `BRANCHBACK_HOME`, then `~/.branchback`. `--repo` defaults to the current directory. `--project-root` identifies an explicit non-Git project. `--json` returns structured output; ordinary context output is readable text. Exit code 2 reports malformed input, stale context or storage errors on stderr.

`read` without IDs lists project explorations and their sessions. An unregistered project returns an empty list without creating state. No command selects the newest exploration automatically.

| Command | Required options | Purpose |
| --- | --- | --- |
| `start` | `--input FILE` | Create a tree and initial session |
| `read` | Optional `--tree ID --session ID` | Recover context or list existing work |
| `enter` | `--tree ID --session ID --input FILE` | Enter or delegate a child |
| `plan` | Same | Register a question at a specified parent without entering |
| `abandon` | Same | Abandon a question or explicitly selected subtree |
| `restore` | Same | Restore an abandoned question without starting it |
| `handoff` | Same | Pause only the caller's session, keeping the node open |
| `return` | Same | Save a scoped result and return/pause |
| `revise` | Same | Revise the current contract or an unstarted plan with history |
| `finish` | Same | Close at root, retaining uncovered scope |
| `attach` | `--tree ID --input FILE` | Join independently or resume a session |
| `projects list` | None | Read repository keys and state directories |
| `projects rebind` | `--from-key KEY` | Rebind after a local repository move |

`FILE` can be `-` for stdin. Use a quoted heredoc:

```bash
python3 ~/.agents/skills/branchback/scripts/branchback.py --repo /path/to/repo --json --context-format deduplicated start --input - <<'JSON'
{
  "goal": "Choose a retrieval approach for the specified workload",
  "scope": "Compare quality and latency under the project's existing constraints",
  "constraints": ["Preserve existing authorization and data boundaries"],
  "sources": ["docs/requirements.md"],
  "label": "main investigation"
}
JSON
```

Keep the returned tree/session IDs and `context_token`. Mutations return the next context and token, so a separate read is needed only for recovery, intervening work, conflicts or newly available results.

## Node states and parent constraints

`planned` means registered but never started; `open` means started and available for progress; `paused` means the research branch is deferred; `closed` records a scoped conclusion; `abandoned` records a decision not to pursue it. A negative finding can close research; abandonment does not prove experimental failure. Actual execution is tracked separately in sessions.

| Parent state | Allowed direct child states |
| --- | --- |
| `planned` | `planned`, `abandoned` |
| `open` | All five |
| `paused` | `planned`, `paused`, `closed`, `abandoned` |
| `closed` | `planned`, `closed`, `abandoned` |
| `abandoned` | `closed`, `abandoned` |

Every open node and active session must have an open ancestor path. Closing checks the entire subtree, including inactive open nodes and paused descendants. An individual session can hand off while other work continues; pausing a node cannot leave other sessions working in its subtree. Child completion does not automatically change the parent state. Previous results and history survive all transitions.

## Targeted maintenance

`plan` defaults `parent` to the caller's current node. `abandon`, `restore` and `revise` default `node` to the current node. Targeted maintenance must stay within the session's assigned boundary. To act elsewhere, first run:

```text
read --tree TREE --view node --node TARGET
```

This returns the full node, ancestor contracts, `target_token` and `state_warnings`, without moving any session. Pass that `target_token` with the caller's fresh `context_token`. Target tokens cover the target's ancestor versions, subtree revisions and session states. A changed target requires rereading and reconsidering; no operation silently skips a stale check. The caller still needs its own current context.

`plan` returns `planned_node` and a `target_token` for that new node. Targeted `revise` returns `revised_node` and its token; `abandon` returns `abandoned_nodes` and a token for the selected target; `restore` returns `restored_node` and its token. These fields accompany the caller's normal context, so subsequent maintenance can use the returned tokens directly. They remain inline in deduplicated output.

## Deduplicated JSON context

Prefer `--json --context-format deduplicated` for agent context. It is a self-contained representation of the same information, not an incremental response or a generated summary. `--json` alone (or `--context-format legacy`) retains the original format; default text rendering is unchanged. Deduplicated format requires `--json`, checked before executing any command.

Context responses have `context_format: "deduplicated-v1"`, shared `contracts` and `branches` tables keyed by node ID, and a `context` for the caller. A fork also includes `delegation` for the participant, using the same tables. In each context:

- `root` is a contract ID and `ancestors` is an ordered list of contract IDs.
- `current` contains `node` (a contract ID) and `latest_result` (the original result or null).
- `children`, `siblings` and `root_branches` are ordered lists of branch IDs.
- Session, context token, pending results, return instructions and all other context fields are unchanged.

Contracts retain every original field, including all parent assessments. Branches retain the original overview fields, including activity and result counts. A node can appear in both tables: a brief must never replace its full contract. No result text, condition, unknown or evidence link is shortened.

To reconstruct legacy context, resolve `root` and `ancestors` through `contracts`; combine `contracts[current.node]` with `current.latest_result`; resolve the three branch lists through `branches`. A single-context response unwraps `context`; a fork retains the `context`/`delegation` pair. Table entries must be copied if the consumer mutates them.

Project listings, tree/node/history views and project rebind responses are not wrapped in the format envelope. The output format option does not change storage or mutation inputs; use the token inside the relevant context. Recovery needs only tree/session IDs and a fresh `read`: no previous response or table is required. To hand off a fork, pass IDs and let the participant read, or include the shared tables with its context; an isolated `delegation` object is not self-contained. Lifecycle fields, pending updates, warnings and mutation-specific fields are preserved without summarization.

## Input contracts

Input is an object; unknown fields are rejected. Optional arrays default to `[]`. Case information may be omitted or described as unknown. Evidence entries are references, not files copied by the CLI.

### start

Required: `goal`, `scope` (nonempty strings). Optional: `constraints`, `sources` (string arrays), `label` (string).

### plan

Required: `context_token`, `question`, `parent_link`. Optional: `parent` and `target_token` as described above; `return_when`, `case`, `coverage`, `decision_effect`, `notes`, `activation_trigger`, `deferred_because`, `followup_reason` (strings); `constraints`, `sources` (string arrays).

Creates a `planned` node with `started: false`, zero results and no new session. The caller's position and session status are unchanged, and pending results/updates are not assessed. `return_when` can be omitted until the plan is refined; it is required before entering. Triggers are descriptive, not automatic execution conditions or authorization. Dependencies can be referenced in notes/sources; no scheduler is provided.

Under a closed ancestor in an open tree, `followup_reason` is required to explain the new future scope. Existing conclusions remain unchanged. If the original contract is actually incomplete, reopen it instead. Restore abandoned ancestors before adding plans. A completed tree must be explicitly reopened at its root first.

```json
{
  "context_token": "TOKEN_FROM_CALLER_CONTEXT",
  "parent": "TARGET_PARENT_ID",
  "target_token": "TOKEN_FROM_TARGET_NODE_READ",
  "question": "How does this behave on the unmeasured workload?",
  "parent_link": "Extends the coverage of the parent comparison",
  "activation_trigger": "A representative corpus is available",
  "deferred_because": "The corpus is not ready"
}
```

### enter

Required: `context_token`, plus either a new child's `question`, `parent_link`, `return_when` (nonempty strings), or an existing direct child's `node` ID. A closed child requires `reopen_reason`; an abandoned child requires `restore` first. A planned child must have `return_when` before entry; change its contract separately with targeted `revise`. Entering preserves its ID and marks it `open`, `started: true`.

New children may also include `case`, `coverage`, `decision_effect` (strings), `constraints` and `sources` (string arrays). Assumptions need not be known at creation.

Optional `fork: true` creates a separate session bounded to that child, with optional `label`. The response has `context` for the caller and `delegation` for the participant. The caller stays at the parent. Pass participant IDs and worktree through the existing host; the CLI does not start an agent.

Include `assessment` when child results or lifecycle updates await parent review.

### return

Required: `context_token`, `mode` (`paused` or `closed`), and `result`:

```json
{
  "summary": "The measured configuration met the target for this dataset",
  "evidence": ["runs/run-014/metrics.json", "commit:abc123; retained patch:runs/run-014/code.diff"],
  "conditions": ["The tested corpus and parameter configuration"],
  "limitations": ["Other workloads have not been tested"],
  "unknowns": ["Behavior under the untested workload"]
}
```

Only `summary` is mandatory in a result. A paused return can record progress, evidence locations and a resumption point. Do not fabricate evidence or known parameters.

Normally the session moves to its parent. At its assigned boundary it becomes inactive and retains its position; a delegated session receives the parent identity and pending result/update IDs, with full parent scope already in root/ancestors. The parent executor reads its own context to see pending bodies. At the exploration root, only `paused` is allowed; use `finish` to close.

Both pausing and closing refuse other active sessions in the subtree. Have participants `handoff` or return first. A paused return normally refuses open descendants; optional `subtree: true` explicitly pauses those descendants after participants have left. Existing plans, closed nodes and abandoned nodes retain their states. Cascaded pauses create lifecycle updates, not fabricated results. `subtree` is not supported for closed returns.

A closed return rejects all open/paused descendants. If plans remain, supply `uncovered` (string array) explaining their scope; their IDs/states are saved with the result. Describing uncovered scope does not bypass the state restrictions.

If the current node has pending results or lifecycle updates, include a parent assessment before returning further upward.

### abandon

Required: `context_token`, `reason`. Optional: `node`, `target_token`, `subtree` (boolean), `result`, `assessment`.

Only `planned`, `open` or `paused` nodes can be abandoned. Record why work is no longer pursued. A nonterminal descendant requires explicit `subtree: true` or prior individual disposition. The operation marks unfinished nodes in that subtree abandoned, leaving closed nodes and previous abandonments unchanged. Other active sessions must first hand off/return; the tool never kills agents. Return to an ancestor before abandoning its subtree from inside it.

At the caller's current research node, optional `result` can preserve real progress and optional `assessment` can process displayed pending items. A remote target cannot take either field; a planned node never takes a result. Without an assessment, pending items stay unprocessed. Each abandoned node receives a typed lifecycle update with its prior state, reason and execution provenance. Its parent sees it in `pending_updates`; no synthetic research result is created.

Abandoning the current node returns/releases the caller as with `return`. Targeted abandonment elsewhere preserves the caller's position. Abandoning the root makes the exploration `abandoned` and releases the root session; this records termination, not completion of its goal.

### restore

Required: `context_token`, `reason`. Optional: `node`, `target_token`.

Only abandoned nodes can be restored. Known unstarted nodes return to `planned`; started nodes, and legacy nodes with unknown start history, return to `paused`. It neither enters nor starts work. Old results and disposition history remain intact, and the parent receives a `restored` update. Restore necessary ancestors first; restoring a started child under a closed parent is refused. Only the selected node is restored, not abandoned siblings or descendants.

For an abandoned exploration, read and use an existing root session to restore the root. The tree becomes open while the root node/session remain paused. Then `attach` that session to start work again. An inactive non-root session cannot use `restore` to start an independent branch.

### handoff

Required: `context_token`, `reason`. Optional: `result` (real progress), `assessment`.

Pauses only the caller's session, retaining its position and boundary. The node stays open and other sessions may continue. The session retains the handoff reason for recovery. An optional progress result is saved normally; existing pending items are only processed when an assessment is supplied. Resume with `attach {"resume": "s_..."}`. To pause an entire research branch instead, coordinate its participants and use a paused return.

### assessment

Include this object with the next `enter`, `return`, `revise` or `finish`:

```json
{
  "answers": "This establishes feasibility for the measured part of the parent scope",
  "local_only": "The corpus and threshold remain local; broader usefulness is unverified",
  "next": "Evaluate the uncovered workload before recommending a common threshold"
}
```

All three fields are nonempty strings. Assess all pending result and lifecycle-update IDs in the displayed context. The parent saves `source_results`, `source_updates`, source node IDs and reasoning, while original records remain intact. This is a structure check, not validation of reasoning quality.

### revise

Required: `context_token`, `reason`, `changes` (nonempty object). Changes affect the current node, or a `planned` node selected with `node` and `target_token`. Only plans can be revised without entering. Mutable fields are `question`, `scope`, `constraints`, `sources`, `parent_link`, `return_when`, `case`, `coverage`, `decision_effect`, `notes`, `activation_trigger`, `deferred_because`, `followup_reason`. Array fields are `constraints` and `sources`; others are strings. Status, parent identity and started history cannot be changed through `revise`.

Changing root `question`, `scope` or `constraints` also requires a top-level `sources` array for the change's basis. History retains previous values and reasons. This does not grant authorization.

At the current node, pending results/updates need an assessment except for an unrelated `notes`-only edit. Such a note leaves pending items unprocessed. Targeted plan revisions leave the caller's pending items untouched and do not accept an assessment. Do not use maintenance to bypass review when adopting a result.

### finish

Required: `context_token`, `result`. Optional: `uncovered` (string array), `assessment` for pending results/updates. Only a root session can finish. Other active sessions must hand off/return first. Open and paused descendants are rejected even with `uncovered`. Planned branches can remain if `uncovered` explains their scope; their IDs and states are saved with the final result. Abandoned branches remain identifiable with their reasons. Closure does not imply all branches succeeded or delivery was accepted.

### attach

Create a session using optional `node` (default root), `label`, `boundary` (default root, must be an ancestor of the selected node). It returns context before any decision-changing action.

Resume with `{"resume": "s_..."}` to retain the node and boundary; do not supply `node` or `boundary` as well. After compaction, read the existing active session rather than creating a new participant. Attaching starts the target node and requires an open ancestor path. Closed nodes require `reopen_reason`, abandoned nodes require `restore` first, and planned nodes require a complete entry contract. Open ancestors from the top down; the tool never automatically restores a path. A closed exploration must be reopened at its root with a reason. Prior results remain preserved.

## Reading detail

```text
read --tree ID --session ID
read --tree ID --view tree
read --tree ID --view node --node ID
read --tree ID --view history --offset 0 --limit 50
```

Context includes root and ancestor contracts and their prior assessments, the current node and latest result, direct children/siblings, root-branch status, `pending_results`, `pending_updates`, `state_warnings` and the next mutation token. Contracts/briefs expose the latest lifecycle update and known start history; node detail retains all results, updates and assessments. Missing `started` (or null in a brief) means legacy start history is unknown. Branch activity includes sessions in descendant nodes. No extra model summarizes it. Tree and history views are paginated with total counts and `more`; `--limit` is 1–1000 and `--offset` is nonnegative.

Tokens reflect the session position, ancestor revisions and current direct children/results. An unrelated branch's internal experiment need not invalidate a leaf. A changed ancestor or newly returned child result requires rereading and reconsidering the action. There is no force flag.

## Storage and relocation

`projects.json` maps canonical Git common-directory paths to relative state directories. Non-Git keys use `dir:<canonical-project-root>`. Each tree is `trees/<tree-id>.json` containing nodes, sessions, results and history. Local file locks protect short read-modify-write operations; atomic replacement prevents half-written files. There is no database, service or distributed sync.

For an intentional repository move, inspect `projects list`, then use `--repo NEW_PATH projects rebind --from-key OLD_KEY`. State IDs remain unchanged. Rebinding refuses to merge two registered projects; it does not rewrite evidence paths or move artifacts.

Tests should use an isolated `--home`. `read` and `projects list` do not create a registry; first `start` registers the project. Corrupt JSON is reported instead of reset. Automatic worktree/HEAD/dirty metadata does not preserve uncommitted file contents.

New trees use schema 2. Schema 1 remains readable without writes, including historical state combinations that do not meet the new lifecycle rules. `state_warnings` exposes those combinations. Successful writes upgrade the schema number atomically; they do not rewrite old events, results or classify paused nodes as planned. Older CLI versions reject schema 2 rather than silently changing it.

Repair affected legacy branches explicitly. For example, reopen the ancestors of an old closed parent containing a paused child, decide whether to continue/close or abandon that child, then close the parent again under the new rules. Opening an ancestor permits repairing deeper legacy inconsistencies incrementally; state-changing operations validate the affected path and children, and terminal/paused subtree operations validate all affected descendants. Unrelated historical branches are not silently repaired. Unknown start history is preserved; if such a node is abandoned and restored, it conservatively resumes as paused.

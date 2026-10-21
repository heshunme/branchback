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
| `return` | Same | Save a scoped result and return/pause |
| `revise` | Same | Revise the current contract with history |
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

## Deduplicated JSON context

Prefer `--json --context-format deduplicated` for agent context. It is a self-contained representation of the same information, not an incremental response or a generated summary. `--json` alone (or `--context-format legacy`) retains the original format; default text rendering is unchanged. Deduplicated format requires `--json`, checked before executing any command.

Context responses have `context_format: "deduplicated-v1"`, shared `contracts` and `branches` tables keyed by node ID, and a `context` for the caller. A fork also includes `delegation` for the participant, using the same tables. In each context:

- `root` is a contract ID and `ancestors` is an ordered list of contract IDs.
- `current` contains `node` (a contract ID) and `latest_result` (the original result or null).
- `children`, `siblings` and `root_branches` are ordered lists of branch IDs.
- Session, context token, pending results, return instructions and all other context fields are unchanged.

Contracts retain every original field, including all parent assessments. Branches retain the original overview fields, including activity and result counts. A node can appear in both tables: a brief must never replace its full contract. No result text, condition, unknown or evidence link is shortened.

To reconstruct legacy context, resolve `root` and `ancestors` through `contracts`; combine `contracts[current.node]` with `current.latest_result`; resolve the three branch lists through `branches`. A single-context response unwraps `context`; a fork retains the `context`/`delegation` pair. Table entries must be copied if the consumer mutates them.

Project listings, tree/node/history views and project rebind responses keep their original shape, without the format envelope. Storage and mutation inputs are unchanged; use the token inside the relevant context. Recovery needs only tree/session IDs and a fresh `read`: no previous response or table is required. To hand off a fork, pass IDs and let the participant read, or include the shared tables with its context; an isolated `delegation` object is not self-contained.

## Input contracts

Input is an object; unknown fields are rejected. Optional arrays default to `[]`. Case information may be omitted or described as unknown. Evidence entries are references, not files copied by the CLI.

### start

Required: `goal`, `scope` (nonempty strings). Optional: `constraints`, `sources` (string arrays), `label` (string).

### enter

Required: `context_token`, plus either a new child's `question`, `parent_link`, `return_when` (nonempty strings), or an existing direct child's `node` ID. A closed child requires `reopen_reason`; change its contract separately with `revise`.

New children may also include `case`, `coverage`, `decision_effect` (strings), `constraints` and `sources` (string arrays). Assumptions need not be known at creation.

Optional `fork: true` creates a separate session bounded to that child, with optional `label`. The response has `context` for the caller and `delegation` for the participant. The caller stays at the parent. Pass participant IDs and worktree through the existing host; the CLI does not start an agent.

Include `assessment` when child results await parent review.

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

Normally the session moves to its parent. At its assigned boundary it becomes inactive and retains its position; a delegated session receives the parent identity and pending result IDs, with full parent scope already in root/ancestors. The parent executor reads its own context to see pending result bodies. At the exploration root, only `paused` is allowed; use `finish` to close. Closing is refused while another session is active in that subtree. Pausing does not close other participants.

If the current node has pending results, include a parent assessment before returning further upward.

### assessment

Include this object with the next `enter`, `return`, `revise` or `finish`:

```json
{
  "answers": "This establishes feasibility for the measured part of the parent scope",
  "local_only": "The corpus and threshold remain local; broader usefulness is unverified",
  "next": "Evaluate the uncovered workload before recommending a common threshold"
}
```

All three fields are nonempty strings. Assess all pending result IDs in the displayed context. The parent saves the reasoning and source IDs while original results and conditions remain intact. This is a structure check, not validation of reasoning quality.

### revise

Required: `context_token`, `reason`, `changes` (nonempty object). Changes affect only the current node. Mutable fields are `question`, `scope`, `constraints`, `sources`, `parent_link`, `return_when`, `case`, `coverage`, `decision_effect`, `notes`. Array fields are `constraints` and `sources`; others are strings.

Changing root `question`, `scope` or `constraints` also requires a top-level `sources` array for the change's basis. History retains previous values and reasons. This does not grant authorization.

Pending results need an assessment except for an unrelated `notes`-only edit. Such a note leaves pending results unprocessed. Do not use notes to bypass review when adopting a result.

### finish

Required: `context_token`, `result`. Optional: `uncovered` (string array), `assessment` for pending results. Only a root session can finish. Other active sessions must return/pause first. Open or paused branches may remain if `uncovered` explains the scope; their IDs and states are saved with the final result. Closure does not imply all branches succeeded or delivery was accepted.

### attach

Create a session using optional `node` (default root), `label`, `boundary` (default root, must be an ancestor of the selected node). It returns context before any decision-changing action.

Resume with `{"resume": "s_..."}` to retain the node and boundary; do not supply `node` or `boundary` as well. After compaction, read the existing active session rather than creating a new participant. Closed nodes require `reopen_reason`. Closed ancestors must be reopened first, from the highest closed ancestor downward; attaching below one is refused. A closed exploration must be reopened at its root with a reason. Prior results remain preserved.

## Reading detail

```text
read --tree ID --session ID
read --tree ID --view tree
read --tree ID --view node --node ID
read --tree ID --view history --offset 0 --limit 50
```

Context includes root and ancestor contracts and their prior assessments, the current node and latest result, direct children/siblings, root-branch status, pending results and the next mutation token. Branch activity includes sessions in descendant nodes. No extra model summarizes it. Tree and history views are paginated with total counts and `more`; `--limit` is 1–1000 and `--offset` is nonnegative. Node detail retains earlier results and assessments.

Tokens reflect the session position, ancestor revisions and current direct children/results. An unrelated branch's internal experiment need not invalidate a leaf. A changed ancestor or newly returned child result requires rereading and reconsidering the action. There is no force flag.

## Storage and relocation

`projects.json` maps canonical Git common-directory paths to relative state directories. Non-Git keys use `dir:<canonical-project-root>`. Each tree is `trees/<tree-id>.json` containing nodes, sessions, results and history. Local file locks protect short read-modify-write operations; atomic replacement prevents half-written files. There is no database, service or distributed sync.

For an intentional repository move, inspect `projects list`, then use `--repo NEW_PATH projects rebind --from-key OLD_KEY`. State IDs remain unchanged. Rebinding refuses to merge two registered projects; it does not rewrite evidence paths or move artifacts.

Tests should use an isolated `--home`. `read` and `projects list` do not create a registry; first `start` registers the project. Corrupt JSON is reported instead of reset. Automatic worktree/HEAD/dirty metadata does not preserve uncommitted file contents.

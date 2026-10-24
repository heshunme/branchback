---
name: branchback
description: Keep sustained research and experiments tied to their parent questions, evidence, and scope. Use for branching investigations, case-based trials, or research that spans sessions and worktrees; ordinary edits and single checks do not require it.
---

# Branchback

Use a persistent question tree to connect local experiments to the actual task. This is a general tool for the developer's agents: single-user, local, multi-session and multi-worktree. It has no dependency on a delivery skill or the application being developed.

## Recover the exploration

Resolve this skill's directory from the loaded `SKILL.md` path. Run its `scripts/branchback.py` with Python 3.10+ on Linux, WSL or macOS. Pass the actual target repository with `--repo`; the command may run from any directory.

Read [the CLI reference](references/cli.md) when first invoking commands or when inputs are unclear; reuse instructions still available in the current context. For structured context, prefer `--json --context-format deduplicated`; this shares repeated content within each response without omitting it. Global options precede the command. Supply mutation input as a JSON file or through `--input -` with a quoted heredoc; do not interpolate prose into shell syntax.

At the beginning of existing work, or after resumption/compaction, use `read` to recover the tree and session. Without a tree ID, it lists existing work without selecting the latest tree. Keep tree/session IDs in the host's existing handoff or notes; the overview can recover them. Continue the same session for the same execution context; independent agents get separate sessions.

Start a tree for a bounded research goal. Preserve the user's overall purpose, scope, effective constraints and sources in the root. Include the intended use of a local case. If joining halfway through, record what is known and leave missing history unknown. Starting an exploration does not authorize experiments, product changes or external actions beyond the user's task.

## Enter a question, not every operation

Create a child for a separately answerable subproblem whose result needs interpretation at the parent level. Explain its parent link and return condition. Cases, decision effects and detailed assumptions can remain unknown at entry.

Use `plan` for a known question that should exist before work starts. It creates a `planned` node without entering, delegating or producing a research result. Record the parent link and known sources, trigger or deferral reason; complete `return_when` before entering the same node. Plans can be nested. For a different parent, read its node detail and ancestors, then pass its `target_token` alongside your session's `context_token`. Stay within the session boundary. A plan below a closed ancestor needs `followup_reason` explaining its future scope; reopen the ancestor if the old question actually remains unanswered. Revise an unstarted plan by target ID without entering it.

Parameter adjustments, script runs and routine troubleshooting within the same question do not each need a node. Work normally inside the node; use existing logs and fixed artifacts as evidence without a parallel narration after each step. Use `revise` when the question changes or an unrecoverable rationale merits a short note.

Revisit the parent when the return condition is met, the branch no longer changes the parent decision, or a different subproblem is taking over. Before using a case-specific finding as a shared prompt rule, default parameter or general implementation constraint, restore the appropriate parent context and assess that broader use.

## Return results with their scope

`return` saves a result or progress and restores the parent context. Keep detailed reasoning in existing artifacts; record a self-contained conclusion, evidence links, actual conditions, limitations and unknowns rather than copying the report. Completion messages can point to this result without repeating its fields. A paused branch may contain only progress and a resumption point; do not invent experimental parameters or a positive conclusion.

Read the restored root, ancestor constraints, pending results and lifecycle updates before deciding. Include an assessment with the next actual action (`enter`, `return`, `revise` or `finish`):

- `answers`: which part of the parent question the evidence answers;
- `local_only`: which conditions remain local or wider uses remain unverified;
- `next`: the next step and why it advances the parent question.

Assess the pending result and update IDs shown in that context. Source results and conditions remain intact. Plan registration and maintenance leave them pending; do not use maintenance to bypass assessment when adopting a conclusion. A generic acknowledgment is not a scope assessment. The CLI checks structure and context freshness, not reasoning quality.

Use the context and `context_token` returned by the last operation directly; do not immediately repeat `read` unless recovery, intervening changes or new results require it. On a stale token, read and reconsider the action instead of blindly resubmitting old reasoning with a new token. Ancestor edits and new results may change the decision. Read full nodes when the overview is insufficient; omitted detail does not mean a branch was explored or ruled out.

`finish` operates at the root. Closing any node requires descendants to be `planned`, `closed` or `abandoned`; describe remaining plans in `uncovered`. Resolve `open` and `paused` branches before closure, rather than relabeling prior work as `planned`. Closure records the scoped outcome, not experimental success or delivery acceptance. Child completion never automatically closes its parent.

Use `abandon` with a reason when deciding not to pursue a question. It preserves prior evidence and notifies the parent without fabricating a result for an unstarted plan. Unfinished descendants need individual disposition or an explicit `subtree: true` abandonment; completed nodes remain intact. Use `restore` with a reason to reconsider: known unstarted nodes return to `planned`, previously started or historically unknown nodes to `paused`. Restore/open necessary ancestors from the top down, then enter only the selected path.

Pausing a node pauses its branch: no open descendants or other active sessions may remain. After participants hand off, `return` with `mode: paused, subtree: true` can pause remaining open descendants. To leave only your execution context while other work continues, use `handoff` with a resumption reason and optional real progress result; the node stays open. Resume that session using `attach`. The CLI never stops external agents.

## Parallel sessions and worktrees

All worktrees of one local Git repository resolve to one project through its common Git directory. The state lives in `~/.branchback`. The tool never creates worktrees, spawns agents, edits project code or runs experiments.

For an already authorized delegation, `enter` with `fork: true` creates a child session while leaving your position at the parent. Pass the participant the target worktree, tree ID, session ID and this skill. It reads context and works within that subtree. Returning its boundary publishes the result and makes its session inactive. The executor of the parent question reads and reconciles it in its own session.

Independent developer sessions can `attach` to the same tree. Node parentage does not prescribe an agent hierarchy. Positions are independent; write conflicts require rereading. Coordinate code writers through existing project conventions, independently of Branchback.

Record the tested revision and preserve relevant diffs or fixed run artifacts when a worktree is dirty. Automatic HEAD/worktree metadata does not snapshot uncommitted files. Preserve necessary artifacts before worktree cleanup.

## Keep responsibility bounded

JSON stores retain contracts, results, assessments and revision history. `~/.branchback/projects.json` maps repositories to `projects/<name>-<short-id>/`. Use `--home` or `BRANCHBACK_HOME` for isolated trials. `projects rebind` handles intentional local repository moves; matching remotes do not justify merging unrelated clones.

Schema 1 trees remain readable. Successful writes upgrade to schema 2 without classifying old paused nodes or rewriting history. Treat `state_warnings` as legacy inconsistencies to resolve explicitly in the affected branch; old closed nodes with paused descendants need reopening and disposition before closing again. Use the updated CLI for schema 2 state.

Keep product decisions in existing authoritative documents. Research may include prototypes; delivery may expose new research. Reference shared artifacts without requiring phase changes, shared task state or another skill. There is no account system or distributed/cross-machine synchronization.

The tool enforces its own transitions and restores recorded context. It cannot detect every logical branch, verify semantic correctness, guarantee the model read the output or constrain other shell tools. Adjust the workflow using actual outcomes and costs rather than accumulating speculative rules.

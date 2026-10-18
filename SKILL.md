---
name: branchback
description: Keep sustained research and experiments tied to their parent questions, evidence, and scope. Use for branching investigations, case-based trials, or research that spans sessions and worktrees; ordinary edits and single checks do not require it.
---

# Branchback

Use a persistent question tree to connect local experiments to the actual task. This is a general tool for the developer's agents: single-user, local, multi-session and multi-worktree. It has no dependency on a delivery skill or the application being developed.

## Recover the exploration

Resolve this skill's directory from the loaded `SKILL.md` path. Run its `scripts/branchback.py` with Python 3.10+ on Linux, WSL or macOS. Pass the actual target repository with `--repo`; the command may run from any directory.

Read [the CLI reference](references/cli.md) when first invoking commands or when inputs are unclear. Global options precede the command. Supply mutation input as a JSON file or through `--input -` with a quoted heredoc; do not interpolate prose into shell syntax.

At the beginning of existing work, or after resumption/compaction, use `read` to recover the tree and session. Without a tree ID, it lists existing work without selecting the latest tree. Keep tree/session IDs in the host's existing handoff or notes; the overview can recover them. Continue the same session for the same execution context; independent agents get separate sessions.

Start a tree for a bounded research goal. Preserve the user's overall purpose, scope, effective constraints and sources in the root. Include the intended use of a local case. If joining halfway through, record what is known and leave missing history unknown. Starting an exploration does not authorize experiments, product changes or external actions beyond the user's task.

## Enter a question, not every operation

Create a child for a separately answerable subproblem whose result needs interpretation at the parent level. Explain its parent link and return condition. Cases, decision effects and detailed assumptions can remain unknown at entry.

Parameter adjustments, script runs and routine troubleshooting within the same question do not each need a node. Work normally inside the node; use existing logs and fixed artifacts as evidence without a parallel narration after each step. Use `revise` when the question changes or an unrecoverable rationale merits a short note.

Revisit the parent when the return condition is met, the branch no longer changes the parent decision, or a different subproblem is taking over. Before using a case-specific finding as a shared prompt rule, default parameter or general implementation constraint, restore the appropriate parent context and assess that broader use.

## Return results with their scope

`return` saves a result or progress and restores the parent context. Record observations, evidence, actual conditions, limitations and unknowns as available. A paused branch may contain only progress and a resumption point; do not invent experimental parameters or a positive conclusion.

Read the restored root, ancestor constraints and pending results before deciding. Include an assessment with the next actual action (`enter`, `return`, `revise` or `finish`):

- `answers`: which part of the parent question the evidence answers;
- `local_only`: which conditions remain local or wider uses remain unverified;
- `next`: the next step and why it advances the parent question.

Assess the pending result IDs shown in that context. Source results and conditions remain intact. A generic acknowledgment is not a scope assessment. The CLI checks structure and context freshness, not reasoning quality.

Use the returned `context_token` for the next mutation. On a stale token, read and reconsider the action instead of blindly resubmitting old reasoning with a new token. Ancestor edits and new results may change the decision. Read full nodes when the overview is insufficient; omitted detail does not mean a branch was explored or ruled out.

`finish` operates at the root. State the overall result and uncovered scope, including paused or unexamined branches. Closing this record is independent of experimental success or software delivery. Have other active sessions return/pause before closing the tree. To hand off unfinished root work, use `return` with `mode: paused`.

## Parallel sessions and worktrees

All worktrees of one local Git repository resolve to one project through its common Git directory. The state lives in `~/.branchback`. The tool never creates worktrees, spawns agents, edits project code or runs experiments.

For an already authorized delegation, `enter` with `fork: true` creates a child session while leaving your position at the parent. Pass the participant the target worktree, tree ID, session ID and this skill. It reads context and works within that subtree. Returning its boundary publishes the result and makes its session inactive. The executor of the parent question reads and reconciles it in its own session.

Independent developer sessions can `attach` to the same tree. Node parentage does not prescribe an agent hierarchy. Positions are independent; write conflicts require rereading. Coordinate code writers through existing project conventions, independently of Branchback.

Record the tested revision and preserve relevant diffs or fixed run artifacts when a worktree is dirty. Automatic HEAD/worktree metadata does not snapshot uncommitted files. Preserve necessary artifacts before worktree cleanup.

## Keep responsibility bounded

JSON stores retain contracts, results, assessments and revision history. `~/.branchback/projects.json` maps repositories to `projects/<name>-<short-id>/`. Use `--home` or `BRANCHBACK_HOME` for isolated trials. `projects rebind` handles intentional local repository moves; matching remotes do not justify merging unrelated clones.

Keep product decisions in existing authoritative documents. Research may include prototypes; delivery may expose new research. Reference shared artifacts without requiring phase changes, shared task state or another skill. There is no account system or distributed/cross-machine synchronization.

The tool enforces its own transitions and restores recorded context. It cannot detect every logical branch, verify semantic correctness, guarantee the model read the output or constrain other shell tools. Adjust the workflow using actual outcomes and costs rather than accumulating speculative rules.

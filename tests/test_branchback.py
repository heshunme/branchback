import concurrent.futures
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from bb_storage import Error, Store, atomic_json
from bb_engine import Engine

CLI = SCRIPTS / "branchback.py"
ASSESSMENT = {"answers": "Only the measured case is supported", "local_only": "The threshold remains local",
              "next": "Investigate the unmeasured case before generalizing"}
RESULT = {"summary": "Candidate reduced measured errors", "evidence": ["runs/001/result.json"],
          "conditions": ["Dataset A, threshold 0.4"], "limitations": ["Dataset B untested"]}


class BranchbackTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="branchback-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.home = self.base / "state"
        self.store = Store(self.home, project_root=self.repo)
        self.engine = Engine(self.store)

    def start(self):
        return self.engine.start({"goal": "Compare approaches for all supported modes", "scope": "Two workloads",
                                  "constraints": ["Preserve the offline path"], "sources": ["user request"]})

    def action(self, action, c, **body):
        return getattr(self.engine, action)(c["tree"], c["session"]["id"],
                                           {"context_token": c["context_token"], **body})

    def enter(self, c, **body):
        return self.action("enter", c, question="Measure candidate A", parent_link="Compare feasibility",
                           return_when="Enough evidence to decide the next comparison", **body)

    def refresh(self, c):
        return self.engine.read(c["tree"], c["session"]["id"])

    def git(self, *args, cwd=None):
        result = subprocess.run(["git", "-C", str(cwd or self.repo), *args], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def git_repo(self):
        self.git("init", "-b", "main")
        (self.repo / "fixture.txt").write_text("fixture\n")
        self.git("add", "fixture.txt")
        self.git("-c", "user.name=Branchback Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture")
        self.store = Store(self.home, self.repo)
        self.engine = Engine(self.store)

    def cli(self, command, body=None, repo=None, git=False):
        location = ["--repo", str(repo or self.repo)] if git else ["--project-root", str(repo or self.repo)]
        args = [sys.executable, str(CLI), "--home", str(self.home), *location, "--json", *command]
        if body is not None:
            args += ["--input", "-"]
        return subprocess.run(args, input=json.dumps(body) if body is not None else None,
                              text=True, capture_output=True, timeout=20)

    def test_read_does_not_create_state(self):
        self.assertEqual(self.engine.read()["trees"], [])
        self.assertFalse(self.home.exists())

    def test_complete_return_assessment_and_provenance(self):
        root = self.start()
        child = self.enter(root)
        back = self.action("return_", child, mode="closed", result=RESULT)
        self.assertEqual(back["current"]["id"], root["current"]["id"])
        self.assertEqual(back["root"]["constraints"], ["Preserve the offline path"])
        self.assertEqual(back["pending_results"][0]["result"]["conditions"], RESULT["conditions"])
        path = self.store.tree_path(root["tree"])
        before = path.read_bytes()
        with self.assertRaisesRegex(Error, "assessment"):
            self.action("finish", back, result={"summary": "Limited evidence only"})
        self.assertEqual(path.read_bytes(), before)
        done = self.action("finish", back, assessment=ASSESSMENT, result={"summary": "Limited evidence only"},
                           uncovered=["Workload B not evaluated"])
        self.assertEqual(done["tree_status"], "closed")
        tree = self.store.read_tree(root["tree"])
        parent = tree["nodes"][tree["root"]]
        self.assertEqual(parent["assessments"][0]["source_nodes"], [child["current"]["id"]])
        self.assertEqual(tree["nodes"][child["current"]["id"]]["results"][0]["conditions"], RESULT["conditions"])

    def test_deep_context_preserves_root_and_parent(self):
        root = self.start()
        parent = self.enter(root, case="Dataset A only")
        leaf = self.enter(parent)
        self.assertEqual(len(leaf["ancestors"]), 2)
        self.assertEqual(leaf["ancestors"][1]["case"], "Dataset A only")
        self.assertEqual(leaf["root"]["scope"], "Two workloads")

    def test_pause_and_resume_without_fabricated_experiment(self):
        root = self.start()
        paused = self.action("return_", root, mode="paused", result={"summary": "Need to inspect fixtures next"})
        self.assertEqual(paused["session"]["status"], "paused")
        self.assertEqual(paused["current"]["latest_result"]["evidence"], [])
        resumed = self.engine.attach(root["tree"], {"resume": root["session"]["id"]})
        self.assertEqual(resumed["session"]["status"], "active")
        self.assertEqual(resumed["session"]["id"], root["session"]["id"])
        self.assertIn("Need to inspect", resumed["current"]["latest_result"]["summary"])

    def test_reopen_retains_results_and_requires_reason(self):
        root = self.start()
        done = self.action("finish", root, result={"summary": "No useful evidence"})
        with self.assertRaisesRegex(Error, "Reopen"):
            self.engine.attach(root["tree"], {"resume": root["session"]["id"]})
        c = self.engine.attach(root["tree"], {"resume": root["session"]["id"], "reopen_reason": "New dataset supplied"})
        self.assertEqual(c["current"]["latest_result"]["summary"], done["current"]["latest_result"]["summary"])
        self.assertEqual(c["tree_status"], "open")

    def test_root_revision_preserves_old_values_and_invalidates_leaf(self):
        root = self.start()
        leaf = self.enter(root)
        other = self.engine.attach(root["tree"], {"label": "parent maintainer"})
        with self.assertRaisesRegex(Error, "sources"):
            self.action("revise", other, reason="Request changed", changes={"scope": "Now three workloads"})
        updated = self.action("revise", other, reason="Request changed", changes={"scope": "Now three workloads"}, sources=["new user request"])
        with self.assertRaisesRegex(Error, "Context changed"):
            self.action("return_", leaf, mode="paused", result={"summary": "Progress"})
        history = self.engine.read(root["tree"], view="history")["events"]
        self.assertEqual(history[-1]["detail"]["before"]["scope"], "Two workloads")
        self.assertEqual(updated["root"]["scope"], "Now three workloads")
        self.assertIn("new user request", updated["root"]["sources"])

    def test_parent_assessment_is_restored_inside_next_branch(self):
        root = self.start()
        child = self.enter(root)
        back = self.action("return_", child, mode="closed", result=RESULT)
        next_branch = self.enter(back, assessment=ASSESSMENT)
        self.assertEqual(next_branch["root"]["assessments"][0]["local_only"], ASSESSMENT["local_only"])
        self.assertEqual(next_branch["root"]["assessments"][0]["source_nodes"], [child["current"]["id"]])

    def test_overview_reports_activity_below_an_ancestor(self):
        root = self.start()
        parent = self.enter(root)
        leaf = self.enter(parent, fork=True)
        view = self.engine.read(root["tree"], view="tree")
        branch = next(n for n in view["nodes"] if n["id"] == parent["current"]["id"])
        self.assertIn(leaf["delegation"]["session"]["id"], branch["active_sessions"])

    def test_missing_registered_state_is_not_silently_recreated(self):
        self.start()
        project = self.store.project()
        registry_before = (self.home / "projects.json").read_bytes()
        shutil.rmtree(project)
        with self.assertRaisesRegex(Error, "missing"):
            self.start()
        self.assertFalse(project.exists())
        self.assertEqual((self.home / "projects.json").read_bytes(), registry_before)

    def test_notes_do_not_clear_pending_results(self):
        root = self.start()
        child = self.enter(root)
        back = self.action("return_", child, mode="closed", result=RESULT)
        noted = self.action("revise", back, reason="Remember an artifact", changes={"notes": "A separate fixture exists"})
        self.assertEqual(len(noted["pending_results"]), 1)
        with self.assertRaisesRegex(Error, "assessment"):
            self.enter(noted)

    def test_parallel_positions_and_unrelated_leaf_progress(self):
        root = self.start()
        fork_a = self.enter(root, fork=True, label="A")
        fork_b = self.enter(fork_a["context"], fork=True, label="B")
        a, b = fork_a["delegation"], fork_b["delegation"]
        a_back = self.action("return_", a, mode="closed", result=RESULT)
        self.assertEqual(a_back["session"]["status"], "returned")
        b_progress = self.action("revise", b, reason="Record irrecoverable rationale", changes={"notes": "Chose this fixture for its unusual script"})
        self.assertEqual(b_progress["current"]["id"], b["current"]["id"])
        main = self.refresh(fork_b["context"])
        self.assertEqual(main["current"]["id"], root["current"]["id"])
        self.assertEqual(len(main["pending_results"]), 1)
        with self.assertRaisesRegex(Error, "Other sessions"):
            self.action("finish", main, assessment=ASSESSMENT, result={"summary": "Not yet complete"})
        b_back = self.action("return_", b_progress, mode="closed", result={"summary": "B remains inconclusive", "unknowns": ["Insufficient samples"]})
        self.assertEqual(b_back["returned_to"]["parent"]["id"], root["current"]["id"])
        with self.assertRaisesRegex(Error, "Context changed"):
            self.action("finish", main, assessment=ASSESSMENT, result={"summary": "Old reasoning"})
        main = self.refresh(main)
        self.assertEqual(len(main["pending_results"]), 2)
        done = self.action("finish", main, assessment=ASSESSMENT, result={"summary": "Comparison is limited"})
        self.assertEqual(done["tree_status"], "closed")

    def test_delegated_session_cannot_continue_above_boundary(self):
        root = self.start()
        child = self.enter(root, fork=True)["delegation"]
        returned = self.action("return_", child, mode="closed", result=RESULT)
        self.assertEqual(returned["session"]["node"], child["current"]["id"])
        with self.assertRaisesRegex(Error, "inactive"):
            self.action("revise", returned, reason="Attempt parent edit", changes={"question": "Replace goal"})

    def test_finish_allows_explicitly_uncovered_paused_branch(self):
        root = self.start()
        child = self.enter(root)
        back = self.action("return_", child, mode="paused", result={"summary": "No experiment executed"})
        with self.assertRaisesRegex(Error, "uncovered"):
            self.action("finish", back, assessment=ASSESSMENT, result={"summary": "Partial exploration"})
        done = self.action("finish", back, assessment=ASSESSMENT, result={"summary": "Partial exploration"}, uncovered=["Candidate A remains untested"])
        self.assertEqual(done["current"]["latest_result"]["unresolved_nodes"][0]["status"], "paused")

    def test_child_cannot_be_closed_while_descendant_is_active(self):
        parent = self.enter(self.start())
        fork = self.enter(parent, fork=True)
        with self.assertRaisesRegex(Error, "Other sessions"):
            self.action("return_", fork["context"], mode="closed", result=RESULT)

    def test_resume_descendant_requires_reopening_closed_ancestor(self):
        parent = self.enter(self.start())
        fork = self.enter(parent, fork=True)
        leaf = self.action("return_", fork["delegation"], mode="paused", result={"summary": "Awaiting fixtures"})
        root = self.action("return_", self.refresh(fork["context"]), mode="closed",
                           assessment=ASSESSMENT, result={"summary": "Branch deferred based on current evidence"})
        path = self.store.tree_path(root["tree"])
        before = path.read_bytes()
        for body in ({"resume": leaf["session"]["id"]},
                     {"node": leaf["current"]["id"], "reopen_reason": "New fixture"}):
            with self.assertRaisesRegex(Error, "Closed ancestor"):
                self.engine.attach(root["tree"], body)
        self.assertEqual(path.read_bytes(), before)
        self.action("enter", root, node=parent["current"]["id"],
                    reopen_reason="New fixture changes the parent decision", assessment=ASSESSMENT)
        resumed = self.engine.attach(root["tree"], {"resume": leaf["session"]["id"]})
        self.assertEqual(resumed["session"]["status"], "active")
        self.assertEqual(resumed["current"]["latest_result"]["summary"], "Awaiting fixtures")

    def test_each_return_revision_remains_pending_until_assessed(self):
        root = self.start()
        delegated = self.enter(root, fork=True)["delegation"]
        paused = self.action("return_", delegated, mode="paused", result={"summary": "First measurement"})
        resumed = self.engine.attach(root["tree"], {"resume": paused["session"]["id"]})
        self.action("return_", resumed, mode="closed", result={"summary": "Second measurement"})
        main = self.refresh(root)
        self.assertEqual(len(main["pending_results"]), 2)

    def test_bad_input_and_failed_transition_leave_tree_unchanged(self):
        root = self.start()
        path = self.store.tree_path(root["tree"])
        before = path.read_bytes()
        with self.assertRaisesRegex(Error, "Unknown input"):
            self.action("enter", root, qusetion="Typo")
        with self.assertRaisesRegex(Error, "parent_link"):
            self.action("enter", root, question="Incomplete", return_when="Later")
        self.assertEqual(path.read_bytes(), before)

    def test_unknown_project_invalid_start_does_not_register(self):
        with self.assertRaises(Error):
            self.engine.start({"goal": "Missing scope"})
        self.assertFalse(self.home.exists())

    def test_corrupt_registry_is_not_overwritten(self):
        self.home.mkdir()
        path = self.home / "projects.json"
        path.write_text("{broken")
        with self.assertRaisesRegex(Error, "not reset"):
            self.start()
        self.assertEqual(path.read_text(), "{broken")

    def test_registry_rejects_path_traversal(self):
        self.home.mkdir()
        (self.home / "projects.json").write_text(json.dumps({self.store.key: "../outside"}))
        with self.assertRaisesRegex(Error, "Invalid projects"):
            self.engine.read()

    def test_tree_identifier_rejects_path_traversal(self):
        self.start()
        with self.assertRaisesRegex(Error, "identifier"):
            self.store.read_tree("../../projects")

    def test_atomic_replace_failure_preserves_old_json(self):
        path = self.base / "state.json"
        atomic_json(path, {"original": True})
        with patch("bb_storage.os.replace", side_effect=OSError("simulated interrupted replacement")):
            with self.assertRaises(OSError):
                atomic_json(path, {"original": False})
        self.assertEqual(json.loads(path.read_text()), {"original": True})
        self.assertEqual(list(self.base.glob(".state.json.*")), [])

    def test_local_rebind_preserves_state_directory(self):
        root = self.start()
        old_key, old_path = self.store.key, self.store.project()
        moved = self.base / "moved"
        self.repo.rename(moved)
        new_store = Store(self.home, project_root=moved)
        new_store.rebind(old_key)
        self.assertEqual(new_store.project(), old_path)
        self.assertEqual(new_store.list_trees()["trees"][0]["id"], root["tree"])
        self.assertNotIn(old_key, new_store.registry())

    def test_distinct_same_name_projects_do_not_collide(self):
        self.start()
        other = self.base / "elsewhere" / "repo"
        other.mkdir(parents=True)
        other_store = Store(self.home, project_root=other)
        Engine(other_store).start({"goal": "Different project", "scope": "Independent"})
        self.assertNotEqual(self.store.project(), other_store.project())
        with self.assertRaisesRegex(Error, "already has"):
            other_store.rebind(self.store.key)

    def test_worktrees_share_registry_and_capture_revision(self):
        self.git_repo()
        root = self.start()
        worktree = self.base / "other-worktree"
        self.git("worktree", "add", "-b", "experiment", str(worktree))
        other = Store(self.home, worktree)
        self.assertEqual(other.key, self.store.key)
        self.assertEqual(other.project(), self.store.project())
        (worktree / "fixture.txt").write_text("modified\n")
        peer = Engine(other).attach(root["tree"], {"label": "other checkout"})
        tree = other.read_tree(root["tree"])
        metadata = tree["events"][-1]["execution"]
        self.assertEqual(metadata["worktree"], str(worktree))
        self.assertTrue(metadata["dirty"])
        self.assertEqual(metadata["head"], self.git("rev-parse", "HEAD"))
        self.assertNotEqual(peer["session"]["id"], root["session"]["id"])

    def test_concurrent_process_registration_keeps_all_trees(self):
        def launch(_):
            return self.cli(["start"], {"goal": "Concurrent exploration", "scope": "Separate tree"})
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            outputs = list(pool.map(launch, range(12)))
        self.assertTrue(all(o.returncode == 0 for o in outputs), [o.stderr for o in outputs])
        self.assertEqual(len(self.store.registry()), 1)
        self.assertEqual(len(self.engine.read()["trees"]), 12)

    def test_concurrent_same_session_rejects_stale_action(self):
        root = self.start()
        args = ["enter", "--tree", root["tree"], "--session", root["session"]["id"]]
        body = {"context_token": root["context_token"], "question": "Concurrent branch", "parent_link": "Compare", "return_when": "Evidence available"}
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            outputs = list(pool.map(lambda _: self.cli(args, body), range(2)))
        self.assertEqual(sorted(o.returncode for o in outputs), [0, 2])
        self.assertIn("Context changed", next(o.stderr for o in outputs if o.returncode))
        self.assertEqual(len(self.store.read_tree(root["tree"])["nodes"]), 2)

    def test_concurrent_different_nodes_preserve_both_results(self):
        root = self.start()
        a = self.enter(root, fork=True)
        b = self.enter(a["context"], fork=True)
        def save(c):
            return self.cli(["return", "--tree", c["tree"], "--session", c["session"]["id"]],
                            {"context_token": c["context_token"], "mode": "closed", "result": RESULT})
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            outputs = list(pool.map(save, [a["delegation"], b["delegation"]]))
        self.assertTrue(all(o.returncode == 0 for o in outputs), [o.stderr for o in outputs])
        self.assertEqual(len(self.refresh(root)["pending_results"]), 2)

    def test_cli_recovery_and_error_output(self):
        started = self.cli(["start"], {"goal": "Observe a problem", "scope": "Bounded"})
        self.assertEqual(started.returncode, 0, started.stderr)
        root = json.loads(started.stdout)
        recovered = self.cli(["read", "--tree", root["tree"], "--session", root["session"]["id"]])
        self.assertEqual(json.loads(recovered.stdout)["context_token"], root["context_token"])
        failed = self.cli(["read", "--tree", "missing"])
        self.assertEqual(failed.returncode, 2)
        self.assertNotIn("Traceback", failed.stderr)

    def test_history_and_tree_pagination_explicit(self):
        root = self.start()
        self.enter(root, fork=True)
        view = self.engine.read(root["tree"], view="tree", limit=1)
        self.assertEqual(view["total_nodes"], 2)
        self.assertTrue(view["more"])
        history = self.engine.read(root["tree"], view="history", limit=1)
        self.assertEqual(history["total"], 2)
        self.assertTrue(history["more"])


if __name__ == "__main__":
    unittest.main()

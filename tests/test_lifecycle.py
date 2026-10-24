"""Behavioral coverage for planned questions and bounded lifecycle transitions."""

from copy import deepcopy
import concurrent.futures
import json

from test_branchback import BranchbackFixture, ASSESSMENT, RESULT, expand_context
from bb_engine import state_issues
from bb_storage import Error, atomic_json
from branchback import deduplicate_context, render


class LifecycleTest(BranchbackFixture):
    def plan(self, c, **body):
        return self.action("plan", c, question="A future experiment", parent_link="Resolve an uncovered case", **body)

    def aimed(self, c, nid):
        detail = self.engine.read(c["tree"], view="node", node_id=nid)
        return {"node": nid, "target_token": detail["target_token"]}

    def assert_unchanged(self, c, fn, message):
        path = self.store.tree_path(c["tree"])
        before = path.read_bytes()
        with self.assertRaisesRegex(Error, message):
            fn()
        self.assertEqual(path.read_bytes(), before)

    def assert_valid(self, c):
        tree = self.store.read_tree(c["tree"])
        self.assertEqual(state_issues(tree, tree["root"]), [])

    def test_plan_does_not_enter_delegate_or_assess_results(self):
        root = self.start()
        child = self.enter(root)
        back = self.action("return_", child, mode="closed", result=RESULT)
        p = self.plan(back, activation_trigger="A representative workload arrives")
        n = p["planned_node"]
        self.assertEqual(p["session"], back["session"])
        self.assertEqual(p["pending_results"], back["pending_results"])
        tree = self.store.read_tree(p["tree"])
        self.assertEqual(len(tree["sessions"]), 1)
        self.assertEqual(tree["nodes"][n["id"]]["results"], [])
        self.assertEqual(tree["nodes"][n["id"]]["status"], "planned")
        self.assertFalse(n["started"])
        self.assertEqual(tree["nodes"][tree["root"]]["assessments"], [])
        self.assert_valid(p)

    def test_refine_plan_without_enter_then_start_same_id(self):
        p = self.plan(self.start())
        nid = p["planned_node"]["id"]
        self.assert_unchanged(p, lambda: self.action("enter", p, node=nid), "return_when")
        r = self.action("revise", p, **self.aimed(p, nid), reason="Specify stopping evidence",
                        changes={"return_when": "Compare measured cases", "deferred_because": "Need fixture"})
        self.assertEqual(r["current"]["id"], p["current"]["id"])
        active = self.action("enter", r, node=nid)
        self.assertEqual(active["current"]["id"], nid)
        self.assertTrue(active["current"]["started"])
        self.assertEqual(active["current"]["status"], "open")
        self.assertEqual(active["current"]["sources"], p["planned_node"]["sources"])
        self.assert_valid(active)

    def test_register_elsewhere_retains_position_and_checks_target(self):
        root = self.start()
        a = self.enter(root, fork=True)
        b = self.enter(a["context"], fork=True)
        main = b["context"]
        nid = a["delegation"]["current"]["id"]
        info = self.aimed(main, nid)
        stale = info["target_token"]
        self.action("revise", a["delegation"], reason="New condition", changes={"notes": "Changed"})
        self.assert_unchanged(main, lambda: self.plan(self.refresh(main), parent=nid, target_token=stale), "Target context changed")
        fresh = self.refresh(main)
        p = self.plan(fresh, parent=nid, target_token=self.aimed(fresh, nid)["target_token"])
        self.assertEqual(p["session"], fresh["session"])
        self.assertEqual(p["planned_node"]["parent"], nid)
        # Unrelated leaf context is still usable.
        self.action("revise", b["delegation"], reason="Independent evidence", changes={"notes": "Still valid"})

    def test_target_token_covers_descendants_and_session_activity(self):
        root = self.start()
        a = self.enter(root, fork=True)
        nested = self.enter(a["delegation"], fork=True)
        main = self.refresh(a["context"])
        nid = a["delegation"]["current"]["id"]
        old = self.aimed(main, nid)["target_token"]
        self.action("handoff", nested["delegation"], reason="Other context will resume")
        self.assert_unchanged(main, lambda: self.plan(main, parent=nid, target_token=old), "Target context changed")

    def test_delegated_session_cannot_target_ancestor_or_sibling(self):
        root = self.start()
        a = self.enter(root, fork=True)
        b = self.enter(a["context"], fork=True)
        child = a["delegation"]
        for nid in (root["current"]["id"], b["delegation"]["current"]["id"]):
            with self.subTest(target=nid):
                info = self.aimed(child, nid)
                self.assert_unchanged(child, lambda: self.plan(child, parent=nid, target_token=info["target_token"]), "outside.*boundary")

    def test_plans_can_be_nested_but_execution_requires_open_ancestors(self):
        p = self.plan(self.start(), return_when="Parent answer")
        nid = p["planned_node"]["id"]
        q = self.plan(p, parent=nid, target_token=p["target_token"], return_when="Child answer")
        qid = q["planned_node"]["id"]
        self.assert_unchanged(q, lambda: self.engine.attach(q["tree"], {"node": qid}), "Planned ancestor")
        parent = self.action("enter", q, node=nid)
        leaf = self.action("enter", parent, node=qid)
        self.assert_valid(leaf)

    def test_plan_under_closed_parent_preserves_conclusion(self):
        root = self.start()
        child = self.enter(root)
        back = self.action("return_", child, mode="closed", result=RESULT)
        nid = child["current"]["id"]
        before = deepcopy(self.store.read_tree(back["tree"])["nodes"][nid])
        info = self.aimed(back, nid)
        self.assert_unchanged(back, lambda: self.plan(back, parent=nid, target_token=info["target_token"]), "followup_reason")
        p = self.plan(back, parent=nid, target_token=info["target_token"], followup_reason="Future workload outside measured scope")
        saved = self.store.read_tree(back["tree"])["nodes"][nid]
        self.assertEqual(saved["status"], "closed")
        self.assertEqual(saved["results"], before["results"])
        self.assertEqual(saved["question"], before["question"])
        done = self.action("finish", p, assessment=ASSESSMENT, result=RESULT, uncovered=["Future workload"])
        self.assertEqual(done["current"]["latest_result"]["unresolved_nodes"][0]["id"], p["planned_node"]["id"])
        self.assert_valid(done)

    def test_close_accepts_planned_closed_and_abandoned_children(self):
        parent = self.enter(self.start())
        child = self.enter(parent)
        parent = self.action("return_", child, mode="closed", result=RESULT)
        p = self.plan(parent, return_when="Future scope")
        q = self.plan(p)
        abandoned = self.action("abandon", q, **self.aimed(q, q["planned_node"]["id"]), reason="No longer needed")
        self.assert_unchanged(abandoned, lambda: self.action("return_", abandoned, mode="closed", result=RESULT, assessment=ASSESSMENT), "uncovered")
        done = self.action("return_", abandoned, mode="closed", result=RESULT, assessment=ASSESSMENT, uncovered=["Future scope remains planned"])
        self.assert_valid(done)
        self.assertEqual(self.store.read_tree(done["tree"])["nodes"][parent["current"]["id"]]["status"], "closed")

    def test_close_rejects_open_node_even_after_session_handoff(self):
        root = self.start()
        fork = self.enter(root, fork=True)
        self.action("handoff", fork["delegation"], reason="Continue later")
        main = self.refresh(fork["context"])
        self.assert_unchanged(main, lambda: self.action("finish", main, result=RESULT, uncovered=["Deferred"]), "open or paused")

    def test_abandon_plan_has_reason_and_notification_but_no_result(self):
        p = self.plan(self.start())
        info = self.aimed(p, p["planned_node"]["id"])
        self.assert_unchanged(p, lambda: self.action("abandon", p, **info, reason=" "), "reason")
        back = self.action("abandon", p, **info, reason="Different approach selected")
        self.assertEqual(back["pending_results"], [])
        self.assertEqual(len(back["pending_updates"]), 1)
        self.assertEqual(back["pending_updates"][0]["update"]["reason"], "Different approach selected")
        tree = self.store.read_tree(back["tree"])
        self.assertEqual(tree["nodes"][info["node"]]["results"], [])
        self.assert_unchanged(back, lambda: self.action("finish", back, result=RESULT), "assessment")
        done = self.action("finish", back, result=RESULT, assessment=ASSESSMENT)
        self.assertEqual(len(done["current"]["assessments"][-1]["source_updates"]), 1)

    def test_restore_never_started_plan_does_not_start_or_erase_history(self):
        p = self.plan(self.start(), return_when="Evidence")
        nid = p["planned_node"]["id"]
        abandoned = self.action("abandon", p, **self.aimed(p, nid), reason="No capacity")
        self.assert_unchanged(abandoned, lambda: self.action("enter", abandoned, node=nid, assessment=ASSESSMENT), "restore")
        restored = self.action("restore", abandoned, **self.aimed(abandoned, nid), reason="Capacity available")
        self.assertEqual(restored["restored_node"]["status"], "planned")
        self.assertFalse(restored["restored_node"]["started"])
        self.assertEqual(len(restored["pending_updates"]), 2)
        actual = self.action("enter", restored, node=nid, assessment=ASSESSMENT)
        saved = self.store.read_tree(actual["tree"])["nodes"][nid]
        self.assertEqual([u["kind"] for u in saved["updates"]], ["abandoned", "restored"])
        self.assertTrue(saved["started"])

    def test_abandon_research_preserves_actual_progress_and_returns(self):
        root = self.start()
        child = self.enter(root)
        back = self.action("abandon", child, reason="Benefit too small", result=RESULT)
        nid = child["current"]["id"]
        self.assertEqual(back["current"]["id"], root["current"]["id"])
        self.assertEqual(back["pending_results"][0]["result"]["summary"], RESULT["summary"])
        restored = self.action("restore", back, **self.aimed(back, nid), reason="New data")
        self.assertEqual(restored["restored_node"]["status"], "paused")
        self.assertTrue(restored["restored_node"]["started"])

    def test_explicit_subtree_abandonment_preserves_closed_nodes(self):
        parent = self.enter(self.start())
        leaf = self.enter(parent)
        back = self.action("return_", leaf, mode="closed", result=RESULT)
        p = self.plan(back)
        before = deepcopy(self.store.read_tree(p["tree"])["nodes"][leaf["current"]["id"]])
        self.assert_unchanged(p, lambda: self.action("abandon", p, reason="Stop this route"), "subtree")
        abandoned = self.action("abandon", p, reason="Stop this route", subtree=True)
        tree = self.store.read_tree(abandoned["tree"])
        self.assertEqual(tree["nodes"][leaf["current"]["id"]], before)
        self.assertEqual(tree["nodes"][p["planned_node"]["id"]]["status"], "abandoned")
        self.assertEqual(tree["nodes"][parent["current"]["id"]]["status"], "abandoned")
        # Parent research remains open and old child results are not silently assessed.
        self.assertEqual(abandoned["current"]["status"], "open")
        self.assert_valid(abandoned)

    def test_abandon_cannot_relabel_closed_research_or_drop_other_sessions(self):
        root = self.start()
        fork = self.enter(root, fork=True)
        main = fork["context"]
        self.assert_unchanged(main, lambda: self.action("abandon", main, reason="Stop", subtree=True), "Other sessions")
        done = self.action("return_", fork["delegation"], mode="closed", result=RESULT)
        main = self.refresh(main)
        info = self.aimed(main, done["current"]["id"])
        self.assert_unchanged(main, lambda: self.action("abandon", main, **info, reason="Relabel"), "Only planned")

    def test_handoff_leaves_node_open_for_other_executor(self):
        root = self.start()
        peer = self.engine.attach(root["tree"], {"label": "peer"})
        self.assert_unchanged(root, lambda: self.action("return_", root, mode="paused", result=RESULT), "Other sessions")
        left = self.action("handoff", root, reason="Peer continues", result=RESULT)
        self.assertEqual(left["session"]["status"], "paused")
        self.assertEqual(left["session"]["handoff"]["reason"], "Peer continues")
        self.assertIn("Peer continues", render(left))
        self.assertEqual(left["current"]["status"], "open")
        peer = self.refresh(peer)
        done = self.action("finish", peer, result=RESULT)
        self.assert_valid(done)

    def test_pause_subtree_is_explicit_and_does_not_pause_external_agents(self):
        root = self.start()
        fork = self.enter(root, fork=True)
        self.assert_unchanged(fork["context"], lambda: self.action("return_", fork["context"], mode="paused", subtree=True, result=RESULT), "Other sessions")
        self.action("handoff", fork["delegation"], reason="Ready to pause")
        main = self.refresh(fork["context"])
        self.assert_unchanged(main, lambda: self.action("return_", main, mode="paused", result=RESULT), "Invalid child state")
        paused = self.action("return_", main, mode="paused", subtree=True, result=RESULT)
        self.assert_valid(paused)
        tree = self.store.read_tree(paused["tree"])
        self.assertEqual(tree["nodes"][fork["delegation"]["current"]["id"]]["status"], "paused")
        self.assert_unchanged(paused, lambda: self.engine.attach(paused["tree"], {"resume": fork["delegation"]["session"]["id"]}), "Paused ancestor")
        self.engine.attach(paused["tree"], {"resume": paused["session"]["id"]})
        self.engine.attach(paused["tree"], {"resume": fork["delegation"]["session"]["id"]})

    def test_root_abandon_restore_and_selected_path_only(self):
        p = self.plan(self.start())
        nid = p["planned_node"]["id"]
        abandoned = self.action("abandon", p, reason="Goal withdrawn", subtree=True)
        self.assertEqual(abandoned["tree_status"], "abandoned")
        self.assert_unchanged(abandoned, lambda: self.engine.attach(abandoned["tree"], {"resume": abandoned["session"]["id"], "reopen_reason": "Retry"}), "restore")
        restored = self.action("restore", abandoned, reason="Goal reinstated")
        self.assertEqual(restored["current"]["status"], "paused")
        self.assertEqual(restored["session"]["status"], "paused")
        self.assertEqual(self.store.read_tree(restored["tree"])["nodes"][nid]["status"], "abandoned")
        resumed = self.engine.attach(restored["tree"], {"resume": restored["session"]["id"]})
        self.assert_valid(resumed)

    def test_closed_ancestor_blocks_restoring_started_descendant(self):
        parent = self.enter(self.start())
        child = self.enter(parent)
        parent = self.action("abandon", child, reason="Stop")
        root = self.action("return_", parent, mode="closed", result=RESULT, assessment=ASSESSMENT)
        self.assert_unchanged(root, lambda: self.action("restore", root, **self.aimed(root, child["current"]["id"]), reason="Retry"), "Invalid child state")

    def test_schema_one_reads_do_not_migrate_and_explicit_repair_preserves_history(self):
        parent = self.enter(self.start())
        child = self.enter(parent)
        parent = self.action("return_", child, mode="paused", result=RESULT)
        path = self.store.tree_path(parent["tree"])
        legacy = self.store.read_tree(parent["tree"])
        legacy["schema"] = 1
        legacy["nodes"][parent["current"]["id"]]["status"] = "closed"
        legacy["sessions"][parent["session"]["id"]]["node"] = legacy["root"]
        for n in legacy["nodes"].values():
            n.pop("started", None)
        atomic_json(path, legacy)
        before = path.read_bytes()
        read = self.refresh(parent)
        self.assertTrue(read["state_warnings"])
        self.assertEqual(path.read_bytes(), before)
        repaired = self.action("enter", read, node=parent["current"]["id"], reopen_reason="Continue unfinished scope")
        tree = self.store.read_tree(parent["tree"])
        self.assertEqual(tree["schema"], 2)
        self.assertEqual(tree["events"][:-1], legacy["events"])
        self.assertEqual(tree["nodes"][child["current"]["id"]]["results"], legacy["nodes"][child["current"]["id"]]["results"])
        self.assertNotIn("started", tree["nodes"][child["current"]["id"]])
        self.assert_valid(repaired)

    def test_unknown_legacy_started_state_is_not_inferred_from_results(self):
        p = self.plan(self.start())
        nid = p["planned_node"]["id"]
        tree = self.store.read_tree(p["tree"])
        tree["schema"] = 1
        tree["nodes"][nid]["status"] = "paused"
        tree["nodes"][nid].pop("started")
        atomic_json(self.store.tree_path(p["tree"]), tree)
        c = self.refresh(p)
        a = self.action("abandon", c, **self.aimed(c, nid), reason="Stop old work")
        restored = self.action("restore", a, **self.aimed(a, nid), reason="Reconsider")
        self.assertEqual(restored["restored_node"]["status"], "paused")
        self.assertNotIn("started", restored["restored_node"])

    def test_new_contexts_remain_lossless_in_both_formats(self):
        p = self.plan(self.start(), activation_trigger="Dataset", deferred_because="Not ready")
        a = self.action("abandon", p, **self.aimed(p, p["planned_node"]["id"]), reason="Alternative")
        r = self.action("restore", a, **self.aimed(a, p["planned_node"]["id"]), reason="New evidence")
        for c in (p, a, r):
            with self.subTest(keys=list(c)):
                original = deepcopy(c)
                self.assertEqual(expand_context(deduplicate_context(c)), c)
                self.assertEqual(c, original)
                self.assertIn(c["current"]["id"], render(c))
        self.assertIn("Alternative", render(a))
        self.assertIn("Dataset", render(p))

    def test_concurrent_targeted_plan_writes_reject_one_stale_snapshot(self):
        p = self.plan(self.start())
        peer = self.engine.attach(p["tree"], {"label": "independent maintainer"})
        nid = p["planned_node"]["id"]
        target = self.aimed(p, nid)["target_token"]
        def launch(c):
            return self.cli(["plan", "--tree", c["tree"], "--session", c["session"]["id"]],
                            {"context_token": c["context_token"], "parent": nid, "target_token": target,
                             "question": "Future subquestion", "parent_link": "Refines plan"})
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(launch, [p, peer]))
        self.assertEqual(sorted(r.returncode for r in results), [0, 2])
        self.assertEqual(len(self.store.read_tree(p["tree"])["nodes"]), 3)

    def test_cli_plan_abandon_restore_handoff_and_read_target(self):
        root = self.start()
        p = self.cli(["plan", "--tree", root["tree"], "--session", root["session"]["id"]],
                     {"context_token": root["context_token"], "question": "Next", "parent_link": "Coverage"},
                     options=["--context-format", "deduplicated"])
        self.assertEqual(p.returncode, 0, p.stderr)
        c = expand_context(json.loads(p.stdout))
        nid = c["planned_node"]["id"]
        target = self.cli(["read", "--tree", c["tree"], "--view", "node", "--node", nid])
        self.assertIn("ancestors", json.loads(target.stdout))
        for action in ("abandon", "restore"):
            out = self.cli([action, "--tree", c["tree"], "--session", c["session"]["id"]],
                           {"context_token": c["context_token"], **self.aimed(c, nid), "reason": "Changed circumstances"})
            self.assertEqual(out.returncode, 0, out.stderr)
            c = json.loads(out.stdout)
        handoff = self.cli(["handoff", "--tree", c["tree"], "--session", c["session"]["id"]],
                           {"context_token": c["context_token"], "reason": "Next conversation"})
        self.assertEqual(handoff.returncode, 0, handoff.stderr)
        self.assertEqual(json.loads(handoff.stdout)["current"]["status"], "open")

"""Behaviour tests for the X11/EWMH compositor adapter.

Golden input is a real capture from a UOS 25 / kwin_x11 session
(``tests/fixtures/x11``, 2026-09-24): a 1920x1080 screen, the desktop shell,
a control centre window at (560,240) sized 800x600, a maximised terminal, and
the dock strip along the bottom.  EWMH ``_NET_CLIENT_LIST_STACKING`` is ordered
bottom-to-top, so the dock is the topmost managed window and the terminal sits
above the control centre.
"""

import subprocess
import unittest
from pathlib import Path

from mcp_autogui.adapters.compositor.x11 import (
    COORDINATE_SPACE_ID,
    MIN_OVERLAY_SIZE,
    X11CompositorAdapter,
    frame_extents,
    parse_cursor,
    parse_outputs,
    parse_root_geometry,
    parse_stacking,
    parse_window_geometry,
    parse_window_tree,
    top_level_with_descendants,
    unquote,
    window_role,
)
from mcp_autogui.adapters.evidence.compositor_window import CompositorWindowEvidenceProvider
from mcp_autogui.core.action_gate import ActionGate
from mcp_autogui.core.models import (
    Action,
    ActionProposal,
    ActionType,
    AssertionSpec,
    CanonicalSnapshot,
    ExecutionReceipt,
    ExecutionStatus,
    Point,
    PolicyStatus,
    ReasonCode,
    Rect,
    TaskContract,
    TaskLimits,
    TaskPermissions,
    TaskStatus,
    WindowRole,
    new_id,
    utc_now,
)
from mcp_autogui.core.orchestrator import CoreOrchestrator
from mcp_autogui.core.store import ObjectStore


FIXTURES = Path(__file__).parent / "fixtures" / "x11"

DESKTOP = "0x4200007"
CONTROL_CENTRE = "0x5a00014"
TERMINAL = "0x6a0000a"
DOCK = "0x2c00014"
STACKING_BOTTOM_TO_TOP = (DESKTOP, CONTROL_CENTRE, TERMINAL, DOCK)
# xwininfo -id 0x6a0000a reports this app id; the served pointer sat inside it.
TERMINAL_APP_ID = "deepin-terminal"
# Synthetic: the captured launchpad surface reported as mapped and full-screen.
MAPPED_FULLSCREEN_OVERLAY = (
    "xwininfo: Window id: 0x2c00018 \"dde-shell/launchpad\"\n\n"
    "  Absolute upper-left X:  0\n"
    "  Absolute upper-left Y:  0\n"
    "  Width: 1920\n"
    "  Height: 1080\n"
    "  Map State: IsViewable\n"
)


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class X11FixtureRunner:
    """Replays captured command output and rejects unrecorded commands.

    ``overrides`` maps a full command line to replacement output *content* so a
    test can describe a desktop state that was never captured.
    """

    def __init__(self, overrides: dict[str, str] | None = None) -> None:
        self.overrides = dict(overrides or {})
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, argv, *, c_locale: bool = False, timeout: float = 0.0):
        argv = [str(item) for item in argv]
        self.commands.append(tuple(argv))
        output = self.overrides.get(" ".join(argv))
        if output is None:
            name = self._fixture_name(argv)
            if name is None:
                raise AssertionError(f"unexpected X11 command: {' '.join(argv)}")
            output = fixture_text(name)
        return subprocess.CompletedProcess(argv, 0, output, "")

    def observed(self, *prefix: str) -> bool:
        return any(command[: len(prefix)] == prefix for command in self.commands)

    @staticmethod
    def _fixture_name(argv: list[str]) -> str | None:
        if argv[:3] == ["xwininfo", "-root", "-tree"]:
            return "tree.txt"
        if argv[:2] == ["xwininfo", "-root"]:
            return "root.txt"
        if argv[0] == "xwininfo" and argv[1] == "-id":
            return f"xwininfo-{argv[2]}.txt"
        if argv[0] == "xprop" and argv[1] == "-id":
            return f"prop-{argv[2]}.txt"
        if argv[:2] == ["xprop", "-root"]:
            return "stacking.xprop.txt" if "_NET_CLIENT_LIST_STACKING" in argv else "active.xprop.txt"
        if argv[:2] == ["xdotool", "getmouselocation"]:
            return "cursor.txt"
        if argv[:2] == ["xdotool", "getdisplaygeometry"]:
            return "display.txt"
        if argv[:2] == ["xrandr", "--current"]:
            return "xrandr.txt"
        return None


def adapter(runner: X11FixtureRunner | None = None, store: ObjectStore | None = None):
    return X11CompositorAdapter(runner=runner or X11FixtureRunner(), artifact_store=store)


class X11ParserTests(unittest.TestCase):
    def test_stacking_is_parsed_bottom_to_top_with_the_active_window(self):
        stacking, active = parse_stacking(fixture_text("stacking.xprop.txt"))
        self.assertEqual(stacking, STACKING_BOTTOM_TO_TOP)
        self.assertEqual(active, TERMINAL)

    def test_outputs_come_from_connected_heads_only(self):
        bounds, outputs = parse_outputs(fixture_text("xrandr.txt"))
        self.assertEqual((bounds.x, bounds.y, bounds.width, bounds.height), (0, 0, 1920, 1080))
        self.assertEqual([item.output_id for item in outputs], ["VGA-0"])
        self.assertEqual(outputs[0].scale, 1.0)

    def test_root_geometry_is_read_without_relying_on_window_titles(self):
        bounds = parse_root_geometry(fixture_text("root.txt"))
        self.assertEqual((bounds.width, bounds.height), (1920.0, 1080.0))

    def test_window_tree_keeps_every_window_and_its_nesting(self):
        nodes = parse_window_tree(fixture_text("tree.txt"))
        ids = [node.window_id for node in nodes]
        for managed in STACKING_BOTTOM_TO_TOP:
            self.assertIn(managed, ids)
        self.assertLess(min(node.indent for node in nodes), max(node.indent for node in nodes))

    def test_managed_windows_are_nested_below_their_frame(self):
        nodes = parse_window_tree(fixture_text("tree.txt"))
        groups = top_level_with_descendants(nodes)
        owners = [node.window_id for node, _ in groups]
        for managed in STACKING_BOTTOM_TO_TOP:
            self.assertNotIn(managed, owners)
        self.assertIn("0x2c00018", owners)  # the unmanaged launchpad surface

    def test_frame_extents_tolerate_a_missing_property(self):
        self.assertEqual(frame_extents({}), (0.0, 0.0, 0.0, 0.0))
        self.assertEqual(frame_extents({"_NET_FRAME_EXTENTS": "not found."}), (0.0, 0.0, 0.0, 0.0))
        self.assertEqual(
            frame_extents({"_NET_FRAME_EXTENTS": "1, 2, 3, 4"}), (1.0, 3.0, 2.0, 4.0)
        )

    def test_map_state_and_geometry_are_parsed_from_the_client_window(self):
        geometry, visible = parse_window_geometry(fixture_text(f"xwininfo-{CONTROL_CENTRE}.txt"))
        self.assertEqual((geometry.x, geometry.y, geometry.width, geometry.height), (560, 240, 800, 600))
        self.assertTrue(visible)

    def test_cursor_and_roles(self):
        self.assertEqual(parse_cursor(fixture_text("cursor.txt")), Point(931, 643))
        self.assertEqual(unquote('"控制中心"'), "控制中心")
        self.assertEqual(window_role({"_NET_WM_WINDOW_TYPE": "_NET_WM_WINDOW_TYPE_DESKTOP, _NET_WM_WINDOW_TYPE_NORMAL"}), WindowRole.DESKTOP)
        self.assertEqual(window_role({"_NET_WM_WINDOW_TYPE": "_NET_WM_WINDOW_TYPE_DOCK"}), WindowRole.PANEL)
        self.assertEqual(window_role({"_NET_WM_WINDOW_TYPE": "_NET_WM_WINDOW_TYPE_NORMAL"}), WindowRole.NORMAL)


class X11ObservationTests(unittest.TestCase):
    def setUp(self):
        self.store = ObjectStore()
        self.runner = X11FixtureRunner()
        self.compositor = adapter(self.runner, self.store)
        self.snapshot = self.compositor.observe()

    def test_descriptor_claims_an_authoritative_total_stacking_order(self):
        capabilities = self.compositor.descriptor.capabilities
        self.assertEqual(capabilities.stacking.model.value, "total-order")
        self.assertTrue(capabilities.stacking.hit_test)
        self.assertTrue(capabilities.stacking.is_above)
        self.assertTrue(capabilities.active_window)

    def test_managed_windows_are_reported_bottom_to_top(self):
        self.assertEqual([item.window_id for item in self.snapshot.windows], list(STACKING_BOTTOM_TO_TOP))
        self.assertEqual([item.z_index for item in self.snapshot.windows], [0.0, 1.0, 2.0, 3.0])

    def test_only_the_active_window_is_marked_active(self):
        active = [item.window_id for item in self.snapshot.windows if item.active is True]
        self.assertEqual(active, [TERMINAL])
        self.assertEqual(self.snapshot.active_window().window_id, TERMINAL)

    def test_titles_are_utf8_properties_not_ascii_mangled_tree_text(self):
        by_id = {item.window_id: item for item in self.snapshot.windows}
        self.assertEqual(by_id[TERMINAL].title, "uos@uos-PC: ~/Desktop - 终端")
        self.assertEqual(by_id[CONTROL_CENTRE].title, "控制中心")
        self.assertEqual(by_id[DOCK].app_id, "dde-shell/dock")
        self.assertEqual(by_id[TERMINAL].app_id, TERMINAL_APP_ID)

    def test_geometry_visibility_and_role_come_from_the_server(self):
        by_id = {item.window_id: item for item in self.snapshot.windows}
        centre = by_id[CONTROL_CENTRE].geometry
        self.assertEqual(
            (centre.x, centre.y, centre.width, centre.height), (560.0, 240.0, 800.0, 600.0)
        )
        self.assertEqual(
            (by_id[DOCK].geometry.x, by_id[DOCK].geometry.y, by_id[DOCK].geometry.height),
            (0.0, 1032.0, 48.0),
        )
        self.assertTrue(all(item.visible is True for item in self.snapshot.windows))
        self.assertEqual(by_id[DESKTOP].role, WindowRole.DESKTOP)
        self.assertEqual(by_id[DOCK].role, WindowRole.PANEL)
        self.assertEqual(by_id[TERMINAL].role, WindowRole.NORMAL)

    def test_sticky_windows_have_no_workspace_and_others_report_theirs(self):
        by_id = {item.window_id: item for item in self.snapshot.windows}
        self.assertIsNone(by_id[DESKTOP].workspace_id)  # 4294967295 means all desktops
        self.assertIsNone(by_id[DOCK].workspace_id)
        self.assertEqual(by_id[TERMINAL].workspace_id, "0")

    def test_every_window_is_attributed_to_the_connected_output(self):
        self.assertEqual({item.output_id for item in self.snapshot.windows}, {"VGA-0"})

    def test_coordinate_space_is_the_root_window(self):
        space = self.snapshot.coordinate_space
        self.assertEqual(space.id, COORDINATE_SPACE_ID)
        self.assertEqual((space.bounds.width, space.bounds.height), (1920.0, 1080.0))
        self.assertTrue(space.version.startswith("sha256:"))

    def test_the_raw_observation_is_kept_as_an_artifact(self):
        artifact = self.store.require(self.snapshot.raw_artifact_ref)
        self.assertIn("stacking", artifact["commands"])
        self.assertEqual(artifact["overlays"], {})

    def test_coordinate_space_version_tracks_the_layout_not_the_windows(self):
        first = self.compositor.observe().coordinate_space.version
        second = self.compositor.observe().coordinate_space.version
        self.assertEqual(first, second)
        resized = X11FixtureRunner(
            {
                "xrandr --current": "Screen 0: current 2560 x 1440\n"
                "VGA-0 connected primary 2560x1440+0+0 (normal) 600mm x 340mm\n",
                "xwininfo -root": fixture_text("root.txt").replace(
                    "-geometry 1920x1080+0+0", "-geometry 2560x1440+0+0"
                ),
            }
        )
        moved = adapter(resized, ObjectStore()).observe()
        self.assertEqual(moved.coordinate_space.bounds.width, 2560.0)
        self.assertNotEqual(moved.coordinate_space.version, first)

    def test_the_root_window_geometry_wins_if_xrandr_disagrees(self):
        # xrandr reports the logical mode, the server reports what is actually
        # mapped; a rotated or scaled layout can differ, so the server wins.
        runner = X11FixtureRunner(
            {"xrandr --current": "Screen 0: current 1024 x 768\nVGA-0 connected 1024x768+0+0 (normal)\n"}
        )
        snapshot = adapter(runner, ObjectStore()).observe()
        self.assertEqual(snapshot.coordinate_space.bounds.width, 1920.0)

    def test_environment_version_changes_when_the_desktop_changes(self):
        changed = X11FixtureRunner({"xprop -root _NET_CLIENT_LIST_STACKING _NET_ACTIVE_WINDOW": f"_NET_CLIENT_LIST_STACKING(WINDOW): window id # {DESKTOP}\n_NET_ACTIVE_WINDOW(WINDOW): window id # {DESKTOP}\n"})
        other = adapter(changed, ObjectStore()).observe()
        self.assertNotEqual(other.environment_version, self.snapshot.environment_version)


class X11SpatialQueryTests(unittest.TestCase):
    def setUp(self):
        self.store = ObjectStore()
        self.compositor = adapter(X11FixtureRunner(), self.store)
        self.snapshot = self.compositor.observe()

    def test_hit_test_returns_the_topmost_managed_window(self):
        # The control centre occupies (560,240)-(1360,840) but the terminal is
        # stacked above it and covers the same point.
        self.assertEqual(self.compositor.hit_test(Point(900, 400), self.snapshot), TERMINAL)
        # Below the terminal's 1032px height only the dock remains.
        self.assertEqual(self.compositor.hit_test(Point(100, 1040), self.snapshot), DOCK)

    def test_hit_test_agrees_with_the_x_servers_own_answer_at_the_pointer(self):
        cursor = self.snapshot.cursor
        served = int(fixture_text("cursor.txt").split("WINDOW=")[1].strip())
        self.assertEqual(self.compositor.hit_test(cursor, self.snapshot), f"0x{served:x}")

    def test_hit_test_points_outside_every_window_have_no_target(self):
        outside = CanonicalSnapshot(
            snapshot_id=new_id("snapshot"),
            captured_at=utc_now(),
            environment_version="env",
            coordinate_space=self.snapshot.coordinate_space,
            outputs=self.snapshot.outputs,
            cursor=None,
            windows=(),
        )
        self.assertIsNone(self.compositor.hit_test(Point(5000, 5000), outside))

    def test_is_above_follows_the_stacking_order(self):
        self.assertTrue(self.compositor.is_above(DOCK, TERMINAL, self.snapshot))
        self.assertFalse(self.compositor.is_above(TERMINAL, DOCK, self.snapshot))
        self.assertIsNone(self.compositor.is_above("0xdeadbeef", TERMINAL, self.snapshot))

    def test_occlusion_uses_windows_stacked_above_the_target(self):
        region = Rect(560, 240, 800, 600)
        self.assertTrue(self.compositor.occluded(CONTROL_CENTRE, region, self.snapshot))
        self.assertFalse(self.compositor.occluded(DOCK, Rect(0, 1032, 1920, 48), self.snapshot))
        self.assertIsNone(self.compositor.occluded("0xdeadbeef", region, self.snapshot))

    def test_unmapped_unmanaged_surfaces_do_not_block_the_desktop(self):
        # 11 unmanaged top-level windows are large enough to matter (a 1920x1080
        # launchpad, a 640x480 lock surface, kwin helpers) and every one of them
        # is unmapped; trusting their size alone would refuse every click.
        self.assertIsNotNone(self.compositor.hit_test(Point(10, 10), self.snapshot))
        self.assertFalse(self.compositor.occluded(DOCK, Rect(0, 1032, 1920, 48), self.snapshot))

    def test_a_mapped_unmanaged_overlay_hides_the_target_conservatively(self):
        runner = X11FixtureRunner({"xwininfo -id 0x2c00018": MAPPED_FULLSCREEN_OVERLAY})
        compositor = adapter(runner, ObjectStore())
        snapshot = compositor.observe()
        self.assertIsNone(compositor.hit_test(Point(900, 400), snapshot))
        self.assertTrue(compositor.occluded(TERMINAL, Rect(900, 400, 10, 10), snapshot))
        self.assertTrue(compositor.occluded(CONTROL_CENTRE, Rect(560, 240, 800, 600), snapshot))

    def test_overlay_threshold_excludes_helper_windows(self):
        nodes = parse_window_tree(fixture_text("tree.txt"))
        candidates = [
            node
            for node, ids in top_level_with_descendants(nodes)
            if node.geometry.width >= MIN_OVERLAY_SIZE and node.geometry.height >= MIN_OVERLAY_SIZE
        ]
        self.assertNotIn("0x4800016", {node.window_id for node in candidates})  # 3x3 clipboard helper
        self.assertIn("0x2c00018", {node.window_id for node in candidates})  # full-screen launchpad


class X11GateIntegrationTests(unittest.TestCase):
    """The adapter must satisfy the real ActionGate, not just its own tests."""

    def setUp(self):
        self.store = ObjectStore()
        self.compositor = adapter(X11FixtureRunner(), self.store)
        self.snapshot = self.compositor.observe()
        self.gate = ActionGate(self.compositor.descriptor, self.compositor.hit_test)

    def contract(self, actions, intents=("navigation",), overrides=None):
        return TaskContract(
            task_id="task-x11",
            goal="click the terminal",
            permissions=TaskPermissions(frozenset(actions), frozenset(intents)),
            limits=TaskLimits(max_steps=3, max_retries=0),
            policy_overrides=dict(overrides or {}),
        )

    def proposal(self, point: Point):
        return ActionProposal(
            proposal_id=new_id("proposal"),
            source="test",
            based_on_snapshot=self.snapshot.snapshot_id,
            action=Action(ActionType.POINTER_CLICK, point, COORDINATE_SPACE_ID),
            claimed_intent="navigation",
        )

    def test_a_bare_click_is_unclassified_and_needs_confirmation_by_default(self):
        # Nothing independent describes a click, so the semantic policy falls back
        # to `unknown`, whose profile entry is `confirm`.  That default is the
        # reason the desktop tools and the README pass an explicit override.
        decision, guard, resolution = self.gate.decide(
            self.proposal(Point(900, 400)),
            self.contract({ActionType.POINTER_CLICK}),
            self.snapshot,
        )
        self.assertEqual(decision.status, PolicyStatus.CONFIRM)
        self.assertEqual(decision.reason_code, ReasonCode.CONFIRMATION_REQUIRED)
        self.assertEqual(guard.target_window_id, TERMINAL)
        self.assertIn("unknown", [tag.tag for tag in resolution.tags])

    def test_a_click_on_the_terminal_is_allowed_with_a_hit_test_guard(self):
        decision, guard, _ = self.gate.decide(
            self.proposal(Point(900, 400)),
            self.contract({ActionType.POINTER_CLICK}, overrides={"unknown": "allow"}),
            self.snapshot,
        )
        self.assertEqual(decision.status, PolicyStatus.ALLOW)
        self.assertEqual(guard.target_window_id, TERMINAL)
        self.assertEqual(guard.required_hit_window_id, TERMINAL)

    def test_a_click_without_permission_is_denied_before_any_guard(self):
        decision, guard, _ = self.gate.decide(
            self.proposal(Point(900, 400)),
            self.contract({ActionType.KEYBOARD_KEY}),
            self.snapshot,
        )
        self.assertEqual(decision.status, PolicyStatus.DENY)
        self.assertEqual(decision.reason_code, ReasonCode.MECHANICAL_PERMISSION_DENIED)
        self.assertIsNone(guard)

    def test_a_coordinate_outside_the_root_window_is_rejected(self):
        decision, _, _ = self.gate.decide(
            self.proposal(Point(5000, 100)),
            self.contract({ActionType.POINTER_CLICK}),
            self.snapshot,
        )
        self.assertEqual(decision.status, PolicyStatus.INVALID)
        self.assertEqual(decision.reason_code, ReasonCode.OUTSIDE_DESKTOP)

    def test_recheck_reports_a_target_that_moved_away_from_the_proposal_point(self):
        _, guard, _ = self.gate.decide(
            self.proposal(Point(900, 400)),
            self.contract({ActionType.POINTER_CLICK}, overrides={"unknown": "allow"}),
            self.snapshot,
        )
        moved = X11FixtureRunner(
            {
                "xwininfo -id 0x6a0000a": fixture_text("xwininfo-0x6a0000a.txt").replace(
                    "Absolute upper-left X:  0", "Absolute upper-left X:  2000"
                )
            }
        )
        later = adapter(moved, ObjectStore()).observe()
        self.assertEqual(self.gate.recheck(guard, later), ReasonCode.TARGET_GEOMETRY_INVALIDATED)

    def test_recheck_reports_a_target_that_disappeared(self):
        _, guard, _ = self.gate.decide(
            self.proposal(Point(900, 400)),
            self.contract({ActionType.POINTER_CLICK}, overrides={"unknown": "allow"}),
            self.snapshot,
        )
        closed = X11FixtureRunner(
            {"xprop -root _NET_CLIENT_LIST_STACKING _NET_ACTIVE_WINDOW": f"_NET_CLIENT_LIST_STACKING(WINDOW): window id # {DESKTOP}\n_NET_ACTIVE_WINDOW(WINDOW): window id # {DESKTOP}\n"}
        )
        later = adapter(closed, ObjectStore()).observe()
        self.assertEqual(self.gate.recheck(guard, later), ReasonCode.TARGET_DISAPPEARED)


class FakeExecutor:
    def __init__(self):
        self.executed: list[ActionProposal] = []

    def execute(self, proposal):
        self.executed.append(proposal)
        now = utc_now()
        return ExecutionReceipt(
            new_id("execution"),
            proposal.proposal_id,
            ExecutionStatus.DELIVERED,
            proposal.action,
            now,
            now,
        )


class X11CoreEndToEndTests(unittest.TestCase):
    """Real X11 observation -> real gate -> real evidence -> real assertion."""

    def test_a_click_on_the_terminal_completes_a_contract_about_the_active_window(self):
        store = ObjectStore()
        compositor = adapter(X11FixtureRunner({"xdotool getmouselocation --shell": fixture_text("cursor.txt")}), store)
        executor = FakeExecutor()
        runtime = CoreOrchestrator(
            compositor,
            executor,
            evidence_providers=(CompositorWindowEvidenceProvider(),),
            store=store,
        )
        runtime.register_task(
            TaskContract(
                task_id="task-x11",
                goal="the terminal is the active window",
                permissions=TaskPermissions(
                    frozenset({ActionType.POINTER_CLICK}), frozenset({"navigation"})
                ),
                assertions=(
                    AssertionSpec("terminal-active", "active_window.app_id", "equals", TERMINAL_APP_ID),
                ),
                limits=TaskLimits(max_steps=2, max_retries=0),
                policy_overrides={"unknown": "allow"},
            )
        )
        snapshot = runtime.observe("task-x11")
        proposal = ActionProposal(
            proposal_id=new_id("proposal"),
            source="test",
            based_on_snapshot=snapshot.snapshot_id,
            action=Action(ActionType.POINTER_CLICK, Point(900, 400), COORDINATE_SPACE_ID),
            claimed_intent="navigation",
        )
        runtime.submit_proposal("task-x11", proposal)
        self.assertEqual(runtime.decide(proposal.proposal_id).status, PolicyStatus.ALLOW)

        receipt = runtime.execute(proposal.proposal_id)
        self.assertIsInstance(receipt, ExecutionReceipt)
        self.assertEqual(receipt.status, ExecutionStatus.DELIVERED)
        self.assertEqual(len(executor.executed), 1)

        evidence, results, state = runtime.evaluate("task-x11")
        self.assertEqual([item.status.value for item in results], ["passed"])
        self.assertEqual(state.status, TaskStatus.COMPLETED)
        self.assertEqual(len(evidence), 1)


if __name__ == "__main__":
    unittest.main()

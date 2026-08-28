import threading
import unittest

from flowclick.automation import WorkflowRunner
from flowclick.models import Step, Workflow


class RecordingRunner(WorkflowRunner):
    def __init__(self, finished: threading.Event):
        super().__init__(on_finished=lambda _error: finished.set())
        self.executed: list[str] = []

    def _execute(self, step, workflow):
        self.executed.append(str(step.params.get("text", step.action)))
        if step.action == "wait_text_choice":
            return "break_loop"
        return None


class RoutingRunner(RecordingRunner):
    def _execute(self, step, workflow):
        self.executed.append(str(step.params.get("text", step.action)))
        if step.action == "text_router":
            return "jump:领奖"
        return None


class RunnerTests(unittest.TestCase):
    def test_loop_executes_body_requested_number_of_times(self):
        finished = threading.Event()
        runner = RecordingRunner(finished)
        start = Step.create("loop_start")
        start.params["count"] = 3
        body = Step.create("comment")
        body.params["text"] = "body"
        workflow = Workflow(steps=[start, body, Step.create("loop_end")])

        runner.start(workflow)
        self.assertTrue(finished.wait(2), "runner did not finish")
        self.assertEqual(runner.executed, ["body", "body", "body"])

    def test_disabled_steps_are_skipped(self):
        finished = threading.Event()
        runner = RecordingRunner(finished)
        disabled = Step.create("comment")
        disabled.params["text"] = "disabled"
        disabled.enabled = False
        enabled = Step.create("comment")
        enabled.params["text"] = "enabled"

        runner.start(Workflow(steps=[disabled, enabled]))
        self.assertTrue(finished.wait(2), "runner did not finish")
        self.assertEqual(runner.executed, ["enabled"])

    def test_text_choice_can_break_current_loop(self):
        finished = threading.Event()
        runner = RecordingRunner(finished)
        start = Step.create("loop_start")
        start.params["count"] = 5
        before = Step.create("comment")
        before.params["text"] = "before"
        choice = Step.create("wait_text_choice")
        skipped = Step.create("comment")
        skipped.params["text"] = "must-not-run"
        after = Step.create("comment")
        after.params["text"] = "after-loop"
        workflow = Workflow(
            steps=[start, before, choice, skipped, Step.create("loop_end"), after]
        )

        runner.start(workflow)
        self.assertTrue(finished.wait(2), "runner did not finish")
        self.assertEqual(runner.executed, ["before", "wait_text_choice", "after-loop"])

    def test_text_router_skips_to_named_label_and_exits_inner_loop(self):
        finished = threading.Event()
        runner = RoutingRunner(finished)
        outer = Step.create("loop_start")
        outer.params["count"] = 1
        inner = Step.create("loop_start")
        inner.params["count"] = 5
        router = Step.create("text_router")
        router.params["routes"] = "领取=>领奖"
        skipped = Step.create("comment")
        skipped.params["text"] = "must-not-run"
        label = Step.create("label")
        label.params["name"] = "领奖"
        after = Step.create("comment")
        after.params["text"] = "after-jump"
        workflow = Workflow(
            steps=[outer, inner, router, skipped, Step.create("loop_end"), label, after, Step.create("loop_end")]
        )

        runner.start(workflow)
        self.assertTrue(finished.wait(2), "runner did not finish")
        self.assertEqual(runner.executed, ["text_router", "label", "after-jump"])


if __name__ == "__main__":
    unittest.main()

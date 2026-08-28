import json
import unittest

from flowclick.models import Step, Workflow, step_summary
from flowclick.storage import load_workflow, save_workflow
from flowclick.validator import build_loop_map, parse_region, validate_workflow


class CoreTests(unittest.TestCase):
    def test_workflow_round_trip(self):
        import tempfile
        from pathlib import Path

        workflow = Workflow(name="测试", steps=[Step.create("wait"), Step.create("click")])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow.json"
            save_workflow(workflow, path)
            loaded = load_workflow(path)
            self.assertEqual(loaded.to_dict(), workflow.to_dict())
            self.assertEqual(loaded.source_path, str(path.resolve()))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["format"], "flowclick-workflow")

    def test_nested_loop_map(self):
        steps = [
            Step.create("loop_start"),
            Step.create("wait"),
            Step.create("loop_start"),
            Step.create("wait"),
            Step.create("loop_end"),
            Step.create("loop_end"),
        ]
        self.assertEqual(build_loop_map(steps), {2: 4, 4: 2, 0: 5, 5: 0})

    def test_unbalanced_loop_is_reported(self):
        workflow = Workflow(steps=[Step.create("loop_start"), Step.create("wait")])
        messages = [issue.display() for issue in validate_workflow(workflow)]
        self.assertTrue(any("缺少对应的循环结束" in message for message in messages))

    def test_parse_region(self):
        cases = [
            ("", None),
            ("10,20,300,400", (10, 20, 300, 400)),
            ([1, 2, 3, 4], (1, 2, 3, 4)),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(parse_region(raw), expected)

    def test_invalid_region_rejected(self):
        with self.assertRaises(ValueError):
            parse_region("1,2,0,4")

    def test_click_summary_is_readable(self):
        step = Step.create("click")
        step.params.update({"x": 100, "y": 200, "clicks": 2})
        self.assertIn("(100, 200)", step_summary(step))
        self.assertIn("× 2", step_summary(step))

    def test_text_choice_must_be_inside_loop(self):
        choice = Step.create("wait_text_choice")
        workflow = Workflow(steps=[choice])
        messages = [issue.display() for issue in validate_workflow(workflow)]
        self.assertTrue(any("必须放在循环开始" in message for message in messages))

    def test_text_choice_is_valid_inside_loop(self):
        workflow = Workflow(
            steps=[
                Step.create("loop_start"),
                Step.create("wait_text_choice"),
                Step.create("loop_end"),
            ]
        )
        self.assertEqual(validate_workflow(workflow), [])

    def test_text_choice_summary_lists_both_results(self):
        choice = Step.create("wait_text_choice")
        summary = step_summary(choice)
        self.assertIn("自动隐藏", summary)
        self.assertIn("前往开箱", summary)

    def test_text_router_requires_existing_label(self):
        router = Step.create("text_router")
        router.params["routes"] = "领取=>领奖"
        messages = [issue.display() for issue in validate_workflow(Workflow(steps=[router]))]
        self.assertTrue(any("找不到目标标签" in message for message in messages))

    def test_text_router_with_label_is_valid(self):
        router = Step.create("text_router")
        router.params["routes"] = "领取=>领奖"
        label = Step.create("label")
        label.params["name"] = "领奖"
        self.assertEqual(validate_workflow(Workflow(steps=[router, label])), [])

    def test_watchdog_defaults_are_valid(self):
        workflow = Workflow(steps=[Step.create("watchdog"), Step.create("wait")])
        self.assertEqual(validate_workflow(workflow), [])


if __name__ == "__main__":
    unittest.main()

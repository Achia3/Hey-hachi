import json
from pathlib import Path

import pytest

from hachi_evaluation import score_output, summarize_scores


EXPECTED = {"outcome": "tool_call", "tool": "manage_app", "arguments": {"action": "launch", "app_name": "Discord"}}


def call(name="manage_app", arguments=None):
    return "<tool_call>" + json.dumps({"name": name, "arguments": arguments or EXPECTED["arguments"]}) + "</tool_call>"


def test_correct_call_passes_but_extra_arguments_and_extra_calls_fail():
    assert score_output(EXPECTED, call())["correct"] is True
    assert score_output(EXPECTED, call(arguments={**EXPECTED["arguments"], "unrequested": True}))["correct"] is False
    assert score_output(EXPECTED, call() + call())["correct"] is False
    assert score_output(EXPECTED, call() + call("delete_everything"))["correct"] is False


@pytest.mark.parametrize("raw", [
    "", "<tool_call>broken", call("delete_everything"),
    '<tool_call><function=manage_app><parameter=action>launch</function></tool_call>',
    '<tool_call><function=manage_app><parameter=action>launch</parameter><parameter=action>close</parameter></function></tool_call>',
])
def test_bad_output_does_not_pass_as_chat(raw):
    result = score_output({"outcome": "assistant_response"}, raw)
    assert result["correct"] is None
    assert result["no_tool_compliant"] is False


def test_nonsense_chat_does_not_receive_quality_credit():
    expected = {"outcome": "assistant_response"}
    result = score_output(expected, "The moon is made of cheese.")
    assert result["correct"] is None
    assert result["no_tool_compliant"] is True
    summary = summarize_scores([{**result, "expected": expected}])
    assert summary["response_quality_accuracy"] is None
    assert summary["end_to_end_task_accuracy"] is None
    assert summary["tool_call_accuracy"] is None


def test_xml_calls_and_home_action_order():
    raw = '<tool_call><function=manage_app><parameter=action>launch</parameter><parameter=app_name>Discord</parameter></function></tool_call><|im_end|>'
    assert score_output(EXPECTED, raw)["correct"] is True
    actions = [{"action": "turn_on", "target": "living_room_light"}, {"action": "lock", "target": "front_door_lock"}]
    expected = {"outcome": "tool_call", "tool": "control_smart_home", "arguments": {"actions": actions, "goal": "Evening"}}
    assert score_output(expected, call("control_smart_home", {"actions": actions[::-1], "goal": "Secure the house"}))["correct"] is True


def test_notebook_embeds_the_same_tested_scorer():
    root = Path(__file__).resolve().parents[1]
    notebook = json.loads((root / "training_master_v2/hachi_qwen35_2b_kaggle_master_v2.ipynb").read_text(encoding="utf-8"))
    helpers = (root / "hachi_evaluation.py").read_text(encoding="utf-8").split("# Command-line rescoring")[0]
    cell = next("".join(c["source"]) for c in notebook["cells"] if "def evaluate_records(" in "".join(c.get("source", [])))
    assert cell.startswith(helpers)
    assert "score_output(record['expected'], completion)" in cell
    assert "summarize_scores(results)" in cell
    compile(cell, "notebook_evaluator", "exec")

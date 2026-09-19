"""Strict, offline scoring of Hachi model outputs; never executes tools.

Tool accuracy measures selection and arguments, not application execution.
Conversational quality requires a separate human rubric and remains unscored.
The notebook embeds these helpers via scripts/sync_master_evaluator.py.
"""
import json
import re


SCORER_VERSION = "strict_v1"
VALID_TOOLS = {
    "control_smart_home", "get_smart_home_state", "manage_app", "manage_mode",
    "run_routine", "media", "manage_productivity", "web_research", "get_weather",
    "system_control",
}


def parse_prediction(raw):
    """Parse every call, rejecting incomplete syntax, unknown tools and duplicates."""
    text = re.sub(r"(?:<\|im_end\|>|<\|endoftext\|>|<\|eot_id\|>)\s*$", "", str(raw or "")).strip()
    calls = []

    def json_call(value):
        if not isinstance(value, dict):
            raise ValueError("Tool call must be an object")
        fn = value.get("function", value)
        if not isinstance(fn, dict):
            raise ValueError("Function must be an object")
        args = fn.get("arguments", {})
        if isinstance(args, str):
            args = json.loads(args)
        return {"name": fn.get("name"), "arguments": args}

    def parse_block(block):
        function = re.fullmatch(r"<function=([\w]+)>\s*(.*?)\s*</function>", block.strip(), re.DOTALL)
        if not function:
            return json_call(json.loads(block))
        name, body = function.groups()
        args = {}
        pattern = r"<parameter=([\w]+)>\s*(.*?)\s*</parameter>"
        for match in re.finditer(pattern, body, re.DOTALL):
            key, value = match.groups()
            if key in args:
                raise ValueError("Duplicate parameter")
            try:
                args[key] = json.loads(value)
            except json.JSONDecodeError:
                args[key] = value.strip()
        if re.sub(pattern, "", body, flags=re.DOTALL).strip():
            raise ValueError("Malformed function parameters")
        return {"name": name, "arguments": args}

    try:
        if "<tool_call>" in text:
            blocks = re.findall(r"<tool_call>\s*(.*?)\s*</tool_call>", text, re.DOTALL)
            remainder = re.sub(r"<tool_call>.*?</tool_call>", "", text, flags=re.DOTALL).strip()
            if not blocks or remainder:
                raise ValueError("Incomplete or mixed tool-call output")
            calls = [parse_block(block) for block in blocks]
        elif "<function=" in text:
            calls = [parse_block(text)]
        elif any(marker in text for marker in ("tool_call", "<parameter=", "</function>", '"arguments"')):
            value = json.loads(text)
            values = value.get("tool_calls", [value]) if isinstance(value, dict) else value
            if not isinstance(values, list) or not values:
                raise ValueError("Missing tool calls")
            calls = [json_call(value) for value in values]
        elif text.startswith("{"):
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                value = None
            if isinstance(value, dict) and ("name" in value or "function" in value):
                calls = [json_call(value)]
        for call in calls:
            if call["name"] not in VALID_TOOLS:
                raise ValueError("Unknown tool")
            if not isinstance(call["arguments"], dict):
                raise ValueError("Arguments must be an object")
        return {"calls": calls, "error": None, "text": text}
    except (ValueError, TypeError, AttributeError) as exc:
        return {"calls": calls, "error": str(exc), "text": text}


def score_output(expected, raw):
    parsed = parse_prediction(raw)
    calls = parsed["calls"]
    no_tool = not calls and parsed["error"] is None and bool(parsed["text"])
    if expected["outcome"] == "assistant_response":
        return {**parsed, "correct": None, "no_tool_compliant": no_tool,
                "quality_review_required": True}
    correct = parsed["error"] is None and len(calls) == 1
    if correct:
        call = calls[0]
        wanted = dict(expected.get("arguments", {}))
        actual = dict(call["arguments"])
        if expected["tool"] == "control_smart_home":
            # Goal prose is descriptive; action/value/target accuracy is exact.
            wanted.pop("goal", None)
            actual.pop("goal", None)
            for args in (wanted, actual):
                if isinstance(args.get("actions"), list):
                    args["actions"] = sorted(json.dumps(a, sort_keys=True) for a in args["actions"])
        correct = call["name"] == expected["tool"] and actual == wanted
    return {**parsed, "correct": bool(correct), "no_tool_compliant": None,
            "quality_review_required": False}


def summarize_scores(rows):
    tool_rows = [r for r in rows if r["expected"]["outcome"] == "tool_call"]
    chat_rows = [r for r in rows if r["expected"]["outcome"] == "assistant_response"]
    return {
        "scorer_version": SCORER_VERSION,
        "records": len(rows),
        "tool_call_records": len(tool_rows),
        "tool_call_correct": sum(r["correct"] is True for r in tool_rows),
        "tool_call_accuracy": sum(r["correct"] is True for r in tool_rows) / len(tool_rows) if tool_rows else None,
        "assistant_response_records": len(chat_rows),
        "no_tool_compliance": sum(r["no_tool_compliant"] for r in chat_rows) / len(chat_rows) if chat_rows else None,
        "invalid_output_records": sum(r["error"] is not None for r in rows),
        "response_quality_accuracy": None,
        "end_to_end_task_accuracy": None,
        "limitations": ["Conversational quality is unscored and requires human review.",
                        "Tool outputs are scored without executing application actions.",
                        "No laptop latency or GGUF quality is inferred from training runs."],
    }


# Command-line rescoring
def main():
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("Use a separate output file to preserve the historical benchmark.")
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    rows = []
    for record in payload["results"]:
        score = score_output(record["expected"], record["raw"])
        rows.append({"id": record["id"], "expected": record["expected"], **score})
    summary = summarize_scores(rows)
    report = {"source": str(args.input), "summary": summary, "results": rows,
              "baseline_rescored": False}
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

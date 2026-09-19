"""Embed the tested offline scorer in the standalone Kaggle notebook."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "training_master_v2/hachi_qwen35_2b_kaggle_master_v2.ipynb"


def main():
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    helpers = (ROOT / "hachi_evaluation.py").read_text(encoding="utf-8").split("# Command-line rescoring")[0]
    for cell in notebook["cells"]:
        source = "".join(cell.get("source", []))
        if "def evaluate_records(" not in source:
            continue
        runner = source[source.index("@torch.inference_mode()") :]
        runner = runner.replace("predicted = extract_tool_call(completion)\n        correct = score_prediction(record, predicted)",
                                "score = score_output(record['expected'], completion)\n        correct = score['correct']")
        runner = runner.replace("'correct': correct, 'expected': record['expected'], 'predicted': predicted,",
                                "'expected': record['expected'], **score,")
        runner = runner.replace("'accuracy': sum(r['correct'] for r in results) / len(results),",
                                "**summarize_scores(results),\n        'latency_environment': 'training_notebook',")
        cell["source"] = (helpers + "\n\n" + runner).splitlines(keepends=True)
        cell["outputs"] = []
        cell["execution_count"] = None
        break
    else:
        raise RuntimeError("Evaluator cell not found")
    for cell in notebook["cells"]:
        source = "".join(cell.get("source", []))
        if "'baseline': base_metrics," in source and "'baseline_results': base_results," not in source:
            source = source.replace("'baseline': base_metrics,", "'baseline': base_metrics,\n    'baseline_results': base_results,")
            cell["source"] = source.splitlines(keepends=True)
    NOTEBOOK.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

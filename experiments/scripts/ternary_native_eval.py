"""Evaluate original claim-level records with pinned, unchanged upstream code.

No prose extraction, alternative scoring, inferred verdicts or scorer feedback to agents.
Old JevLoop final-answer results are not compatible with this protocol.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import sys
import tarfile
import tempfile
from pathlib import Path

from experiments.benchmark.ternary_judge.ternary_judge import TERNARY_COMMIT
from experiments.core.download import DATASET_DIR

PREFIX = f"mvp-ternary-judge-{TERNARY_COMMIT}"
VERDICTS = {"FOLLOW", "OMIT", "NULL", "UNDECIDED"}
SOURCE_SHA256 = {
    "pipeline.py": "31f574f66cab6385e2919f9a7f06571c52a19124e8b8e6a375e56ff067ad3576",
    "run_experiment.py": "ca1ed298c9b9efbcacc26f94f4bfb905c135a57ca56e983d9a179876fb65e03b",
    "data/corpus.json": "8bd2a7e4e2ae29fa88ffe716154dfaae8f28f565101c0391c7240a26bcaf48e1",
    "data/questions.json": "35508417b39e3f6e85643e0bc3a6ff4a081bdcdc77073fbf1221f1d210c6223d",
}


def evaluate(records: list[dict], *, archive: Path, tokens: dict[str, int]) -> dict:
    """Invoke upstream functions unchanged; tokens must be measured, not guessed.

    Importing upstream run_experiment requires its data and pipeline module. The
    isolated temporary directory contains only exact bytes from the pinned archive.
    """
    with tempfile.TemporaryDirectory(prefix="jev-ternary-native-") as tmp:
        root = Path(tmp)
        hashes = {}
        with tarfile.open(archive) as tf:
            for name in ("pipeline.py", "run_experiment.py", "data/corpus.json", "data/questions.json"):
                member = tf.getmember(f"{PREFIX}/{name}")
                stream = tf.extractfile(member)
                if stream is None:
                    raise ValueError(f"missing upstream source: {name}")
                data = stream.read()
                digest = hashlib.sha256(data).hexdigest()
                if digest != SOURCE_SHA256[name]:
                    raise ValueError(f"upstream bytes changed: {name}")
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                hashes[name] = hashlib.sha256(data).hexdigest()
        prior = sys.modules.get("pipeline")
        try:
            def load(name, path):
                spec = importlib.util.spec_from_file_location(name, path)
                if spec is None or spec.loader is None:
                    raise RuntimeError(f"cannot load {path}")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module
            pipeline = load("pipeline", root / "pipeline.py")
            sys.modules["pipeline"] = pipeline
            upstream = load("jev_upstream_ternary_run", root / "run_experiment.py")
            questions = {q["q_id"]: q for q in upstream.questions}
            rescored = []
            for index, record in enumerate(records):
                required = {"config", "q_id", "q_type", "claim", "verdict", "reason"}
                missing = required - record.keys()
                if missing:
                    raise ValueError(f"row {index}: missing native fields {sorted(missing)}; prose logs cannot be scored")
                q = questions[record["q_id"]]
                if record["q_type"] != q["type"]:
                    raise ValueError(f"row {index}: q_type does not match original data")
                if record["verdict"] not in VERDICTS:
                    raise ValueError(f"row {index}: invalid original verdict")
                if not isinstance(record["claim"], str) or not record["claim"].strip():
                    raise ValueError(f"row {index}: empty/non-string claim")
                rescored.append({**record, "follow_valid": pipeline.gold_check(record["claim"], q)
                                 if record["verdict"] == "FOLLOW" else None})
            configs = sorted({r["config"] for r in rescored})
            if set(configs) != set(tokens):
                raise ValueError("tokens must specify exactly every observed config")
            if any(type(v) is not int or v < 0 for v in tokens.values()):
                raise ValueError("tokens must be measured nonnegative integers")
            reports = {}
            for config in configs:
                rows = [r for r in rescored if r["config"] == config]
                reports[config] = {"metrics": upstream.metrics(rows, tokens[config]),
                                   "by_type": upstream.by_type(rows)}
            return {"evaluator": f"mvp-ternary-judge@{TERNARY_COMMIT}",
                    "source_sha256": hashes,
                    "unit": "original atomic-claim moves, not final-answer accuracy",
                    "configs": reports, "rows": rescored}
        finally:
            if prior is None:
                sys.modules.pop("pipeline", None)
            else:
                sys.modules["pipeline"] = prior


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("records", type=Path, help="original claim/verdict JSONL, not JevLoop prose results")
    parser.add_argument("--tokens", type=Path, required=True, help="JSON config -> measured total tokens")
    parser.add_argument("--archive", type=Path, default=DATASET_DIR / "_tarballs" / f"ternary-judge-{TERNARY_COMMIT}.tar.gz")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    rows = [json.loads(l) for l in args.records.read_text(encoding="utf-8").splitlines() if l.strip()]
    result = evaluate(rows, archive=args.archive, tokens=json.loads(args.tokens.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"native evaluator: {result['evaluator']}; {len(rows)} claim moves")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

"""Pin upstream claim scoring, not JevLoop final-answer heuristics."""
import json
from pathlib import Path
import pytest
from experiments.scripts.ternary_native_eval import evaluate
from experiments.benchmark.ternary_judge.ternary_judge import TERNARY_COMMIT
from experiments.core.download import DATASET_DIR
ARCHIVE = DATASET_DIR / '_tarballs' / f'ternary-judge-{TERNARY_COMMIT}.tar.gz'
pytestmark = pytest.mark.skipif(not ARCHIVE.exists(), reason='pinned upstream archive missing')

def row(claim, verdict='FOLLOW', q_id='q001', q_type='supported'):
    return dict(config='test', q_id=q_id, q_type=q_type, claim=claim, verdict=verdict, reason='fixture')

def test_preserves_original_span_ambiguity_and_absence_rules():
    rows=[row('Aldermont Systems was founded in 1998.'),row('Founded in 19980.'),
          row('Founded in 1998 or 1999.'),row('Documents do not state the founding year.')]
    r=evaluate(rows,archive=ARCHIVE,tokens={'test':100})
    assert [x['follow_valid'] for x in r['rows']] == [True,False,False,None]
    assert r['configs']['test']['metrics']['FalseFollowRate'] == .6667
    assert r['configs']['test']['metrics']['abstain_follows'] == 1

def test_coverage_remains_move_level_including_omit():
    rows=[row('founded in 1998'),row('unimportant', 'OMIT'),row('unknown','UNDECIDED')]
    r=evaluate(rows,archive=ARCHIVE,tokens={'test':99})
    m=r['configs']['test']['metrics']
    assert m['moves']==3 and m['Coverage']==.6667
    assert m['CostPerCorrectAnswer']==99

def test_rejects_old_prose_results_instead_of_extracting_claims():
    with pytest.raises(ValueError,match='missing native fields'):
        evaluate([{'task_id':'q001','correct':True}],archive=ARCHIVE,tokens={'test':0})

def test_requires_explicit_measured_token_totals():
    with pytest.raises(ValueError,match='exactly every'):
        evaluate([row('founded in 1998')],archive=ARCHIVE,tokens={})


def test_all_published_moves_match_unmodified_upstream_functions():
    """Independent invocation on every archived move; token counts are test fixtures."""
    import ast
    import tarfile
    from experiments.scripts.ternary_native_eval import PREFIX
    with tarfile.open(ARCHIVE) as tf:
        pipeline_source = tf.extractfile(f'{PREFIX}/pipeline.py').read().decode()
        runner_source = tf.extractfile(f'{PREFIX}/run_experiment.py').read().decode()
        questions = json.load(tf.extractfile(f'{PREFIX}/data/questions.json'))
        records = [json.loads(l) for l in tf.extractfile(
            f'{PREFIX}/results/live_results.jsonl').read().decode().splitlines() if l.strip()]
    namespace = {}
    exec(compile(pipeline_source, '<original-pipeline>', 'exec'), namespace)
    # Avoid top-level filesystem operations, execute exact original function nodes.
    parsed = ast.parse(runner_source)
    functions = ast.Module(body=[n for n in parsed.body if isinstance(n, ast.FunctionDef)
                                 and n.name in ('metrics', 'by_type')], type_ignores=[])
    exec(compile(functions, '<original-functions>', 'exec'), namespace)
    by_id = {q['q_id']: q for q in questions}
    expected = [{**r, 'follow_valid': namespace['gold_check'](r['claim'], by_id[r['q_id']])
                 if r['verdict'] == 'FOLLOW' else None} for r in records]
    fixture_tokens = {c: 12345 for c in {r['config'] for r in records}}
    actual = evaluate(records, archive=ARCHIVE, tokens=fixture_tokens)
    assert len(records) == 636
    assert actual['rows'] == expected
    for config, token_count in fixture_tokens.items():
        rows = [r for r in expected if r['config'] == config]
        assert actual['configs'][config]['metrics'] == namespace['metrics'](rows, token_count)
        assert actual['configs'][config]['by_type'] == namespace['by_type'](rows)


def test_modified_upstream_bytes_are_rejected(tmp_path):
    import io
    import tarfile
    from experiments.scripts.ternary_native_eval import PREFIX
    changed = tmp_path / 'changed.tar.gz'
    with tarfile.open(ARCHIVE) as original, tarfile.open(changed, 'w:gz') as target:
        member = tarfile.TarInfo(f'{PREFIX}/pipeline.py')
        data = original.extractfile(member.name).read() + b'\n# changed\n'
        member.size = len(data)
        target.addfile(member, io.BytesIO(data))
    with pytest.raises(ValueError, match='upstream bytes changed'):
        evaluate([], archive=changed, tokens={})

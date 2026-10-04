"""Run pinned upstream atomic-claim protocol, with non-intervening request logs.

Original retrieval, generation prompt, binary/ternary policies, certificate rule
and metrics run unchanged. The jev arm uses a separately declared typed-choice
policy; it is a claim-controller experiment, not the full seven-node harness.
No mock fallback, prose-to-claim extraction or hidden-gold feedback is permitted.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import time

from experiments.core.env import load_env
from experiments.core.models import Message, OpenAICompatModel, Thinking
from experiments.core.runlog import repo_commit, utc_stamp
from experiments.core.download import DATASET_DIR
from experiments.scripts.ternary_native_eval import PREFIX, SOURCE_SHA256, evaluate
import hashlib
from dataclasses import asdict
from experiments.core.deciding import HttpJevClient, DecideRequest, PINNED_JEV_MODEL, DEFAULT_JEV_URL


class JevClaimController:
    """Our method's genuine claim commit decision; upstream evaluator stays unchanged.

    This is not the author's quote-certified ternary policy: Jev returns a typed
    choice, not an exact quote certificate. It must be reported as a separate method.

    ★★ **`retries` 是这次要测的东西。** 上游作者的 `ternary_judge` **自带重做**：

        if verdict == "UNDECIDED":
            more = retrieve(question + " " + claim, all_docs, k=6)   # 补证据
            raw2 = ternary_judge_raw(llm, claim, q, more)            # 重判

    而我们原来的 `jev` 臂**一次就定**。所以那一场"作者 0 假成功 vs 我们 2"的对比里，
    **对方带着重试机制、我们没有** —— 那是个混杂，而这个开关就是为了拆掉它。
    补证据用的是**上游同一个 `retrieve`**，所以差异只剩"谁来判"，不是"怎么捞"。
    """
    def __init__(self, client, path, *, retries: int = 0, retrieve=None, all_docs=None,
                 grounded: bool = False):
        self.client, self.path = client, path
        self.tokens = 0
        self.retries = int(retries)
        #: ★★ **FOLLOW 必须举证。** 上游作者的 `fixed_rule` 就是这个：
        #:   FOLLOW/NULL 没有一段**逐字引文**（且 >=12 字符、且是某篇文档的子串）
        #:   就降级成 UNDECIDED。我们没有这一步，于是把
        #:   「X does not have a CTO listed」这类**缺席声明**当成了可提交的结论 ——
        #:   而作者结构上不可能这么干：缺席引不出引文。
        #:   Jev 只能做选择题，所以"引文"用**哪篇文档证明它**来表达 + 一个确定性检查。
        self.grounded = bool(grounded)
        self.grounding_log: list[dict] = []
        #: 上游的 `pipeline.retrieve` —— **补证据用它，不是我们另写一个**。
        self.retrieve = retrieve
        self.all_docs = all_docs
        #: ★ 逐条恢复账：问了几次、救回没有、原来的判决是什么。
        self.recovery: list[dict] = []

    def _ask_grounding(self, claim, question, docs):
        """★ 「哪一篇文档**证明了**这条 claim」——选项是 doc_id 加一个 none。

        这是"举证"在 choice-only 接口里的表达方式：作者的 `fixed_rule` 要求
        一段逐字引文，而 Jev 给不出自由文本。**用户选中哪篇，就是它的引文。**
        选 `none` = 它承认没有引文可引 ⇒ 那就不该提交。
        """
        options = [d['doc_id'] for d in docs] + ['none_of_the_provided_documents']
        request = DecideRequest(state={"question": question["question"], "claim": claim,
            "documents": [{"doc_id": d["doc_id"], "text": d["text"]} for d in docs]},
            questions={"grounding": {"type": "choice",
                "instructions": ("Which single provided document, if any, states this claim "
                                 "verbatim or with an explicit number/name that certifies it?"),
                "criteria": {o: "select if this document certifies the claim as stated"
                             for o in options[:-1]}
                            | {options[-1]: "select if NO provided document certifies the claim "
                                            "(for example the claim only reports that something is missing)"}}})
        try:
            response = self.client.decide(request)
        except Exception as exc:
            with self.path.open('a', encoding='utf-8') as fh:
                fh.write(json.dumps({'q_id': question['q_id'], 'kind': 'grounding',
                                     'request': asdict(request),
                                     'error': {'type': type(exc).__name__, 'message': str(exc)}},
                                    ensure_ascii=False) + '\n')
            raise
        self.tokens += response.input_tokens + response.output_tokens
        with self.path.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps({'q_id': question['q_id'], 'kind': 'grounding',
                                 'request': asdict(request), 'response': asdict(response)},
                                ensure_ascii=False) + '\n')
        a = response.answers.get('grounding')
        if response.degraded or a is None or a.kind != 'choice':
            raise RuntimeError('Jev grounding unusable; no guessed certificate')
        return a.choice, options[-1]

    def _ask_once(self, claim, question, docs):
        request = DecideRequest(state={"question": question["question"], "claim": claim,
            "documents": [{"doc_id": d["doc_id"], "text": d["text"]} for d in docs]},
            questions={"commit": {"type": "choice", "instructions":
                "Decide whether this atomic claim should be committed as an answer. "
                "Consider all provided documents, including conflicting sources.",
                "criteria": {"FOLLOW": "The claim is supported and relevant to the question, with no unresolved conflicting evidence.",
                             "OMIT": "The claim is inessential to the requested answer.",
                             "NULL": "The claim contradicts the evidence.",
                             "UNDECIDED": "Available evidence is absent, conflicting, or insufficient to certify the claim."}}})
        try:
            response = self.client.decide(request)
        except Exception as exc:
            with self.path.open('a', encoding='utf-8') as fh:
                fh.write(json.dumps({'q_id': question['q_id'], 'request': asdict(request),
                                     'error': {'type': type(exc).__name__, 'message': str(exc)}},
                                    ensure_ascii=False) + '\n')
            raise
        self.tokens += response.input_tokens + response.output_tokens
        with self.path.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps({"q_id": question['q_id'], "request": asdict(request),
                                 "response": asdict(response)}, ensure_ascii=False)+'\n')
        answer = response.answers.get('commit')
        if response.degraded or response.missing or response.dropped or answer is None or answer.kind != 'choice':
            raise RuntimeError('Jev returned incomplete/degraded decision; no mock or guessed verdict')
        if answer.choice not in {'FOLLOW','OMIT','NULL','UNDECIDED'}:
            raise RuntimeError('Jev returned invalid verdict')
        return answer.choice

    def decide(self, claim, question, docs):
        """一次判定；不够就**按上游同一套检索补证据再判**（`retries` 次）。"""
        first = self._ask_once(claim, question, docs)
        verdict = first
        downgraded = ''
        if self.grounded and first == 'FOLLOW':
            cite, none = self._ask_grounding(claim, question, docs)
            if cite == none:
                # ★ 判它 FOLLOW 却拿不出引文 ⇒ **降级**，和上游 `fixed_rule` 同一个处置。
                verdict = 'UNDECIDED'
                downgraded = 'no_certificate'
            self.grounding_log.append({'q_id': question['q_id'], 'claim': claim,
                                       'cite': cite, 'downgraded': bool(downgraded)})
        attempts = 1
        while verdict == 'UNDECIDED' and attempts <= self.retries:
            if self.retrieve is None or self.all_docs is None:
                break
            # ★ 和上游逐字同形：把**问题 + claim** 一起拿去检索，k=6。
            more = self.retrieve(question["question"] + " " + claim, self.all_docs, k=6)
            verdict = self._ask_once(claim, question, more)
            attempts += 1
        self.recovery.append({"q_id": question["q_id"], "claim": claim,
                              "first": first, "final": verdict, "attempts": attempts,
                              "recovered": first == 'UNDECIDED' and verdict != 'UNDECIDED',
                              "grounding_downgrade": downgraded})
        return verdict


class LoggedClient:
    """Only bridge the upstream chat signature; never repair model output."""
    def __init__(self, model, path, *, effort=None, max_tokens=None):
        self.model, self.path = model, path
        self.thinking = Thinking(effort=effort) if effort else None
        self.max_tokens = max_tokens
        self.tokens = 0
        self.calls = 0
        self.context = {}

    def chat(self, system, user):
        started = time.perf_counter()
        reply = self.model.chat([Message(role='system', content=system),
                                 Message(role='user', content=user)],
                                max_tokens=self.max_tokens, temperature=0,
                                thinking=self.thinking)
        usage = reply.input_tokens_cached + reply.input_tokens_uncached + reply.output_tokens_reasoning + reply.output_tokens_visible
        self.tokens += usage
        self.calls += 1
        with self.path.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps({**self.context, 'call':self.calls, 'system':system,
                'user':user, 'response':reply.text, 'reasoning_content':reply.reasoning_content,
                'tokens':usage, 'elapsed_ms':(time.perf_counter()-started)*1000}, ensure_ascii=False)+'\n')
        return reply.text


def main(argv=None):
    load_env(Path(__file__).resolve().parents[1])
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive', type=Path, default=DATASET_DIR/'_tarballs'/f'{PREFIX.removeprefix("mvp-")}.tar.gz')
    p.add_argument('--questions',default='q001,q061,q091,q121')
    p.add_argument('--configs',default='direct,binary,ternary')
    p.add_argument('--shared-candidates',action='store_true',help='controller ablation on identical generated claims; not full upstream pipeline reproduction')
    p.add_argument('--candidates-from',type=Path,help='reuse candidates.json and measured shared-generation usage from a previous run directory')
    p.add_argument('--jev-timeout',type=float,default=60.0)
    p.add_argument('--jev-grounded',action='store_true',
                   help='FOLLOW 必须能引出一篇文档，否则降级 UNDECIDED（上游 fixed_rule 的处置）')
    p.add_argument('--jev-retries',type=int,default=0,
                   help='UNDECIDED 后按上游同一套检索补证据再判几次。'
                        '上游 ternary 自带一次 k=3→k=6 的重做；这个开关是为了公平对比')
    p.add_argument('--jev-url',default=DEFAULT_JEV_URL)
    p.add_argument('--jev-key',default=None)
    p.add_argument('--jev-model',default=PINNED_JEV_MODEL)
    p.add_argument('--model',default='qwen3.5-9b-local')
    p.add_argument('--base-url',default='http://127.0.0.1:8001/v1')
    p.add_argument('--api-key',default=None)
    p.add_argument('--effort',choices=['low','high','max'])
    p.add_argument('--max-tokens',type=int,default=None)
    # Upstream keeps generator and judge separate (gen=qwen-plus, jud=qwen-turbo).
    # The author's binary/ternary judges parse bare JSON with json.loads, so a judge
    # that wraps output in ```json fences crashes the unchanged pipeline. That is a
    # property of the judge model we supply, not of the benchmark, so it is a flag.
    p.add_argument('--judge-model',default=None,help='defaults to --model')
    p.add_argument('--judge-base-url',default=None,help='defaults to --base-url')
    p.add_argument('--judge-api-key',default=None,help='defaults to --api-key')
    p.add_argument('--judge-effort',choices=['low','high','max'],default=None)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(argv)
    configs=a.configs.split(',')
    if any(c not in ('direct','binary','ternary','jev','jev-retry','jev-grounded') for c in configs):p.error('configs: direct,binary,ternary,jev,jev-retry,jev-grounded')
    if a.shared_candidates and a.candidates_from:
        p.error('choose --shared-candidates or --candidates-from')
    if a.candidates_from and any(c not in ('direct','binary','ternary','jev','jev-retry','jev-grounded') for c in configs):
        p.error('--candidates-from supports direct,binary,ternary,jev')
    if a.shared_candidates and any(c not in ('direct','binary','ternary','jev','jev-retry','jev-grounded') for c in configs):
        p.error('shared-candidates supports direct,binary,ternary,jev')
    if a.output.exists():p.error('output directory exists; do not overwrite a run')
    a.output.mkdir(parents=True)
    commit,dirty=repo_commit(Path(__file__).resolve().parents[2])
    (a.output/'meta.json').write_text(json.dumps({'protocol':PREFIX,'model':a.model,'base_url':a.base_url,
        'effort':a.effort,'max_tokens':a.max_tokens,'commit':commit,'dirty':dirty,
        'questions':a.questions,'configs':configs,'development_subset':True,
        'jev_model':a.jev_model if any(c.startswith('jev') for c in configs) else None,
        'jev_url':a.jev_url if any(c.startswith('jev') for c in configs) else None,
        'policy_note':'jev is our typed-choice policy, not upstream quote-certified ternary policy',
        'shared_candidates':a.shared_candidates or bool(a.candidates_from),
        'candidates_from':str(a.candidates_from) if a.candidates_from else None,
        'jev_timeout_s':a.jev_timeout,
        'jev_retries':a.jev_retries,
        'jev_grounded':a.jev_grounded,
        'judge_model':a.judge_model or a.model,
        'judge_effort':a.judge_effort,
        'note':'shared-candidate controller ablation' if a.shared_candidates else 'separate generations per config, as upstream; not paired cached candidates'},indent=2))
    client=LoggedClient(OpenAICompatModel(base_url=a.base_url,api_key=a.api_key or os.environ.get('DEEPSEEK_API_KEY','local'),
        model_id=a.model,model_version='server-reported',provider='openai-compat'),a.output/'requests.jsonl',effort=a.effort,max_tokens=a.max_tokens)
    judge=client
    if a.judge_model and a.judge_model!=a.model:
        judge=LoggedClient(OpenAICompatModel(base_url=a.judge_base_url or a.base_url,
            api_key=a.judge_api_key or a.api_key or os.environ.get('DEEPSEEK_API_KEY','local'),
            model_id=a.judge_model,model_version='server-reported',provider='openai-compat'),
            a.output/'judge-requests.jsonl',effort=a.judge_effort,max_tokens=a.max_tokens)
    jev=None
    if any(c.startswith('jev') for c in configs):
        key=a.jev_key or os.environ.get('TYPESAFE_API_KEY')
        if not key: raise SystemExit('jev config requires --jev-key or TYPESAFE_API_KEY')
        jev=JevClaimController(HttpJevClient(a.jev_url,key,model=a.jev_model,timeout_s=a.jev_timeout),
                               a.output/'jev-decisions.jsonl', retries=a.jev_retries,
                               grounded=a.jev_grounded)
    records=[]; costs={}; completed=False
    prior=sys.modules.get('pipeline')
    try:
        with tempfile.TemporaryDirectory(prefix='jev-native-run-') as tmp:
            root=Path(tmp)
            with tarfile.open(a.archive) as tf:
                for name,digest in SOURCE_SHA256.items():
                    data=tf.extractfile(f'{PREFIX}/{name}').read()
                    if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('changed upstream bytes')
                    target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
            def load(name,file):
                spec=importlib.util.spec_from_file_location(name,file);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
            pipeline=load('pipeline',root/'pipeline.py');sys.modules['pipeline']=pipeline
            upstream=load('jev_native_upstream_run',root/'run_experiment.py')
            if jev is not None:
                # ★ 补证据用的是**上游同一个 `retrieve`** —— 差异只剩"谁来判"，不是"怎么捞"
                jev.retrieve = pipeline.retrieve
                jev.all_docs = upstream.docs
            byid={q['q_id']:q for q in upstream.questions}
            qs=[byid[qid] for qid in a.questions.split(',')]
            candidates={}
            candidate_cost=0
            if a.candidates_from:
                candidates=json.loads((a.candidates_from/'candidates.json').read_text())
                requests=[json.loads(l) for l in (a.candidates_from/'requests.jsonl').read_text().splitlines() if l.strip()]
                candidate_cost=sum(r['tokens'] for r in requests if r.get('config')=='shared-generation')
                if not requests or any(q['q_id'] not in candidates for q in qs):
                    raise ValueError('missing cached candidates or usage records')
                (a.output/'candidates.json').write_text(json.dumps(candidates,ensure_ascii=False,indent=2))
            elif a.shared_candidates:
                for q in qs:
                    client.context={'config':'shared-generation','q_id':q['q_id']}
                    docs=pipeline.retrieve(q['question'],upstream.docs,k=3)
                    candidates[q['q_id']]=(docs,pipeline.generate(client,q,docs))
                candidate_cost=client.tokens
                (a.output/'candidates.json').write_text(json.dumps(candidates,ensure_ascii=False,indent=2))
            for config in configs:
                before=client.tokens
                before_judge=judge.tokens
                before_jev=jev.tokens if jev is not None else 0
                for q in qs:
                    client.context={'config':config,'q_id':q['q_id']}
                    if a.shared_candidates or a.candidates_from:
                        docs,claims=candidates[q['q_id']]
                        # ★ 同一个控制器对象服务两个配置 ⇒ **每次按配置设重试次数**，
                        #   否则 `jev` 与 `jev-retry` 会在同一次运行里混成一条臂。
                        if jev is not None and config in ('jev','jev-retry','jev-grounded'):
                            jev.retries = a.jev_retries if config=='jev-retry' else 0
                            jev.grounded = (config=='jev-grounded')
                        rows=[]
                        for claim in claims:
                            # Same claims, same retrieval context for every controller.
                            # binary/ternary call the author's unchanged judge functions.
                            if config=='direct': verdict,reason='FOLLOW','NO_JUDGE'
                            elif config=='binary':
                                verdict='FOLLOW' if pipeline.binary_judge(judge,claim,docs) else 'NULL'
                                reason='BINARY'
                            elif config=='ternary':
                                verdict,reason=pipeline.ternary_judge(judge,claim,q,docs,upstream.docs)
                            elif config=='jev-retry': verdict,reason=jev.decide(claim,q,docs),'jev-http-native-retry'
                            elif config=='jev-grounded': verdict,reason=jev.decide(claim,q,docs),'jev-http-native-grounded'
                            else: verdict,reason=jev.decide(claim,q,docs),'jev-http-native'
                            rows.append({'config':config,'q_id':q['q_id'],'q_type':q['type'],'claim':claim,
                                         'verdict':verdict,'reason':reason,
                                         'follow_valid':None})
                    elif config in ('jev','jev-retry','jev-grounded'):
                        docs = pipeline.retrieve(q['question'], upstream.docs, k=3)
                        claims = pipeline.generate(client, q, docs)
                        rows=[]
                        for claim in claims:
                            verdict=jev.decide(claim,q,docs)
                            rows.append({'config':'jev','q_id':q['q_id'],'q_type':q['type'],'claim':claim,
                                         'verdict':verdict,'reason':'jev-http-native','follow_valid':None})
                    else:
                        rows=upstream.run_config(config,config,client,judge,[q])
                    records.extend(rows)
                    with (a.output/'claims.jsonl').open('a',encoding='utf-8') as fh:
                        for row in rows:fh.write(json.dumps(row,ensure_ascii=False)+'\n')
                    print(f"{config} {q['q_id']}: {len(rows)} atomic claims",flush=True)
                if a.shared_candidates or a.candidates_from:
                    # cached mode: no generation here, so client.tokens delta is the
                    # author's own judge usage for binary/ternary (zero for direct).
                    costs[config]=candidate_cost + (client.tokens-before) + (judge.tokens-before_judge) + ((jev.tokens-before_jev) if config in ('jev','jev-retry','jev-grounded') else 0)
                else:
                    costs[config]=(client.tokens-before) + (judge.tokens-before_judge) + ((jev.tokens-before_jev) if config in ('jev','jev-retry','jev-grounded') else 0)
            report=evaluate(records,archive=a.archive,tokens=costs)
            (a.output/'tokens.json').write_text(json.dumps(costs,indent=2))
            (a.output/'native_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
            completed=True
            print(json.dumps(report['configs'],ensure_ascii=False,indent=2))
    except Exception as exc:
        # Keep the native failure visible and preserve partial raw records. Do not
        # turn a timeout into a verdict, retry through Mock, or emit partial metrics.
        (a.output/'error.json').write_text(json.dumps({
            'type': type(exc).__name__, 'message': str(exc),
            'calls': client.calls, 'claim_moves': len(records),
            'partial_claims': 'claims.jsonl',
            'partial_decisions': 'jev-decisions.jsonl',
        }, ensure_ascii=False, indent=2) + '\n')
        raise
    finally:
        if prior is None:sys.modules.pop('pipeline',None)
        else:sys.modules['pipeline']=prior
        (a.output/'exit.json').write_text(json.dumps({'completed':completed,'calls':client.calls,'claim_moves':len(records)},indent=2))
    return 0

if __name__=='__main__':raise SystemExit(main())

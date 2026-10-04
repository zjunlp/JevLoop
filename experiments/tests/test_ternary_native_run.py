"""Check the native protocol bridge does not rewrite prompts or model responses."""
import json
from experiments.core.models import ModelReply
from experiments.scripts.ternary_native_run import LoggedClient

def test_bridge_preserves_raw_response_and_counts_usage(tmp_path):
    class Model:
        def chat(self,messages,**kwargs):
            assert [(m.role,m.content) for m in messages]==[('system','original system'),('user','original input')]
            assert kwargs['max_tokens'] is None
            return ModelReply(text='not valid JSON',input_tokens_cached=2,input_tokens_uncached=3,
                              output_tokens_reasoning=4,output_tokens_visible=5)
    client=LoggedClient(Model(),tmp_path/'requests.jsonl')
    client.context={'config':'direct','q_id':'q001'}
    assert client.chat('original system','original input')=='not valid JSON'
    assert client.tokens==14
    record=json.loads((tmp_path/'requests.jsonl').read_text())
    assert record['response']=='not valid JSON' and record['q_id']=='q001'

def test_bridge_propagates_backend_failure_without_mock(tmp_path):
    import pytest
    class Model:
        def chat(self,*args,**kwargs): raise RuntimeError('backend unavailable')
    client=LoggedClient(Model(),tmp_path/'requests.jsonl')
    with pytest.raises(RuntimeError,match='backend unavailable'):
        client.chat('s','u')
    assert client.tokens==0 and not client.path.exists()

def test_jev_preserves_decision_and_does_not_receive_gold(tmp_path):
    from experiments.scripts.ternary_native_run import JevClaimController
    from experiments.core.deciding import DecideResponse, Answer
    class Client:
        def decide(self, request):
            assert 'gold_claims' not in request.state
            assert request.state['question']=='question'
            return DecideResponse(answers={'commit':Answer(kind='choice',choice='UNDECIDED')},
                                  provider='test',input_tokens=12)
    ctl=JevClaimController(Client(),tmp_path/'decisions.jsonl')
    assert ctl.decide('claim',{'q_id':'q1','question':'question','gold_claims':['secret']},[])=='UNDECIDED'
    assert ctl.tokens==12

def test_jev_timeout_records_request_and_propagates(tmp_path):
    import pytest
    from experiments.scripts.ternary_native_run import JevClaimController
    class Client:
        def decide(self, request): raise TimeoutError('read timeout')
    ctl=JevClaimController(Client(),tmp_path/'decisions.jsonl')
    with pytest.raises(TimeoutError): ctl.decide('claim',{'q_id':'q1','question':'question'},[])
    record=json.loads(ctl.path.read_text())
    assert record['q_id']=='q1' and record['error']['type']=='TimeoutError'
    assert 'response' not in record

def test_jev_degraded_response_is_error_not_invented_verdict(tmp_path):
    import pytest
    from experiments.scripts.ternary_native_run import JevClaimController
    from experiments.core.deciding import DecideResponse
    class Client:
        def decide(self, request): return DecideResponse(answers={},provider='test',degraded=True,missing=['commit'])
    ctl=JevClaimController(Client(),tmp_path/'decisions.jsonl')
    with pytest.raises(RuntimeError,match='no mock'): ctl.decide('claim',{'q_id':'q1','question':'question'},[])


def test_jev_retries_on_undecided_with_upstream_retrieval(tmp_path):
    """★★ 上游作者的 `ternary_judge` **自带重做**：

        if verdict == "UNDECIDED":
            more = retrieve(question + " " + claim, all_docs, k=6)
            raw2 = ternary_judge_raw(llm, claim, q, more)

    而我们原来的 `jev` 臂**一次就定** —— 那场"作者 0 假成功 vs 我们 2"的对比里，
    对方带着重试、我们没有。这个测试钉的是"我们也能补证据"。
    """
    from experiments.scripts.ternary_native_run import JevClaimController
    from experiments.core.deciding import DecideResponse, Answer

    class Client:
        def __init__(self): self.n = 0; self.states = []
        def decide(self, request):
            self.n += 1
            self.states.append([d['doc_id'] for d in request.state['documents']])
            choice = 'UNDECIDED' if self.n == 1 else 'FOLLOW'
            return DecideResponse(answers={'commit': Answer(kind='choice', choice=choice)},
                                  provider='test', input_tokens=5, output_tokens=1)

    calls = []
    def retrieve(query, docs, k=3):
        calls.append((query, k))
        return docs[-2:]          # 「补来的」证据

    c = Client()
    ctl = JevClaimController(c, tmp_path/'d.jsonl', retries=1,
                             retrieve=retrieve, all_docs=[{'doc_id': f'd{i}', 'text': 't'} for i in range(6)])
    q = {'q_id': 'q1', 'question': 'Who is the CTO?'}
    assert ctl.decide('claim x', q, [{'doc_id': 'd0', 'text': 't'}]) == 'FOLLOW'

    # ① 真的补了一次证据，而且是上游那套检索（问题 + claim，k=6）
    assert calls == [('Who is the CTO? claim x', 6)], calls
    # ② 第二次判的是**补来的那批**证据
    assert c.states[0] == ['d0'] and c.states[1] == ['d4', 'd5'], c.states
    # ③ 恢复账记下来了 —— 「救回来几条、救对没救对」全靠它
    assert ctl.recovery == [{'q_id': 'q1', 'claim': 'claim x',
                             'first': 'UNDECIDED', 'final': 'FOLLOW',
                             'attempts': 2, 'recovered': True,
                             'grounding_downgrade': ''}]


def test_jev_retries_zero_keeps_the_old_single_shot_behaviour(tmp_path):
    """★ `retries=0` 必须**一步都不多走** —— 否则新旧两批不可比。"""
    from experiments.scripts.ternary_native_run import JevClaimController
    from experiments.core.deciding import DecideResponse, Answer

    class Client:
        def __init__(self): self.n = 0
        def decide(self, request):
            self.n += 1
            return DecideResponse(answers={'commit': Answer(kind='choice', choice='UNDECIDED')},
                                  provider='test')

    c = Client()
    ctl = JevClaimController(c, tmp_path/'d.jsonl', retries=0,
                             retrieve=lambda *a, **k: (_ for _ in ()).throw(AssertionError('不该补证据')),
                             all_docs=[{'doc_id': 'd0', 'text': 't'}])
    assert ctl.decide('x', {'q_id': 'q1', 'question': 'Q'}, [{'doc_id': 'd0', 'text': 't'}]) == 'UNDECIDED'
    assert c.n == 1


def test_grounded_follow_needs_a_certificate(tmp_path):
    """★★★ **判它 FOLLOW，却拿不出一篇文档来证**，就得降级。

    上游作者的 `fixed_rule` 就是这个：FOLLOW/NULL 没有一段逐字引文
    （且 >=12 字符、且是某篇文档的子串）⇒ 降级 UNDECIDED。

    我们没有这一步，于是把「X does not have a CTO listed」这类**缺席声明**
    当成了可提交的结论（实测 2 条假成功）—— 而作者**结构上不可能**这么干：
    缺席引不出引文。**缺的是"举证"，不是判官。**
    """
    from experiments.scripts.ternary_native_run import JevClaimController
    from experiments.core.deciding import DecideResponse, Answer

    class Client:
        def __init__(self, cite): self.cite = cite; self.asks = []
        def decide(self, request):
            node = next(iter(request.questions))
            self.asks.append((node, tuple(request.questions[node].get('criteria', {}))))
            if node == 'commit':
                return DecideResponse(answers={'commit': Answer(kind='choice', choice='FOLLOW')}, provider='t')
            return DecideResponse(answers={'grounding': Answer(kind='choice', choice=self.cite)}, provider='t')

    docs = [{'doc_id': 'd1', 'text': 'x'}, {'doc_id': 'd2', 'text': 'y'}]
    q = {'q_id': 'q1', 'question': 'Who is the CTO?'}

    # ① 引得出文档 ⇒ FOLLOW 保留
    c = Client('d1'); ctl = JevClaimController(c, tmp_path/'a.jsonl', grounded=True)
    assert ctl.decide('claim', q, docs) == 'FOLLOW'
    assert ctl.grounding_log[0]['cite'] == 'd1' and not ctl.grounding_log[0]['downgraded']

    # ② 引不出来（none）⇒ 降级，且账上记明原因
    c = Client('none_of_the_provided_documents')
    ctl = JevClaimController(c, tmp_path/'b.jsonl', grounded=True)
    assert ctl.decide('X does not have a CTO listed', q, docs) == 'UNDECIDED'
    assert ctl.recovery[0]['grounding_downgrade'] == 'no_certificate'

    # ③ 不开关时一步都不多走 —— 否则新旧两批不可比
    c = Client('d1'); ctl = JevClaimController(c, tmp_path/'c.jsonl', grounded=False)
    assert ctl.decide('claim', q, docs) == 'FOLLOW'
    assert [n for n, _ in c.asks] == ['commit']

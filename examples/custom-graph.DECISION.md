# Custom graph fixture

schema: decision-contract/v1

This fixture shows that a host may declare decision nodes that are not JevLoop's
seven reference nodes. The host-owned graph in `external-host.ts` supplies the
transitions.

## classify_issue

kind: choice
when: host:issue-triage —— classify the incoming issue

### route

ask: Which host phase should handle this issue?

- inspect — the repository needs inspection
- escalate — the issue cannot be handled automatically

frame:
  + task 300 —— the issue determines the initial route
  - output —— no tool output exists at entry

policy:
  - top >= 0.6 → call
  - else → escalate

## interpret_failure

kind: choice
when: host:test-failure —— choose the next action after a failed test

### response

ask: What should the host do with this test failure?

- fixable — another patch attempt is justified
- blocked — a human must review the failure

frame:
  + output 400 —— the failed test is the evidence for classification
  + task 300 —— the task gives the failure its scope
  - answer —— no final answer exists yet

policy:
  - top >= 0.6 → call
  - else → escalate

## request_review

kind: noul
when: host:review —— decide whether the candidate needs human review

ask: The candidate patch should be sent to a human reviewer

- true — the patch has unresolved risk or insufficient evidence
- false — the host may finish without human review

frame:
  + evidence 500 —— review depends on the recorded patch evidence
  - output —— the raw last tool output is not the review decision

policy:
  - prob:true >= 0.6 → ask_human
  - else → finish

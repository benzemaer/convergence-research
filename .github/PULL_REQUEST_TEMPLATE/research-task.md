# Research Task PR

## Task

task_id:
task_title:
workflow_mode: same_pr | split_pr
phase: implementation_review | formal_result_review

## Implementation review

implementation_review_status: pending | approved
reviewed_implementation_sha:
formal_run_allowed: false | true

### Implementation contents

- code:
- config/schema:
- runner/validator:
- unit/synthetic tests:
- formal run runbook:

### Tests actually executed

- command:
- result:

## Formal run

formal_run_status: not_started | completed | needs_rerun
formal_execution_sha:
run_id:

## Formal results

- compact results:
- manifest:
- result analysis:
- large local artifacts and hashes:

## User result decision

result_review_status: not_started | pending | accepted | needs_revision
next_task_allowed: false | true
readme_advanced: false | true

Formal run is forbidden until the user explicitly approves `reviewed_implementation_sha`.

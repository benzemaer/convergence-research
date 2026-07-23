from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_t05_config_freezes_anchor_without_selecting_q() -> None:
    config = json.loads(_text("configs/r2a/r2a_t05_ca_exit_decomposition.v1.json"))
    assert config["research_anchor_q"] == 2000
    assert config["research_anchor_role"] == "exit_mechanism_decomposition"
    assert config["q_selection_status"] == "not_selected"
    assert config["canonical_dynamic_request_selected"] is False
    assert config["formal_run_allowed"] is False
    assert config["formal_run_started"] is False
    assert config["real_score_data_read"] is False
    assert config["formal_artifacts_generated"] is False
    assert config["R2A-T05_DONE"] == "absent"
    assert config["R2A-T06_allowed_to_start"] is False
    assert [item["logical_request_name"] for item in config["requests"]] == [
        "CA_q10_k5",
        "CA_q15_k5",
        "CA_q20_k5",
        "CA_q25_k5",
    ]


def test_t05_route_is_preserved_after_t06_successor_start() -> None:
    stage = _text("docs/stages/R2A_PCAVT动态收敛状态体系.md")
    task = _text("docs/tasks/R2A-T05_CA退出机制与跨q结构分解.md")
    handoff = _text("HANDOFF.md")
    assert "R2A-T05：CA q20 退出机制与跨 q 结构分解" in stage
    assert "R2A-T06：CA 连续失效退出确认与迟滞规则选择" in stage
    assert "R2A-T07：版本注册与消费者契约冻结" in stage
    assert "q20 仅是 `exit_mechanism_decomposition` research anchor" in handoff
    assert "T06 的 no-lookahead/PIT 要求保留" in task
    assert (
        "R2A-T06_status: implementation_candidate_remediation_pending_successor_review"
        in handoff
    )
    assert "formal_run_started: false" in task


def test_t06_successor_does_not_create_formal_done() -> None:
    assert not (ROOT / "configs/r2a/r2a_t06.v1.json").exists()
    assert not (ROOT / "schemas/r2a/r2a_t06.schema.json").exists()
    assert not (ROOT / "scripts/r2a/run_r2a_t06.py").exists()
    assert not list((ROOT / "data/generated/r2a").glob("r2a_t06*/DONE"))

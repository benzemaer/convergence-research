from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


class R1T04ValidationError(RuntimeError):
    pass


def validate_r1_t04_state_line_profiles(*, summary_path: Path, result_package_path: Path | None = None, output_path: Path | None = None, root: Path = ROOT) -> dict[str, Any]:
    errors: list[str] = []
    summary = _load(summary_path, errors, "summary")
    if summary.get("task_id") != "R1-T04": errors.append("task_id_mismatch")
    if summary.get("status") != "completed": errors.append("summary_not_completed")
    outputs = summary.get("output_paths", {})
    required = {"state_line_profile_csv":14,"state_line_profile_json":14,"duration_profile_csv":14,"reference_challenger_comparison_csv":10,"daily_overlap_profile_csv":10,"parent_child_profile_csv":8,"year_concentration_profile_csv":1,"diagnostic_summary":1,"anomaly_scan":1}
    for name, minimum in required.items():
        item=outputs.get(name)
        if not item: errors.append(f"missing_output:{name}"); continue
        path=root/item["path"]
        if not path.exists(): errors.append(f"missing_file:{name}"); continue
        if sha256_file(path)!=item.get("sha256"): errors.append(f"hash_mismatch:{name}")
        if path.suffix==".csv" and _csv_count(path)<minimum: errors.append(f"row_count:{name}")
    checks=summary.get("checks",{})
    if any(value!="passed" for value in checks.values()): errors.append("summary_check_failed")
    if summary.get("blocked_reasons"): errors.append("blocked_reasons_present")
    if result_package_path is not None:
        package=_load(result_package_path,errors,"result_package")
        if package.get("task_id")!="R1-T04": errors.append("result_package_task_mismatch")
        if package.get("run_id")!=summary.get("run_id"): errors.append("result_package_run_mismatch")
        if package.get("code_commit")!=summary.get("code_commit"): errors.append("result_package_commit_mismatch")
    result={"task_id":"R1-T04","run_id":summary.get("run_id"),"code_commit":summary.get("code_commit"),"validator_status":"passed" if not errors else "failed","summary_path":_rel(summary_path,root),"summary_sha256":sha256_file(summary_path) if summary_path.exists() else None,"result_package_path":_rel(result_package_path,root) if result_package_path else None,"errors":errors}
    if output_path:
        output_path.parent.mkdir(parents=True,exist_ok=True); output_path.write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    if errors: raise R1T04ValidationError(json.dumps(result,ensure_ascii=False))
    return result


def sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _load(path: Path, errors: list[str], name: str) -> dict[str, Any]:
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc: errors.append(f"{name}_load:{exc}"); return {}


def _csv_count(path: Path) -> int:
    return max(0,len(path.read_text(encoding="utf-8").splitlines())-1)


def _rel(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\","/")

"""Inventory, copy, verify, and retire one external local-data root.

This operator tool is intentionally fail-closed. It never overwrites different
content and only deletes a source after a complete copy verification receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

MIGRATION_ID = "RETIRE-CONVERGENCE-RESEARCH-INPUTS-20260720"
RETIRED_ROOT_NAME = "convergence-research-inputs"
HANDOFF_RELATIVE = PurePosixPath(
    "data/generated/r2a/r2a_t04/R2A-T04-20260720T002158508Z/"
    "r2a_t04_accepted_result_handoff.json"
)
DONE_RELATIVE = PurePosixPath(
    "data/generated/r2a/r2a_t04/R2A-T04-20260720T002158508Z/DONE"
)
HANDOFF_SHA256 = "ec4aa13d8b428adb03e6f7faff591741f2730c50cdc87d98f33c9e6ef9e20c5a"
DONE_SHA256 = "e41441b415cd20bd50dc659df8dacb1cdf0c0056463f8780fe361e2aeb944808"


class MigrationError(RuntimeError):
    """A fail-closed migration error."""


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _is_reparse(path: Path) -> bool:
    info = path.lstat()
    file_attributes = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return path.is_symlink() or bool(file_attributes & reparse_flag)


def _assert_exact_source(source_root: Path) -> Path:
    source = source_root.absolute()
    if source.name.casefold() != RETIRED_ROOT_NAME.casefold():
        raise MigrationError(f"unexpected source root name: {source.name}")
    if source.parent == source or len(source.parts) < 3:
        raise MigrationError("refusing broad source root")
    if not source.is_dir():
        raise MigrationError("source root is absent or not a directory")
    if _is_reparse(source):
        raise MigrationError("source root is a reparse point")
    return source


def _assert_within(path: Path, root: Path) -> None:
    try:
        path.absolute().relative_to(root.absolute())
    except ValueError as exc:
        raise MigrationError(f"path escapes root: {path}") from exc


def _map_relative(source_relative: PurePosixPath) -> tuple[str, PurePosixPath]:
    if source_relative.parts and source_relative.parts[0].casefold() == "r2a_t04":
        suffix = PurePosixPath(*source_relative.parts[1:])
        return "r2a_t04", PurePosixPath("data/generated/r2a/r2a_t04") / suffix
    return (
        "legacy_external_archive",
        PurePosixPath("data/generated/_legacy_external_archive") / source_relative,
    )


def _walk_source(source_root: Path) -> tuple[list[Path], list[Path]]:
    files: list[Path] = []
    directories: list[Path] = []
    pending = [source_root]
    while pending:
        current = pending.pop()
        try:
            children = sorted(
                os.scandir(current), key=lambda item: item.name.casefold()
            )
        except OSError as exc:
            raise MigrationError(f"unreadable directory: {current}") from exc
        for child in children:
            path = Path(child.path)
            try:
                if _is_reparse(path):
                    raise MigrationError(f"reparse point forbidden: {path}")
                if child.is_dir(follow_symlinks=False):
                    directories.append(path)
                    pending.append(path)
                elif child.is_file(follow_symlinks=False):
                    with path.open("rb"):
                        pass
                    files.append(path)
                else:
                    raise MigrationError(f"unsupported filesystem entry: {path}")
            except OSError as exc:
                raise MigrationError(f"unreadable entry: {path}") from exc
    return sorted(files), sorted(directories)


def _tracked_paths(repo_root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    return {
        item.decode("utf-8").replace("\\", "/")
        for item in result.stdout.split(b"\0")
        if item
    }


def build_inventory(source_root: Path, repo_root: Path) -> dict[str, Any]:
    source = _assert_exact_source(source_root)
    repo = repo_root.resolve(strict=True)
    files, directories = _walk_source(source)
    tracked = _tracked_paths(repo)
    entries: list[dict[str, Any]] = []
    targets_seen: set[str] = set()
    for source_path in files:
        source_relative = PurePosixPath(source_path.relative_to(source).as_posix())
        mapping_class, target_relative = _map_relative(source_relative)
        target_key = target_relative.as_posix().casefold()
        if target_key in targets_seen:
            raise MigrationError(
                f"case-insensitive target collision: {target_relative}"
            )
        targets_seen.add(target_key)
        target = repo / Path(*target_relative.parts)
        _assert_within(target, repo)
        source_hash = _sha256(source_path)
        status = "pending_copy"
        if target.exists():
            if not target.is_file() or _is_reparse(target):
                raise MigrationError(
                    f"target is not an ordinary file: {target_relative}"
                )
            if (
                target.stat().st_size != source_path.stat().st_size
                or _sha256(target) != source_hash
            ):
                raise MigrationError(
                    f"different target content exists: {target_relative}"
                )
            status = "already_present_identical"
        if (
            target_relative.as_posix() in tracked
            and status != "already_present_identical"
        ):
            raise MigrationError(
                f"tracked target cannot be overwritten: {target_relative}"
            )
        entries.append(
            {
                "source_relative_path": source_relative.as_posix(),
                "target_relative_path": target_relative.as_posix(),
                "mapping_class": mapping_class,
                "byte_size": source_path.stat().st_size,
                "sha256": source_hash,
                "copy_disposition": status,
            }
        )
    directory_entries: list[dict[str, str]] = []
    for directory in directories:
        relative = PurePosixPath(directory.relative_to(source).as_posix())
        mapping_class, target_relative = _map_relative(relative)
        directory_entries.append(
            {
                "source_relative_path": relative.as_posix(),
                "target_relative_path": target_relative.as_posix(),
                "mapping_class": mapping_class,
            }
        )
    entry_identity = [
        {
            key: entry[key]
            for key in (
                "source_relative_path",
                "target_relative_path",
                "mapping_class",
                "byte_size",
                "sha256",
            )
        }
        for entry in entries
    ]
    return {
        "receipt_version": 1,
        "migration_id": MIGRATION_ID,
        "created_at": _now(),
        "source_root_name": source.name,
        "source_root_is_reparse_point": False,
        "file_entries": entries,
        "directory_entries": directory_entries,
        "summary": {
            "file_count": len(entries),
            "directory_count": len(directory_entries),
            "total_bytes": sum(entry["byte_size"] for entry in entries),
            "inventory_fingerprint": _canonical_fingerprint(entry_identity),
            "directory_fingerprint": _canonical_fingerprint(directory_entries),
        },
        "status": "passed",
    }


def _verify_inventory_files(
    inventory: dict[str, Any], source: Path | None, repo: Path
) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    for entry in inventory["file_entries"]:
        target = repo / Path(*PurePosixPath(entry["target_relative_path"]).parts)
        _assert_within(target, repo)
        for side, path in (
            ("source", source / entry["source_relative_path"] if source else None),
            ("target", target),
        ):
            if path is None:
                continue
            if not path.is_file() or _is_reparse(path):
                mismatches.append(
                    {
                        "path": entry["target_relative_path"],
                        "side": side,
                        "reason": "missing_or_nonordinary",
                    }
                )
                continue
            actual_size = path.stat().st_size
            actual_hash = _sha256(path)
            if actual_size != entry["byte_size"] or actual_hash != entry["sha256"]:
                mismatches.append(
                    {
                        "path": entry["target_relative_path"],
                        "side": side,
                        "reason": "identity_mismatch",
                        "expected_byte_size": entry["byte_size"],
                        "actual_byte_size": actual_size,
                        "expected_sha256": entry["sha256"],
                        "actual_sha256": actual_hash,
                    }
                )
    return mismatches


def reconcile_locators(repo_root: Path) -> dict[str, Any]:
    handoff_path = repo_root / Path(*HANDOFF_RELATIVE.parts)
    if _sha256(handoff_path) != HANDOFF_SHA256:
        raise MigrationError("accepted handoff identity changed")
    handoff = _load_json(handoff_path)
    results: list[dict[str, Any]] = []
    t04_root = repo_root / "data/generated/r2a/r2a_t04"
    for name, identity in sorted(handoff["evidence_identities"].items()):
        locator = PurePosixPath(identity["relative_locator"])
        if identity.get("storage_class") == "repository_artifact":
            candidate = repo_root / Path(*locator.parts)
        else:
            candidate = t04_root / Path(*locator.parts)
        _assert_within(candidate, repo_root)
        actual_size = candidate.stat().st_size if candidate.is_file() else None
        actual_hash = _sha256(candidate) if candidate.is_file() else None
        passed = (
            actual_size == identity["byte_size"] and actual_hash == identity["sha256"]
        )
        results.append(
            {
                "identity_name": name,
                "relative_locator": locator.as_posix(),
                "resolved_repository_relative_path": candidate.relative_to(
                    repo_root
                ).as_posix(),
                "expected_byte_size": identity["byte_size"],
                "actual_byte_size": actual_size,
                "expected_sha256": identity["sha256"],
                "actual_sha256": actual_hash,
                "status": "passed" if passed else "failed",
            }
        )
    mismatch_count = sum(item["status"] != "passed" for item in results)
    return {
        "receipt_version": 1,
        "migration_id": MIGRATION_ID,
        "checked_at": _now(),
        "handoff_relative_path": HANDOFF_RELATIVE.as_posix(),
        "handoff_sha256": HANDOFF_SHA256,
        "locator_count": len(results),
        "mismatch_count": mismatch_count,
        "locators": results,
        "status": "passed" if mismatch_count == 0 else "failed",
    }


def copy_and_verify(
    source_root: Path, repo_root: Path, receipt_dir: Path
) -> dict[str, Any]:
    source = _assert_exact_source(source_root)
    repo = repo_root.resolve(strict=True)
    inventory_path = receipt_dir / "inventory_manifest.json"
    inventory = _load_json(inventory_path)
    fresh_inventory = build_inventory(source, repo)
    if (
        fresh_inventory["summary"]["inventory_fingerprint"]
        != inventory["summary"]["inventory_fingerprint"]
    ):
        raise MigrationError("source inventory changed after inventory receipt")
    copied_count = 0
    identical_count = 0
    for entry in inventory["file_entries"]:
        source_path = source / entry["source_relative_path"]
        target = repo / Path(*PurePosixPath(entry["target_relative_path"]).parts)
        _assert_within(target, repo)
        if target.exists():
            if (
                target.stat().st_size != entry["byte_size"]
                or _sha256(target) != entry["sha256"]
            ):
                raise MigrationError(
                    f"target conflict during copy: {entry['target_relative_path']}"
                )
            identical_count += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target)
        copied_count += 1
    for entry in inventory["directory_entries"]:
        target = repo / Path(*PurePosixPath(entry["target_relative_path"]).parts)
        _assert_within(target, repo)
        target.mkdir(parents=True, exist_ok=True)
    mismatches = _verify_inventory_files(inventory, source, repo)
    locator_receipt = reconcile_locators(repo)
    _write_json(receipt_dir / "locator_reconciliation.json", locator_receipt)
    passed = not mismatches and locator_receipt["status"] == "passed"
    receipt = {
        "receipt_version": 1,
        "migration_id": MIGRATION_ID,
        "verified_at": _now(),
        "inventory_fingerprint": inventory["summary"]["inventory_fingerprint"],
        "source_file_count": inventory["summary"]["file_count"],
        "target_verified_file_count": inventory["summary"]["file_count"]
        - len(mismatches),
        "total_bytes": inventory["summary"]["total_bytes"],
        "copied_count": copied_count,
        "already_present_identical_count": identical_count,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:1000],
        "locator_reconciliation_status": locator_receipt["status"],
        "source_deleted": False,
        "status": "passed" if passed else "failed",
    }
    _write_json(receipt_dir / "copy_verification_receipt.json", receipt)
    if not passed:
        raise MigrationError("copy or locator verification failed")
    return receipt


def delete_source(
    source_root: Path, repo_root: Path, receipt_dir: Path
) -> dict[str, Any]:
    source = _assert_exact_source(source_root)
    repo = repo_root.resolve(strict=True)
    inventory = _load_json(receipt_dir / "inventory_manifest.json")
    copy_receipt = _load_json(receipt_dir / "copy_verification_receipt.json")
    locator_receipt = _load_json(receipt_dir / "locator_reconciliation.json")
    if (
        copy_receipt.get("status") != "passed"
        or locator_receipt.get("status") != "passed"
    ):
        raise MigrationError("passed copy and locator receipts are required")
    if (
        copy_receipt.get("inventory_fingerprint")
        != inventory["summary"]["inventory_fingerprint"]
    ):
        raise MigrationError("copy receipt does not bind current inventory")
    mismatches = _verify_inventory_files(inventory, source, repo)
    if mismatches:
        raise MigrationError(f"pre-delete identity mismatch count: {len(mismatches)}")
    if _sha256(repo / Path(*HANDOFF_RELATIVE.parts)) != HANDOFF_SHA256:
        raise MigrationError("handoff changed before delete")
    if _sha256(repo / Path(*DONE_RELATIVE.parts)) != DONE_SHA256:
        raise MigrationError("DONE changed before delete")
    shutil.rmtree(source)
    if source.exists():
        raise MigrationError("source root remains after deletion")
    post_mismatches = _verify_inventory_files(inventory, None, repo)
    post_locators = reconcile_locators(repo)
    handoff_hash = _sha256(repo / Path(*HANDOFF_RELATIVE.parts))
    done_hash = _sha256(repo / Path(*DONE_RELATIVE.parts))
    passed = (
        not post_mismatches
        and post_locators["status"] == "passed"
        and handoff_hash == HANDOFF_SHA256
        and done_hash == DONE_SHA256
        and not source.exists()
    )
    receipt = {
        "receipt_version": 1,
        "migration_id": MIGRATION_ID,
        "verified_at": _now(),
        "inventory_fingerprint": inventory["summary"]["inventory_fingerprint"],
        "target_file_count": inventory["summary"]["file_count"],
        "target_total_bytes": inventory["summary"]["total_bytes"],
        "target_mismatch_count": len(post_mismatches),
        "locator_reconciliation_status": post_locators["status"],
        "handoff_sha256": handoff_hash,
        "done_sha256": done_hash,
        "source_root_name": RETIRED_ROOT_NAME,
        "source_deleted": True,
        "source_absent": not source.exists(),
        "backup_created": False,
        "compatibility_link_created": False,
        "status": "passed" if passed else "failed",
    }
    _write_json(receipt_dir / "post_delete_verification.json", receipt)
    if not passed:
        raise MigrationError("post-delete verification failed")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument(
        "--repo-root", default=Path(__file__).resolve().parents[2], type=Path
    )
    parser.add_argument("--receipt-dir", required=True, type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("inventory")
    subparsers.add_parser("copy-and-verify")
    subparsers.add_parser("delete-source")
    args = parser.parse_args(argv)
    receipt_dir = args.receipt_dir.absolute()
    try:
        if args.command == "inventory":
            inventory = build_inventory(args.source_root, args.repo_root)
            _write_json(receipt_dir / "inventory_manifest.json", inventory)
            print(json.dumps(inventory["summary"], sort_keys=True))
        elif args.command == "copy-and-verify":
            receipt = copy_and_verify(args.source_root, args.repo_root, receipt_dir)
            print(json.dumps(receipt, sort_keys=True))
        else:
            receipt = delete_source(args.source_root, args.repo_root, receipt_dir)
            print(json.dumps(receipt, sort_keys=True))
    except (MigrationError, OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"migration_status=failed reason={exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

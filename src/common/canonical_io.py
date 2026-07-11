from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TEXT_EXTENSIONS = {".json", ".csv", ".md", ".py", ".toml", ".yml", ".yaml", ".txt"}


class TextContractError(RuntimeError):
    pass


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_json_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def write_markdown(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"
    path.write_bytes(normalized.encode("utf-8"))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                    if isinstance(value, list | dict)
                    else value
                    for key, value in row.items()
                }
            )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def validate_text_bytes(payload: bytes) -> list[str]:
    errors: list[str] = []
    if payload.startswith(b"\xef\xbb\xbf"):
        errors.append("formal_source_bom")
    if b"\r\n" in payload:
        errors.append("formal_source_crlf")
    without_crlf = payload.replace(b"\r\n", b"")
    if b"\r" in without_crlf:
        errors.append("formal_source_bare_cr")
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError:
        errors.append("formal_source_utf8")
    if not payload.endswith(b"\n"):
        errors.append("formal_source_terminal_newline")
    elif payload.endswith(b"\n\n"):
        errors.append("formal_source_terminal_newline")
    return errors


def validate_text_file(path: Path) -> list[str]:
    return validate_text_bytes(path.read_bytes())


def repo_rel(path: Path, root: Path = ROOT) -> str:
    return path.resolve().relative_to(root).as_posix()


def git_output(args: list[str], *, root: Path = ROOT) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def current_commit(root: Path = ROOT) -> str:
    return git_output(["rev-parse", "HEAD"], root=root)


def git_blob_bytes(commit: str, path: str, *, root: Path = ROOT) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return result.stdout


def git_blob_sha(commit: str, path: str, *, root: Path = ROOT) -> str:
    return git_output(["rev-parse", f"{commit}:{path}"], root=root)


def path_has_staged_change(path: str, *, root: Path = ROOT) -> bool:
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", path],
        cwd=root,
    )
    return result.returncode != 0


def path_has_unstaged_change(path: str, *, root: Path = ROOT) -> bool:
    result = subprocess.run(["git", "diff", "--quiet", "--", path], cwd=root)
    return result.returncode != 0


def formal_source_binding(
    path: Path, commit: str, *, root: Path = ROOT
) -> dict[str, Any]:
    rel = repo_rel(path, root)
    if not path.exists():
        raise TextContractError(f"formal_source_blob_missing:{rel}")
    if path_has_staged_change(rel, root=root):
        raise TextContractError(f"formal_source_staged_change:{rel}")
    if path_has_unstaged_change(rel, root=root):
        raise TextContractError(f"formal_source_dirty:{rel}")

    blob = git_blob_bytes(commit, rel, root=root)
    worktree = path.read_bytes()
    blob_errors = validate_text_bytes(blob)
    worktree_errors = validate_text_bytes(worktree)
    if blob_errors:
        raise TextContractError(f"{blob_errors[0]}:{rel}")
    if worktree_errors:
        raise TextContractError(f"{worktree_errors[0]}:{rel}")

    normalized_blob = blob.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    normalized_worktree = (
        worktree.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    )
    if normalized_blob != normalized_worktree:
        raise TextContractError(f"worktree_committed_content_mismatch:{rel}")

    return {
        "path": rel,
        "source_commit": commit,
        "git_blob_sha": git_blob_sha(commit, rel, root=root),
        "committed_byte_sha256": sha256_bytes(blob),
        "normalized_text_sha256": sha256_bytes(normalized_blob.encode("utf-8")),
        "encoding": "utf-8",
        "line_ending": "lf",
        "bom": False,
        "terminal_lf_count": 1,
    }


def json_source_binding(
    path: Path, commit: str, *, root: Path = ROOT
) -> dict[str, Any]:
    binding = formal_source_binding(path, commit, root=root)
    parsed = json.loads(git_blob_bytes(commit, binding["path"], root=root))
    binding["canonical_json_sha256"] = canonical_json_sha256(parsed)
    return binding


def worktree_hash_for_formal_lineage_forbidden(path: Path) -> str:
    raise TextContractError(f"hash_source_is_worktree_forbidden:{path.as_posix()}")

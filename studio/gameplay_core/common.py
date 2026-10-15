"""Shared validators and read-only, sandboxed file enumeration."""
from __future__ import annotations
import hashlib
from contextlib import contextmanager
import os
from pathlib import Path
import re

ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
MAX_FILE_BYTES = 64*1024*1024
VALID_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})

def identifier(value: object, name: str = "ID") -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError(f"{name} 无效")
    return value

def strict_integer(value: object, minimum: int, maximum: int, label: str = "整数") -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} 应为 {minimum}~{maximum} 的整数")
    return value

def bounded_text(value: object, *, limit: int = 250, label: str = "文字") -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{label} 不合法或过长")
    return value.strip()

def require_keys(value: object, allowed: set[str], required: set[str] | None = None,
                 label: str = "对象") -> dict:
    if not isinstance(value,dict) or set(value)-allowed or (required or set())-set(value):
        raise ValueError(f"{label} 字段不合法")
    return value

def checked_file(root: str | Path, candidate: str | Path, *, allowed_extensions=None,
                 max_bytes: int = MAX_FILE_BYTES) -> Path:
    """Resolve a file inside a root; block symlinks anywhere in its relative path."""
    root = Path(root).resolve(strict=True)
    candidate = Path(candidate)
    if candidate.is_absolute():
        raise ValueError("禁止使用素材绝对路径")
    if any(part in (".", "..") for part in candidate.parts):
        raise ValueError("素材路径不得包含 . 或 ..")
    raw = root / candidate
    relative = raw.relative_to(root)
    probe = root
    for part in relative.parts:
        probe = probe / part
        if probe.is_symlink():
            raise ValueError("素材目录中不允许经过符号链接")
    resolved = raw.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError("素材路径越出指定根目录")
    if not resolved.is_file():
        raise ValueError("目标不是素材文件")
    if allowed_extensions and resolved.suffix.casefold() not in allowed_extensions:
        raise ValueError("不支持的素材类型")
    size = resolved.stat().st_size
    if size <= 0 or size > max_bytes:
        raise ValueError("素材尺寸不在允许范围")
    return resolved

def fingerprint_file(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024*1024),b""):
            digest.update(chunk)
    return digest.hexdigest()

def safe_candidates(root: str | Path, extensions: set[str] | frozenset[str],
                    *, max_files: int = 100_000, forbidden_folders=(),
                    on_skip=None):
    """Yield trusted candidates; optionally report invalid target files.

    The on_skip handler receives a *relative* path and a short reason. Non-
    matching extensions are ignored, not counted as invalid media. Directory
    symlinks are never followed.
    """
    base=Path(root).resolve(strict=True)
    if not base.is_dir():raise ValueError("素材根目录不是文件夹")
    excluded={x.casefold() for x in forbidden_folders}
    scanned=0
    for parent, directories, filenames in os.walk(base,followlinks=False):
        here=Path(parent)
        directories[:]=sorted(d for d in directories if d.casefold() not in excluded
            and not (here/d).is_symlink())
        for filename in sorted(filenames):
            scanned+=1
            if scanned>max_files:
                raise ValueError("扫描文件数量超限，未生成不完整索引")
            path=here/filename
            relative=path.relative_to(base)
            if path.suffix.casefold() not in extensions:
                continue
            if path.is_symlink():
                if on_skip:
                    on_skip({"relative_path":relative.as_posix(),
                             "reason":"symlink_not_followed"})
                continue
            try:
                checked=checked_file(base,relative,allowed_extensions=extensions)
            except (ValueError,OSError,FileNotFoundError) as err:
                if on_skip:
                    on_skip({"relative_path":relative.as_posix(),
                             "reason":"file_rejected",
                             "message":str(err)[:120]})
                continue
            yield relative.as_posix(),checked

def stable_asset_id(prefix: str, relative: str, file_hash: str) -> str:
    key=hashlib.sha256((relative.casefold()+"\n"+file_hash).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{key}"


@contextmanager
def open_verified_asset(root: str | Path, record: dict, *,
                        allowed_extensions: frozenset[str] | set[str] | None = None):
    """Open the PINNED local media using a single validated file descriptor.

    Use this in the actual preview/media HTTP route, not ``root / request.path``.
    The registry owns ``relative_path`` and SHA256; the HTTP client only
    supplies the asset_id, which Codex must resolve server-side.

    This deliberately re-hashes the descriptor before yielding it, and seeks
    back to the beginning. UI callers can cache trusted results if profiling
    proves hashing expensive, but may never drop the directory confinement.
    """
    if not isinstance(record, dict):
        raise ValueError("素材记录不是对象")
    required = {"asset_id", "relative_path", "file_hash", "verified"}
    if required - set(record):
        raise ValueError("素材审核记录缺少必要字段")
    identifier(record["asset_id"], "素材 ID")
    sha = record["file_hash"]
    if (not isinstance(sha, str) or len(sha) != 64
            or any(ch not in "0123456789abcdef" for ch in sha)):
        raise ValueError("素材 SHA256 无效")
    verified=record["verified"]
    # SQLite INTEGER columns represent TRUE as the integer 1. Accept only
    # bool(True) or strict int(1), not strings, floats or other truthy input.
    if not (verified is True or (type(verified) is int and verified==1)):
        raise ValueError("未审核素材不得从正式媒体端点打开")
    path = checked_file(root, record["relative_path"],
                        allowed_extensions=allowed_extensions)
    # Resolve and open exactly the validated path: symlinks from user data
    # are already refused by checked_file(), including intermediate folders.
    with path.open("rb") as handle:
        digest = hashlib.sha256()
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
        if digest.hexdigest() != sha:
            raise ValueError("素材已经修改，审核许可自动失效")
        handle.seek(0)
        yield handle

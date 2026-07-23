"""Raw MinerU artifact helpers: zip integrity, zip-slip, immutability.

P3-T05:
- Verify zip is openable and structurally sound (testzip)
- Reject zip-slip / absolute / drive-letter member paths by default
- Record sha256 and expected entry presence for raw artifacts
- Refuse clean (or any overwrite) of protected raw paths
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

# Files we expect in a successful MinerU full-zip unpack (at least one of each group).
EXPECTED_MARKDOWN_NAMES = ("full.md",)
EXPECTED_CONTENT_LIST_SUFFIXES = ("_content_list.json", "content_list.json")

# Directory name segments that mark immutable raw trees.
RAW_DIR_MARKERS = frozenset({"raw", "unzipped"})
PROTECTED_RAW_BASENAMES = frozenset(
    {
        "result.zip",
        "full.md",
        "raw_manifest.json",
    }
)


class RawError(ValueError):
    """Raised when raw zip integrity, path safety, or immutability is violated."""


def is_safe_zip_member(name: str) -> bool:
    """Reject absolute paths and parent-directory traversal in zip entries."""
    if not name or "\x00" in name:
        return False
    if name.startswith("/") or name.startswith(chr(92)):
        return False
    # Windows drive-style absolute paths
    if len(name) >= 2 and name[1] == ":":
        return False
    normalized = name.replace(chr(92), "/")
    if normalized.startswith("/"):
        return False
    parts = Path(normalized).parts
    if any(part == ".." for part in parts):
        return False
    return True


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def file_fingerprint(path: Path) -> dict[str, Any]:
    """Stable identity for immutability checks (hash + size + mtime_ns)."""
    if not path.is_file():
        raise RawError(f"not a file: {path}")
    st = path.stat()
    return {
        "path": path.name,
        "size_bytes": st.st_size,
        "mtime_ns": st.st_mtime_ns,
        "sha256": sha256_file(path),
    }


def is_under_raw_tree(path: Path) -> bool:
    """True if the path is under a `raw/` directory segment (immutable tree)."""
    parts = [p.lower() for p in Path(path).parts]
    return "raw" in parts


def assert_not_raw_write_target(path: Path) -> None:
    """Refuse writes that would clobber protected raw artifacts."""
    resolved = path.expanduser()
    # Prefer resolve, but path need not exist yet.
    try:
        resolved = resolved.resolve(strict=False)
    except OSError:
        resolved = path.expanduser().absolute()

    parts_l = [p.lower() for p in resolved.parts]
    if "raw" in parts_l:
        raise RawError(
            f"refusing to write into raw/immutable tree: {resolved.name} "
            f"(path contains a 'raw' segment)"
        )
    if resolved.name in PROTECTED_RAW_BASENAMES and "raw" in parts_l:
        raise RawError(f"refusing to overwrite protected raw basename: {resolved.name}")


def verify_zip_integrity(zip_path: Path) -> dict[str, Any]:
    """Open zip, run testzip, list members; raise RawError on corruption/unsafe names."""
    if not zip_path.is_file():
        raise RawError(f"zip not found: {zip_path}")
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            bad = zf.testzip()
            if bad is not None:
                raise RawError(f"corrupt zip member: {bad!r}")
            members = zf.namelist()
            infos = zf.infolist()
    except zipfile.BadZipFile as exc:
        raise RawError(f"not a valid zip: {zip_path.name}: {exc}") from exc

    unsafe = [m for m in members if not is_safe_zip_member(m)]
    if unsafe:
        raise RawError(f"unsafe zip member path(s): {unsafe[:5]!r}")

    return {
        "zip_path": zip_path.name,
        "member_count": len(members),
        "members": members[:200],
        "total_uncompressed": sum(i.file_size for i in infos),
        "sha256": sha256_file(zip_path),
        "size_bytes": zip_path.stat().st_size,
    }


def expected_entries_present(member_names: list[str]) -> dict[str, Any]:
    """Check for markdown + content_list style entries (best-effort for MinerU)."""
    basenames = [Path(n.replace("\\", "/")).name for n in member_names]
    has_md = any(b == "full.md" or b.endswith(".md") for b in basenames)
    has_content_list = any(
        b.endswith("_content_list.json") or b == "content_list.json" or "content_list" in b
        for b in basenames
    )
    return {
        "has_markdown": has_md,
        "has_content_list": has_content_list,
        "ok": has_md,  # markdown is the hard requirement; content_list preferred
    }


def unpack_zip(
    zip_path: Path,
    dest: Path,
    *,
    enforce_safe_members: bool = True,
    verify_integrity: bool = True,
) -> list[str]:
    """Extract zip to dest with zip-slip protection (default on for P3-T05)."""
    if verify_integrity:
        meta = verify_zip_integrity(zip_path)
        names_preview = list(meta["members"])
        if enforce_safe_members and any(not is_safe_zip_member(n) for n in names_preview):
            raise RawError("unsafe members after integrity check")
    else:
        if not zip_path.is_file():
            raise RawError(f"zip not found: {zip_path}")

    dest.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            if enforce_safe_members and not is_safe_zip_member(info.filename):
                raise RawError(f"unsafe zip member path: {info.filename!r}")
            # Extract member-by-member to a resolved path under dest (extra slip guard).
            target = (dest / info.filename).resolve()
            if not str(target).startswith(str(dest.resolve())):
                raise RawError(f"zip-slip blocked: {info.filename!r}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info, "r") as src, target.open("wb") as out:
                    out.write(src.read())
            names.append(info.filename)
    return names


def materialize_raw_from_zip(
    zip_path: Path,
    raw_dir: Path,
    *,
    expected_sha256: str | None = None,
    require_markdown: bool = True,
    copy_zip: bool = True,
) -> dict[str, Any]:
    """Validate zip, optionally copy as result.zip, unpack to raw_dir/unzipped, write manifest.

    Idempotent: if raw_manifest.json exists with matching zip sha256, skip rewrite.
    """
    integrity = verify_zip_integrity(zip_path)
    zip_hash = integrity["sha256"]
    if expected_sha256 and expected_sha256 != zip_hash:
        raise RawError(f"zip sha256 mismatch: expected {expected_sha256}, got {zip_hash}")

    entry_check = expected_entries_present(list(integrity["members"]))
    if require_markdown and not entry_check["has_markdown"]:
        raise RawError("zip missing expected markdown entry (full.md or *.md)")

    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = raw_dir / "raw_manifest.json"
    dest_zip = raw_dir / "result.zip"
    unzipped = raw_dir / "unzipped"

    if manifest_path.is_file() and dest_zip.is_file():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            isinstance(existing, dict)
            and existing.get("zip_sha256") == zip_hash
            and (unzipped.is_dir() or not existing.get("unpacked"))
        ):
            return existing

    if copy_zip:
        if not dest_zip.is_file() or sha256_file(dest_zip) != zip_hash:
            # Never truncate existing different content in place without rename:
            # write temp then replace only when hashes differ and no protected lock.
            tmp = raw_dir / "result.zip.partial"
            tmp.write_bytes(zip_path.read_bytes())
            if sha256_file(tmp) != zip_hash:
                tmp.unlink(missing_ok=True)
                raise RawError("failed to copy zip with matching hash")
            tmp.replace(dest_zip)
        integrity = verify_zip_integrity(dest_zip)

    names = unpack_zip(dest_zip if dest_zip.is_file() else zip_path, unzipped)
    entry_check = expected_entries_present(names)

    # Hash key raw outputs (not entire tree for cost reasons).
    output_hashes: dict[str, str] = {"result.zip": zip_hash}
    for rel in ("unzipped/full.md",):
        p = raw_dir / rel
        if p.is_file():
            output_hashes[rel] = sha256_file(p)
    # First markdown if full.md missing
    if "unzipped/full.md" not in output_hashes:
        mds = sorted(unzipped.rglob("*.md"))
        if mds:
            rel = mds[0].relative_to(raw_dir).as_posix()
            output_hashes[rel] = sha256_file(mds[0])

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "zip_sha256": zip_hash,
        "zip_size_bytes": integrity["size_bytes"],
        "member_count": len(names),
        "members_sample": names[:100],
        "entry_check": entry_check,
        "unpacked": True,
        "output_hashes": output_hashes,
        "immutable": True,
    }
    # Atomic-ish write of manifest (new file or replace).
    tmp_manifest = raw_dir / "raw_manifest.json.partial"
    tmp_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    tmp_manifest.replace(manifest_path)
    return manifest


def summarize_result_dir(result_dir: Path) -> dict[str, Any]:
    files = sorted(
        p.relative_to(result_dir).as_posix() for p in result_dir.rglob("*") if p.is_file()
    )
    md_files = list(result_dir.rglob("*.md"))
    content_lists = list(result_dir.rglob("*content_list.json"))
    summary: dict[str, Any] = {
        "file_count": len(files),
        "files": files[:100],
        "markdown_chars": 0,
        "markdown_preview": "",
        "content_list_items": 0,
        "page_indexes_seen": [],
        "types_count": {},
    }
    if md_files:
        md = md_files[0].read_text(encoding="utf-8", errors="replace")
        summary["markdown_chars"] = len(md)
        summary["markdown_preview"] = md[:1200]
        summary["markdown_path"] = str(md_files[0].relative_to(result_dir))
        summary["markdown_sha256"] = sha256_file(md_files[0])
    if content_lists:
        raw = json.loads(content_lists[0].read_text(encoding="utf-8", errors="replace"))
        items = (
            raw if isinstance(raw, list) else raw.get("pdf_info") or raw.get("content_list") or []
        )
        if isinstance(items, list):
            summary["content_list_items"] = len(items)
            pages: set[Any] = set()
            types: dict[str, int] = {}
            for it in items:
                if not isinstance(it, dict):
                    continue
                t = str(it.get("type") or it.get("category") or "unknown")
                types[t] = types.get(t, 0) + 1
                for k in ("page_idx", "page_no", "page", "page_index"):
                    if k in it and it[k] is not None:
                        pages.add(it[k])
            summary["types_count"] = dict(sorted(types.items(), key=lambda x: (-x[1], x[0])))
            summary["page_indexes_seen"] = sorted(pages)[:50]
            summary["content_list_path"] = str(content_lists[0].relative_to(result_dir))
    return summary


__all__ = [
    "EXPECTED_MARKDOWN_NAMES",
    "PROTECTED_RAW_BASENAMES",
    "RAW_DIR_MARKERS",
    "RawError",
    "assert_not_raw_write_target",
    "expected_entries_present",
    "file_fingerprint",
    "is_safe_zip_member",
    "is_under_raw_tree",
    "materialize_raw_from_zip",
    "sha256_bytes",
    "sha256_file",
    "summarize_result_dir",
    "unpack_zip",
    "verify_zip_integrity",
]

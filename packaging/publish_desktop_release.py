"""把各系统产物收成一份 GitHub Release 目录。

arm64 和 x64 各自生成 latest-mac.yml。这里合并 files，避免后一个盖掉前一个。
deb 和未签名的 macOS 不走静默安装，它们读同目录下的 desktop-release.json。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

CHANNEL_FILES = ("latest.yml", "latest-mac.yml", "latest-linux.yml")
SKIP_NAMES = {"builder-debug.yml"}
TAG_PREFIX = "desktop-v"


def merge_update_info(documents: list[dict], notes: str = "") -> dict:
    """合并同一通道的更新描述。files 按 url 去重，path 优先指向 zip。"""
    merged: dict | None = None
    files: list[dict] = []
    seen: set[str] = set()
    for document in documents:
        if not isinstance(document, dict):
            continue
        if merged is None:
            merged = dict(document)
        for item in document.get("files") or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "")
            if not url or url in seen:
                continue
            seen.add(url)
            files.append(dict(item))
    result = dict(merged or {})
    result["files"] = files
    chosen = next((item for item in files if str(item.get("url", "")).endswith(".zip")), None)
    if chosen is None and files:
        chosen = files[0]
    if chosen is not None:
        result["path"] = chosen.get("url")
        if chosen.get("sha512"):
            result["sha512"] = chosen["sha512"]
    if notes:
        result["releaseNotes"] = notes
    return result


def release_manifest(version: str, tag: str, notes: str, names: list[str], digests: dict[str, str] | None = None) -> dict:
    digests = digests or {}
    files = []
    for name in names:
        lower = name.lower()
        if not lower.endswith((".appimage", ".deb", ".exe", ".dmg", ".zip")):
            continue
        item = {"name": name, "url": name}
        digest = digests.get(name)
        if digest:
            item["sha256"] = digest
        files.append(item)
    return {"version": version, "tag": tag, "notes": notes, "files": files}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_files(artifacts: Path) -> list[Path]:
    found = []
    for path in sorted(artifacts.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if path.name in SKIP_NAMES:
            continue
        lower = path.name.lower()
        if path.name in CHANNEL_FILES or lower.endswith(".blockmap") or lower.endswith((".appimage", ".deb", ".exe", ".dmg", ".zip")):
            found.append(path)
    return found


def assemble(artifacts: Path, out: Path, tag: str, notes: str) -> dict:
    import yaml

    grouped: dict[str, list[Path]] = {name: [] for name in CHANNEL_FILES}
    installers: dict[str, Path] = {}
    blockmaps: dict[str, Path] = {}
    for path in collect_files(artifacts):
        if path.name in CHANNEL_FILES:
            grouped[path.name].append(path)
            continue
        bucket = blockmaps if path.name.lower().endswith(".blockmap") else installers
        previous = bucket.get(path.name)
        if previous is not None and _sha256(previous) != _sha256(path):
            raise SystemExit(f"同名文件内容不同: {path.name}")
        bucket[path.name] = path
    missing = [name for name, paths in grouped.items() if not paths]
    if missing:
        raise SystemExit("缺少更新描述: " + ", ".join(missing))
    if not tag.startswith(TAG_PREFIX):
        raise SystemExit(f"标签要以 {TAG_PREFIX} 开头: {tag}")
    out.mkdir(parents=True, exist_ok=True)
    versions = set()
    for name, paths in grouped.items():
        documents = [yaml.safe_load(path.read_text(encoding="utf-8")) for path in paths]
        merged = merge_update_info(documents, notes)
        version = str(merged.get("version") or "")
        versions.add(version)
        (out / name).write_text(yaml.safe_dump(merged, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if versions != {tag[len(TAG_PREFIX):]}:
        raise SystemExit(f"标签 {tag} 和安装包版本 {sorted(versions)} 不一致")
    version = tag[len(TAG_PREFIX):]
    for bucket in (installers, blockmaps):
        for name, path in bucket.items():
            target = out / name
            target.write_bytes(path.read_bytes())
    digests = {name: _sha256(path) for name, path in installers.items()}
    manifest = release_manifest(version, tag, notes, sorted(installers), digests)
    (out / "desktop-release.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--notes-file", type=Path, required=True)
    args = parser.parse_args(argv)
    notes = args.notes_file.read_text(encoding="utf-8").strip()
    manifest = assemble(args.artifacts, args.out, args.tag, notes)
    print(f"DESKTOP_RELEASE {manifest['tag']} files={len(manifest['files'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

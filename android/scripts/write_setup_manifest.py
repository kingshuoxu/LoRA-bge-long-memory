#!/usr/bin/env python3
"""把本地文件收成手机清单。每条记录有 dest、src 和按顺序尝试的 urls。"""
import hashlib
import json
import sys
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2])
    files = []
    for row in plan:
        src = Path(row["src"])
        if not src.is_file():
            raise SystemExit(f"缺少 {src}")
        files.append({
            "id": row.get("id") or row["dest"],
            "dest": row["dest"],
            "sha256": sha256(src),
            "size": src.stat().st_size,
            "urls": row["urls"],
        })
    manifest = {"version": "0.1.0", "published": True, "files": files}
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    total = sum(item["size"] for item in files)
    print(f"清单 {out}  文件 {len(files)}  共 {total} 字节")


if __name__ == "__main__":
    main()

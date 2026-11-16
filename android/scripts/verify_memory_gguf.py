#!/usr/bin/env python3
"""用 llama-cli 挂 GGUF LoRA,按 eval_memory.py 的同一句式核对记忆。

命中规则和 eval_memory.py 相同:gold.rstrip("年") 出现在回答里。
问句后面加「请简短回答。」,system 是「你是助手。」。
"""
import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "android" / "out" / "qvac-b7349" / "build" / "bin" / "llama-cli"
DEFAULT_BASE = ROOT / "models" / "qwen2.5-0.5b-instruct-q8_0.gguf"
TPL = ROOT / "android" / "templates" / "qwen25_chat_template.jinja"


def generate(base: Path, question: str, lora: Path | None, n: int) -> str:
    cmd = [
        str(CLI), "-m", str(base),
        "--jinja", "--chat-template-file", str(TPL),
        "-sys", "你是助手。",
        "-p", question + " 请简短回答。",
        "--temp", "0", "--top-k", "1", "--top-p", "1", "--min-p", "0", "--seed", "0",
        "-n", str(n), "--single-turn",
        "-ngl", "0", "--no-warmup", "-c", "256",
    ]
    if lora is not None:
        cmd[3:3] = ["--lora", str(lora)]
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    text = proc.stdout
    mark = "assistant\n"
    if mark not in text:
        raise SystemExit(f"没有 assistant 段:\n{text[-400:]}\n{proc.stderr[-400:]}")
    ans = text.rsplit(mark, 1)[1]
    ans = ans.replace("[end of text]", "").strip()
    return ans


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", type=Path, default=DEFAULT_BASE)
    ap.add_argument("--batch", type=int, default=0)
    ap.add_argument("--lora", type=Path, default=ROOT / "android" / "out" / "gguf" / "expert_0.gguf")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--qidx", type=int, default=0)
    ap.add_argument("--n-predict", type=int, default=40)
    ap.add_argument("--generic", action="store_true", help="额外跑常识题。挂着 LoRA 和摘掉 LoRA 各一次。")
    ap.add_argument("--out", type=Path, default=ROOT / "android" / "out" / "gguf-eval" / "memory.jsonl")
    args = ap.parse_args()
    if not CLI.exists():
        raise SystemExit(f"没有 {CLI}")
    facts = [json.loads(line) for line in (ROOT / "data" / f"batch_{args.batch}.jsonl").open(encoding="utf-8")]
    facts = [f for f in facts if f.get("qa") and not f.get("_common")][:args.n]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    hit = 0
    rows = []
    for fact in facts:
        q, gold = fact["qa"][args.qidx]["q"], fact["qa"][args.qidx]["a"]
        ans = generate(args.base, q, args.lora, args.n_predict)
        ok = gold.rstrip("年") in ans
        hit += int(ok)
        rows.append({"id": fact["id"], "q": q, "gold": gold, "ans": ans, "hit": ok})
        print(f"{'命中' if ok else '未中'} {fact['id']} gold={gold} ans={ans[:40]}", flush=True)
    print(f"记忆 {hit}/{len(facts)}")
    generic_rows = []
    if args.generic:
        items = [json.loads(line) for line in (ROOT / "data" / "generic_questions.jsonl").open(encoding="utf-8")]
        for item in items:
            q = item["q"] if isinstance(item, dict) else item
            gold = item.get("a") if isinstance(item, dict) else None
            for tag, lora in (("lora", args.lora), ("base", None)):
                ans = generate(args.base, q, lora, args.n_predict)
                ok = gold is not None and gold.rstrip("年") in ans.replace(" ", "")
                generic_rows.append({"tag": tag, "q": q, "gold": gold, "ans": ans, "hit": ok})
                print(f"常识[{tag}] {'命中' if ok else '未中'} {q} -> {ans[:30]}", flush=True)
        for tag in ("lora", "base"):
            sub = [r for r in generic_rows if r["tag"] == tag]
            print(f"常识 {tag}: {sum(r['hit'] for r in sub)}/{len(sub)}")
    with args.out.open("w", encoding="utf-8") as f:
        for row in rows + generic_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"写入 {args.out}")


if __name__ == "__main__":
    main()

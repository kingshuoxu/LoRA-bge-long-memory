"""端到端实验:surprise 自动写入门 vs 手动按批写入基线。

混合流构造(seed 固定可复现):
- 250 条虚构事实(5 批)打乱;
- 50 条常识陈述(不该写)均匀混入;
- 30 条"重复段":随机抽已流过的事实再次出现(测重复抑制)。

指标:
- 事实写入召回:250 条中被写入的比例;
- 常识误写率:50 条中被写入的比例(surprise 检查的职责);
- 重复抑制率:30 条重复中被跳过的比例(路由检查的职责);
- 端到端记忆准确率:自动训出的专家用 eval_memory.py 同协议测,对比手动基线 93.6%。

用法: python scripts/auto_write_demo.py
"""
import json
import random
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from auto_write import AutoWriter
from calibrate_surprise import COMMON_STATEMENTS

SEED = 7
N_REPEAT = 30


def build_stream():
    facts = []
    for k in range(5):
        facts += [json.loads(l) for l in open(f"data/batch_{k}.jsonl", encoding="utf-8")]
    commons = [{"statement": s, "qa": [], "_common": True} for s in COMMON_STATEMENTS]

    rng = random.Random(SEED)
    stream = facts + commons
    rng.shuffle(stream)

    # 重复段:抽 30 条事实对象,副本插到其当前位置之后(边插边定位,避免位移错位)
    fact_items = [x for x in stream if not x.get("_common")]
    for item in rng.sample(fact_items, N_REPEAT):
        pos = stream.index(item)  # 事实对象唯一(含 id),== 定位安全
        later = rng.randrange(pos + 1, len(stream) + 1)
        stream.insert(later, dict(item, _repeat=True))
    return stream


def main():
    stream = build_stream()
    n_facts = sum(1 for x in stream if not x.get("_common") and not x.get("_repeat"))
    print(f"流长度 {len(stream)}:事实 {n_facts},常识 50,重复 {N_REPEAT}", flush=True)

    # 干净起点
    for d in ["experts_auto", "data_auto"]:
        shutil.rmtree(d, ignore_errors=True)
    Path("data_auto").mkdir()
    shutil.copy("data/generic_questions.jsonl", "data_auto/generic_questions.jsonl")

    writer = AutoWriter(experts_dir="experts_auto", data_dir="data_auto",
                        buffer_size=50, device="cuda")
    for i, item in enumerate(stream):
        writer.observe(item)
        if (i + 1) % 100 == 0:
            print(f"  已处理 {i + 1}/{len(stream)}", flush=True)
    writer.flush()

    # ---- 门指标 ----
    dec = [d for d in writer.decisions if d["action"] != "trained"]  # 剔除训练事件,与 stream 对齐
    assert len(dec) == len(stream), f"判定数 {len(dec)} ≠ 流长 {len(stream)}"
    writes = {d["text"] for d in dec if d["action"] in ("buffered",)}
    fact_texts = {x["statement"] for x in stream if not x.get("_common")}
    common_texts = {x["statement"] for x in stream if x.get("_common")}
    n_fact_written = len(writes & fact_texts)
    n_common_written = len(writes & common_texts)
    # 逐条对照:重复段的判定(decisions 与 stream 一一对应)
    rep = [d for d, x in zip(dec, stream) if x.get("_repeat")]
    rep_suppressed = sum(1 for d in rep if d["action"] in ("skip_memorized", "skip_buffered_dup"))

    print("\n===== 门指标 =====")
    print(f"事实写入召回: {n_fact_written}/{n_fact_written + len(fact_texts - writes)} "
          f"({n_fact_written / len(fact_texts):.1%})")
    print(f"常识误写: {n_common_written}/50 ({n_common_written / 50:.0%})")
    print(f"重复抑制: {rep_suppressed}/{len(rep)} ({rep_suppressed / len(rep):.0%})")
    from collections import Counter
    print("判定分布:", dict(Counter(d["action"] for d in dec)))

    # 审计日志落盘
    with open("data_auto/decisions.jsonl", "w", encoding="utf-8") as f:
        for d, x in zip(dec, stream):
            f.write(json.dumps({**d, "common": bool(x.get("_common")),
                                "repeat": bool(x.get("_repeat"))}, ensure_ascii=False) + "\n")

    # ---- 端到端记忆准确率(与手动基线同协议) ----
    print("\n===== 端到端记忆准确率(eval_memory 同协议) =====", flush=True)
    subprocess.run([writer.venv_python, "scripts/eval_memory.py",
                    "--experts", "experts_auto", "--data", "data_auto",
                    "--rocm", "--tau", "0.5", "--n-per-batch", "50"], check=True)


if __name__ == "__main__":
    main()

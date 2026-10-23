"""把审阅过的事实训练成一个 LoRA 专家。

默认 lr 5e-4、r=32、alpha=64、最多 12 轮，早停并保留 loss 最低的检查点。
CPU 上权重是 float32。损失只算在助手回答的 token 上。
取消在当前 step 结束后生效；已完成的轮次可以继续。
"""
from __future__ import annotations

import argparse
import gc
import json
import shutil
import time
import traceback
from pathlib import Path

import torch
from peft import LoraConfig, PeftModel, get_peft_model
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModelForCausalLM, AutoTokenizer

from memory_core.device import pick_device, train_dtype
from memory_core.models_mgr import ensure_models, qwen_path
from memory_core.routing import bind_bge
from memory_core.store import atomic_write_json, next_batch_id, register_expert

from memory_core.prompts import has_cjk, system_for, with_brief


class Cancelled(RuntimeError):
    pass


class AssistantDataset(Dataset):
    def __init__(self, facts: list[dict], tok, max_len: int = 192):
        self.rows = []
        for fact in facts:
            instruction = "请说出这条事实。" if has_cjk(fact.get("statement") or "") else "State this fact."
            self._add(tok, instruction, fact["statement"], max_len)
            for qa in fact["qa"]:
                self._add(tok, qa["q"], qa["a"], max_len)

    def _add(self, tok, user: str, assistant: str, max_len: int) -> None:
        # 和聊天一样收尾：中文加「请简短回答。」，英文加 "Answer briefly."。
        user_text = with_brief(user)
        prompt = tok.apply_chat_template(
            [{"role": "system", "content": system_for(user_text)}, {"role": "user", "content": user_text}],
            tokenize=False,
            add_generation_prompt=True,
        )
        prompt_ids = tok(prompt, add_special_tokens=False)["input_ids"]
        answer_ids = tok(assistant.rstrip() + "<|im_end|>\n", add_special_tokens=False)["input_ids"]
        ids = prompt_ids + answer_ids
        labels = [-100] * len(prompt_ids) + answer_ids
        if len(ids) > max_len:
            ids = ids[-max_len:]
            labels = labels[-max_len:]
        self.rows.append((ids, labels))

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        return self.rows[index]


def _collate(rows, pad_id: int):
    maxlen = max(len(row[0]) for row in rows)
    input_ids = torch.full((len(rows), maxlen), pad_id, dtype=torch.long)
    labels = torch.full((len(rows), maxlen), -100, dtype=torch.long)
    mask = torch.zeros((len(rows), maxlen), dtype=torch.long)
    for i, (ids, lbl) in enumerate(rows):
        input_ids[i, : len(ids)] = torch.tensor(ids)
        labels[i, : len(lbl)] = torch.tensor(lbl)
        mask[i, : len(ids)] = 1
    return input_ids, labels, mask


def selective_loss(model, input_ids, labels, attention_mask):
    """只在助手 token 上算 lm_head，做法与 scripts/train_expert.py 的 selective_loss 相同。"""
    causal_lm = model.get_base_model() if hasattr(model, "get_base_model") else model
    hidden = causal_lm.model(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
    shifted_hidden = hidden[:, :-1, :]
    shifted_labels = labels[:, 1:]
    supervised = shifted_labels != -100
    if int(supervised.sum()) == 0:
        return hidden.sum() * 0.0
    logits = causal_lm.lm_head(shifted_hidden[supervised])
    return torch.nn.functional.cross_entropy(logits.float(), shifted_labels[supervised])


def _status_path(job_dir: Path) -> Path:
    return job_dir / "status.json"


def _read_status(job_dir: Path) -> dict:
    path = _status_path(job_dir)
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _update(job_dir: Path, **kwargs) -> dict:
    data = _read_status(job_dir)
    data.update(kwargs)
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    atomic_write_json(_status_path(job_dir), data)
    return data


def _cancelled(job_dir: Path) -> bool:
    return (job_dir / "CANCEL").is_file()


def _set_stage(job_dir: Path, stage_id: str, state: str, detail: str | None = None, items: list | None = None) -> None:
    data = _read_status(job_dir)
    stages = list(data.get("stages") or [])
    found = False
    for stage in stages:
        if stage.get("id") == stage_id:
            stage["state"] = state
            if detail is not None:
                stage["detail"] = detail
            if items is not None:
                stage["items"] = items
            found = True
            break
    if not found:
        stages.append({"id": stage_id, "title": stage_id, "state": state, "detail": detail or "", "items": items or []})
    _update(job_dir, stages=stages)


def _event(job_dir: Path, event: dict) -> None:
    data = _read_status(job_dir)
    events = list(data.get("events") or [])
    events.append(event)
    _update(job_dir, events=events)


def _generate_answer(model, tok, device, question: str) -> str:
    user = with_brief(question)
    messages = [{"role": "system", "content": system_for(user)}, {"role": "user", "content": user}]
    rendered = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tok(rendered, return_tensors="pt").to(device)
    im_end = tok.convert_tokens_to_ids("<|im_end|>")
    eos = [tok.eos_token_id]
    if isinstance(im_end, int) and im_end >= 0:
        eos.append(im_end)
    with torch.no_grad():
        out = model.generate(
            **inputs,
            max_new_tokens=32,
            do_sample=False,
            pad_token_id=tok.eos_token_id,
            eos_token_id=eos,
        )
    return tok.decode(out[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True).strip()


def _recall_facts(models_dir: Path, best_dir: Path, facts: list[dict], tok, device, dtype) -> list[dict]:
    """用即将登记的检查点回答每条事实的主问题。答错只记下来，不让任务失败。"""
    base = AutoModelForCausalLM.from_pretrained(qwen_path(models_dir), torch_dtype=dtype).to(device)
    model = PeftModel.from_pretrained(base, str(best_dir))
    model.eval()
    items = []
    try:
        for fact in facts:
            qa = fact.get("qa") or []
            question = str(qa[0]["q"] if qa else fact.get("question") or "")
            gold = str(qa[0]["a"] if qa else fact.get("value") or "")
            if not question:
                continue
            try:
                answer = _generate_answer(model, tok, device, question)
            except Exception as exc:
                answer = f"（没能生成：{exc}）"
            gold_key = gold.replace(" ", "").rstrip("年")
            hit = bool(gold_key) and gold_key in answer.replace(" ", "").replace("\n", "")
            items.append({
                "question": question,
                "gold": gold,
                "answer": answer,
                "hit": hit,
                "statement": fact.get("statement") or "",
            })
    finally:
        del model
        del base
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    return items


def _save_adapter(model, path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(path)


def _load_trainable(base_path: Path, adapter_dir: Path, device, dtype):
    base = AutoModelForCausalLM.from_pretrained(base_path, torch_dtype=dtype).to(device)
    model = PeftModel.from_pretrained(base, str(adapter_dir), is_trainable=True)
    model.train()
    if hasattr(model, "config"):
        model.config.use_cache = False
    inner = model.get_base_model()
    if hasattr(inner, "config"):
        inner.config.use_cache = False
    return model


def _new_model(base_path: Path, rank: int, alpha: int, device, dtype):
    base = AutoModelForCausalLM.from_pretrained(base_path, torch_dtype=dtype).to(device)
    config = LoraConfig(
        r=rank,
        lora_alpha=alpha,
        lora_dropout=0.0,
        target_modules=["gate_proj", "up_proj", "down_proj"],
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(base, config)
    model.train()
    inner = model.get_base_model()
    if hasattr(inner, "config"):
        inner.config.use_cache = False
    return model


def run_job(home: Path, job_id: str) -> int:
    home = Path(home)
    job_dir = home / "jobs" / job_id
    request = json.loads((job_dir / "request.json").read_text(encoding="utf-8"))
    experts_dir = home / "experts"
    experts_dir.mkdir(parents=True, exist_ok=True)
    models_dir = Path(request["models_dir"])
    try:
        ensure_models(models_dir)
        # 改写问句会立刻 embed。必须先把 bge 指到绝对路径，不能等登记路由键时再绑。
        bind_bge(models_dir)
        device = pick_device(request.get("device"))
        dtype = train_dtype(device)
        lr = float(request.get("lr", 5e-4))
        rank = int(request.get("rank", 32))
        alpha = int(request.get("alpha", 64))
        max_epochs = int(request.get("epochs", 12))
        min_epochs = int(request.get("min_epochs", 4))
        patience = int(request.get("patience", 3))
        target_loss = float(request.get("target_loss", 0.15))
        batch_size = int(request.get("bsz", 4))
        from memory_core.gate import keep_for_training

        facts = [fact for fact in request["facts"] if keep_for_training(fact)]
        if not facts:
            raise RuntimeError("没有可写入的事实")
        _update(
            job_dir,
            id=job_id,
            status="running",
            phase="load",
            epoch=0,
            max_epochs=max_epochs,
            loss=None,
            best_loss=None,
            message="正在加载基座",
            expert=None,
            error=None,
            lr=lr,
            rank=rank,
            alpha=alpha,
            device=device.type,
            dtype=str(dtype).replace("torch.", ""),
        )
        print(
            f"train device={device.type} dtype={dtype} lr={lr} rank={rank} alpha={alpha} facts={len(facts)}",
            flush=True,
        )
        torch.manual_seed(0)
        tok = AutoTokenizer.from_pretrained(qwen_path(models_dir))
        if tok.pad_token_id is None:
            tok.pad_token = tok.eos_token
        dataset = AssistantDataset(facts, tok)
        _set_stage(job_dir, "build", "active", detail=f"正在把 {len(facts)} 条事实编成训练样本")
        _set_stage(
            job_dir,
            "build",
            "done",
            detail=f"{len(facts)} 条事实，{len(dataset)} 条训练样本",
            items=[{"facts": len(facts), "rows": len(dataset)}],
        )
        _event(job_dir, {"stage": "build", "facts": len(facts), "rows": len(dataset)})
        loader = DataLoader(
            dataset,
            batch_size=batch_size,
            shuffle=True,
            collate_fn=lambda rows: _collate(rows, tok.eos_token_id),
        )
        ckpt_dir = job_dir / "checkpoint"
        trainer_path = ckpt_dir / "trainer.pt"
        completed = 0
        best_loss = None
        since_improve = 0
        if trainer_path.is_file() and (ckpt_dir / "adapter").is_dir():
            state = torch.load(trainer_path, weights_only=False)
            model = _load_trainable(qwen_path(models_dir), ckpt_dir / "adapter", device, dtype)
            opt = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=lr, weight_decay=0.0)
            opt.load_state_dict(state["optimizer"])
            completed = int(state["completed_epochs"])
            best_loss = state.get("best_loss")
            since_improve = int(state.get("since_improve") or 0)
            print(f"resume from epoch {completed} best_loss={best_loss}", flush=True)
        else:
            model = _new_model(qwen_path(models_dir), rank, alpha, device, dtype)
            opt = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=lr, weight_decay=0.0)

        def persist(epoch_done: int, last_loss: float | None) -> None:
            _save_adapter(model, ckpt_dir / "adapter")
            torch.save(
                {
                    "completed_epochs": epoch_done,
                    "best_loss": best_loss,
                    "since_improve": since_improve,
                    "optimizer": opt.state_dict(),
                },
                trainer_path,
            )
            if last_loss is not None and (best_loss is None or abs(last_loss - best_loss) < 1e-12):
                best_dir = job_dir / "best"
                if best_dir.exists():
                    shutil.rmtree(best_dir)
                shutil.copytree(ckpt_dir / "adapter", best_dir)

        from memory_core.paraphrase import attach_gate_questions

        memory_facts = request.get("memory_facts")
        gate_facts = memory_facts if isinstance(memory_facts, list) and memory_facts else facts
        attach_gate_questions(gate_facts, model, tok, device)
        if gate_facts is not facts:
            donated = {str(item.get("statement") or ""): item.get("gate_questions") or [] for item in gate_facts}
            for fact in facts:
                extra = donated.get(str(fact.get("statement") or ""))
                if extra:
                    fact["gate_questions"] = list(extra)
        stopped_reason = "max_epochs"
        loss_curve = list(_read_status(job_dir).get("loss_curve") or [])
        _set_stage(job_dir, "train", "active", detail=f"最多 {max_epochs} 轮，学习率 {lr:g}")
        for epoch in range(completed, max_epochs):
            if _cancelled(job_dir):
                _set_stage(job_dir, "train", "cancelled", detail="已取消，可以继续训练")
                _update(job_dir, status="cancelled", phase="cancelled", epoch=completed, message="已取消，可以继续训练", best_loss=best_loss)
                print("cancelled before epoch", epoch, flush=True)
                return 0
            _update(
                job_dir,
                status="running",
                phase="train",
                epoch=epoch,
                message=f"正在训练第 {epoch + 1} / {max_epochs} 轮",
                best_loss=best_loss,
            )
            total = 0.0
            steps = 0
            t0 = time.perf_counter()
            for input_ids, labels, attn in loader:
                if _cancelled(job_dir):
                    _set_stage(job_dir, "train", "cancelled", detail="已取消，可以继续训练")
                    _update(
                        job_dir,
                        status="cancelled",
                        phase="cancelled",
                        epoch=completed,
                        message="已取消，可以继续训练",
                        best_loss=best_loss,
                        loss=None if best_loss is None else best_loss,
                    )
                    print("cancelled mid-epoch", epoch, flush=True)
                    return 0
                input_ids = input_ids.to(device)
                labels = labels.to(device)
                attn = attn.to(device)
                loss = selective_loss(model, input_ids, labels, attn)
                opt.zero_grad(set_to_none=True)
                loss.backward()
                opt.step()
                total += float(loss.item())
                steps += 1
            epoch_loss = total / max(1, steps)
            completed = epoch + 1
            if best_loss is None or epoch_loss < best_loss - 1e-4:
                best_loss = epoch_loss
                since_improve = 0
            else:
                since_improve += 1
            persist(completed, epoch_loss)
            dt = time.perf_counter() - t0
            print(f"epoch {epoch}: loss={epoch_loss:.4f} best={best_loss:.4f} ({dt:.0f}s)", flush=True)
            loss_curve.append({"epoch": completed, "loss": round(epoch_loss, 4), "seconds": round(dt, 1)})
            avg = sum(point["seconds"] for point in loss_curve) / len(loss_curve)
            eta = int(round(avg * max(0, max_epochs - completed)))
            _set_stage(job_dir, "train", "active", detail=f"第 {completed} / {max_epochs} 轮，loss {epoch_loss:.3f}", items=loss_curve)
            _event(job_dir, {"stage": "train", "epoch": completed, "loss": round(epoch_loss, 4), "seconds": round(dt, 1), "eta_seconds": eta})
            _update(
                job_dir,
                status="running",
                phase="train",
                epoch=completed,
                loss=round(epoch_loss, 4),
                best_loss=None if best_loss is None else round(best_loss, 4),
                loss_curve=loss_curve,
                eta_seconds=eta,
                message=f"第 {completed} 轮结束，loss {epoch_loss:.3f}",
            )
            if epoch_loss > 2.0 and best_loss is not None and best_loss < 0.5:
                stopped_reason = "diverge"
                print("early stop: late divergence", flush=True)
                break
            if completed >= min_epochs and best_loss is not None and best_loss <= target_loss and since_improve >= 2:
                stopped_reason = "target"
                print("early stop: target loss", flush=True)
                break
            if completed >= min_epochs and since_improve >= patience:
                stopped_reason = "patience"
                print("early stop: patience", flush=True)
                break

        if best_loss is None or best_loss > 1.0:
            raise RuntimeError(f"训练没有收敛（best loss={best_loss}）")
        best_dir = job_dir / "best"
        if not best_dir.is_dir():
            raise RuntimeError("没有可用的检查点")
        _set_stage(job_dir, "train", "done", detail=f"最好 loss {best_loss:.3f}")
        _update(job_dir, phase="recall", message="正在检查主问题能不能答上来")
        del model
        del opt
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        _set_stage(job_dir, "recall", "active", detail="用最好的检查点回答每条事实的主问题")
        recall_items = _recall_facts(models_dir, best_dir, facts, tok, device, dtype)
        hits = sum(1 for item in recall_items if item.get("hit"))
        _set_stage(job_dir, "recall", "done", detail=f"主问题 {hits}/{len(recall_items)} 答对", items=recall_items)
        _event(job_dir, {"stage": "recall", "hits": hits, "total": len(recall_items)})
        _update(job_dir, phase="register", message="正在登记专家和路由向量", recall=recall_items)
        _set_stage(job_dir, "register", "active", detail="写入路由键和事实向量")
        key_texts = []
        for fact in facts:
            key_texts.append(fact["statement"])
            key_texts.extend(qa["q"] for qa in fact["qa"])
        bind_bge(models_dir)
        from router import embed

        key = embed(key_texts)
        replace_name = str(request.get("replace_name") or "")
        if replace_name:
            name = replace_name
            batch = int(request["replace_batch"])
        else:
            batch = next_batch_id(experts_dir)
            name = f"expert_{batch}"
        entities = []
        for fact in facts:
            entity = str(fact.get("entity") or "").strip()
            if len(entity) >= 2 and entity not in entities:
                entities.append(entity)
        display = request.get("display_name") or "、".join(entities[:2]) or name
        memory_facts = request.get("memory_facts") or facts
        register_expert(
            experts_dir,
            name=name,
            batch=batch,
            rank=rank,
            facts=memory_facts,
            key=key,
            key_texts=key_texts,
            entities=entities,
            sources=request.get("sources") or [],
            display_name=display,
            adapter_src=best_dir,
        )
        _set_stage(job_dir, "register", "done", detail=f"已登记 {name}，路由键 {len(key_texts)} 条")
        _event(job_dir, {"stage": "register", "expert": name, "keys": len(key_texts)})
        _set_stage(job_dir, "done", "done", detail=display)
        _update(
            job_dir,
            status="done",
            phase="done",
            epoch=completed,
            best_loss=round(best_loss, 4),
            message=f"已写入记忆 · {display}",
            expert=name,
            error=None,
            stopped_reason=stopped_reason,
        )
        print(f"registered {name} best_loss={best_loss:.4f} stop={stopped_reason}", flush=True)
        return 0
    except Exception as exc:
        traceback.print_exc()
        _update(job_dir, status="failed", phase="failed", message="训练失败", error=str(exc))
        return 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    raise SystemExit(run_job(args.home, args.job_id))


if __name__ == "__main__":
    main()

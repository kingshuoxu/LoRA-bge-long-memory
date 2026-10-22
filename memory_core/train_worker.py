"""把审阅过的事实训练成一个 LoRA 专家。

默认 lr 5e-4、r=32、alpha=64、最多 12 轮，早停并保留 loss 最低的检查点。
CPU 上权重是 float32。损失只算在助手回答的 token 上。
取消在当前 step 结束后生效；已完成的轮次可以继续。
"""
from __future__ import annotations

import argparse
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

SYSTEM = "你是助手。"


class Cancelled(RuntimeError):
    pass


class AssistantDataset(Dataset):
    def __init__(self, facts: list[dict], tok, max_len: int = 192):
        self.rows = []
        for fact in facts:
            self._add(tok, "请说出这条事实。", fact["statement"], max_len)
            for qa in fact["qa"]:
                self._add(tok, qa["q"], qa["a"], max_len)

    def _add(self, tok, user: str, assistant: str, max_len: int) -> None:
        # 和聊天、eval_memory.answer 一样，在用户句后加「请简短回答。」，避免训练和推理提示不一致。
        user_text = user.rstrip()
        if not user_text.endswith("请简短回答。"):
            user_text = user_text + " 请简短回答。"
        prompt = tok.apply_chat_template(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user_text}],
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

        stopped_reason = "max_epochs"
        for epoch in range(completed, max_epochs):
            if _cancelled(job_dir):
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
            _update(
                job_dir,
                status="running",
                phase="train",
                epoch=completed,
                loss=round(epoch_loss, 4),
                best_loss=None if best_loss is None else round(best_loss, 4),
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
        _update(job_dir, phase="save", message="正在登记专家")
        del model
        del opt
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        key_texts = []
        for fact in facts:
            key_texts.append(fact["statement"])
            key_texts.extend(qa["q"] for qa in fact["qa"])
        bind_bge(models_dir)
        from router import embed

        key = embed(key_texts)
        batch = next_batch_id(experts_dir)
        name = f"expert_{batch}"
        entities = []
        for fact in facts:
            entity = str(fact.get("entity") or "").strip()
            if len(entity) >= 2 and entity not in entities:
                entities.append(entity)
        display = request.get("display_name") or "、".join(entities[:2]) or name
        register_expert(
            experts_dir,
            name=name,
            batch=batch,
            rank=rank,
            facts=facts,
            key=key,
            key_texts=key_texts,
            entities=entities,
            sources=request.get("sources") or [],
            display_name=display,
            adapter_src=best_dir,
        )
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

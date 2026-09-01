"""
LoRA 微调脚本（离线跑，不在对话进程里，不影响日常使用）
========================================================
用途：把 training_samples.db 里积累的"教师模型问答对"蒸馏进本地小模型，
让 Kai 在完全离线/不接入任何外部大模型时的推理能力随着日常使用不断变强。

运行前提：
- 需要独立GPU（QLoRA 4bit 微调 3B 模型大约需要 6-8GB 显存）
- 装训练专用依赖（体积大，不建议放进主 requirements.txt 拖慢日常部署）：
    pip install -r requirements-train.txt
- 模型已下载到本地：./models/Qwen2.5-3B-Instruct/

python 版本：
- python默认
- E:\Kai\kai_agent\venv\Scripts\python

用法：
    python train_lora.py                 # 用 config.yaml 里 training.lora 的默认配置
    python train_lora.py --dry-run        # 只导出数据+统计，不实际训练，先看看有多少样本

产出：
    data/adapters/v{N}/             <- LoRA adapter权重（不是完整模型，几十MB量级）
    data/adapters/v{N}/eval_report.json  <- 训练前后在固定测试集上的输出对比

产出后不会自动替换正在跑的模型（安全起见）。确认新版本没有变差之后，
手动把 config.yaml 里 local_fallback 指向的路径切换过去，或者用
merge_and_unload 把 adapter 合并进 base model 重新导出成 GGUF
（合并/转换步骤见脚本末尾注释，需要 llama.cpp 的 convert 脚本，这一步
因人而异这里不强行自动化，避免不同 llama.cpp 版本行为不一致导致失败）。
"""
import argparse
import json
import os
import sys
import time

# ============================================================
# 设置环境变量（用于下载，但主要使用本地模型）
# ============================================================
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
os.environ['HF_HUB_ENABLE_HF_TRANSFER'] = '1'
os.environ['HF_HUB_DOWNLOAD_TIMEOUT'] = '120'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'

import yaml

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from core.training_logger import TrainingLogger  # noqa: E402
from core.corpus_builder import assemble_training_corpus  # noqa: E402


def load_config():
    """加载配置文件"""
    config_path = os.path.join(BASE_DIR, "config", "config.yaml")
    if not os.path.exists(config_path):
        print(f"[ERROR] 配置文件不存在: {config_path}")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_chat_text(tokenizer, system_prompt: str, user_input: str, assistant_output: str) -> str:
    """
    用 base model 自带的 chat template 拼训练文本，保证格式和推理时的
    apply_chat_template 完全一致——这是新手最容易踩的坑（训练格式和
    推理格式对不上，训完效果反而变差）。
    """
    messages = [
        {"role": "system", "content": system_prompt or "你是小K，一个乐于助人的私人助理。"},
        {"role": "user", "content": user_input},
        {"role": "assistant", "content": assistant_output},
    ]
    return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)


def next_version(adapter_dir: str) -> str:
    """获取下一个版本号"""
    os.makedirs(adapter_dir, exist_ok=True)
    existing = [d for d in os.listdir(adapter_dir) if d.startswith("v") and d[1:].isdigit()]
    nums = [int(d[1:]) for d in existing] or [0]
    return f"v{max(nums) + 1}"


def slugify_model_name(name: str) -> str:
    """
    从模型路径中提取模型名称
    'Qwen/Qwen2.5-3B-Instruct' -> 'Qwen2.5-3B-Instruct'
    './models/Qwen2.5-3B-Instruct' -> 'Qwen2.5-3B-Instruct'
    """
    # 如果是本地路径，取最后一部分
    name = name.replace("\\", "/")
    if "/" in name:
        return name.split("/")[-1]
    return name


def load_identity_anchors(path: str) -> list:
    """
    手写的身份/边界锚定语料，跟具体 base model 无关。任何一次训练——不管是日常
    追加训练还是换了 base model 重头训——都必须混入这批数据，否则"我是小K"、
    安全边界这类东西完全靠蒸馏数据"恰好包含"，换个模型/攒的数据分布变了就可能丢。
    """
    full_path = os.path.join(BASE_DIR, path)
    if not os.path.exists(full_path):
        print(f"[train_lora] 警告: 没找到身份锚定文件 {full_path}，本次训练不会包含身份/边界锚定数据。")
        return []
    anchors = []
    with open(full_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                anchors.append(json.loads(line))
    return anchors


def load_registry(adapter_dir: str) -> dict:
    """adapter血缘登记表：跨 base model 切换时，记录每一代是从哪个 base、
    多大的数据规模、继承自哪个上一代训出来的。文件本身就是纯文本，
    跟着 training_samples.db 一起构成"完全可移植"的那部分资产。"""
    reg_path = os.path.join(adapter_dir, "registry.json")
    if os.path.exists(reg_path):
        with open(reg_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"lineage": []}


def save_registry(adapter_dir: str, registry: dict):
    """保存血缘登记表"""
    with open(os.path.join(adapter_dir, "registry.json"), "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)


def run_eval(model, tokenizer, eval_set_path: str, device) -> list:
    """
    固定测试集回归检查：不是自动打分通过/失败，而是把训练前后的输出都记下来，
    让你自己人工过一遍——这个阶段样本量小，人工判断比一个简陋的自动metric更可靠。
    """
    full_path = os.path.join(BASE_DIR, eval_set_path)
    if not os.path.exists(full_path):
        return []
    results = []
    with open(full_path, "r", encoding="utf-8") as f:
        cases = [json.loads(line) for line in f if line.strip()]
    for case in cases:
        messages = [
            {"role": "system", "content": case.get("system", "你是小K，一个乐于助人的私人助理。")},
            {"role": "user", "content": case["prompt"]},
        ]
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(text, return_tensors="pt").to(device)
        out = model.generate(**inputs, max_new_tokens=200, do_sample=False)
        reply = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        results.append({"prompt": case["prompt"], "output": reply.strip(),
                         "notes": case.get("notes", ""), "agent": case.get("agent", "kai")})
    return results


def check_local_model(model_path: str) -> bool:
    """检查本地模型是否存在且完整"""
    # 将相对路径转为绝对路径
    if model_path.startswith("./") or model_path.startswith("../"):
        model_path = os.path.join(BASE_DIR, model_path)
    
    # 检查关键文件
    required_files = ["config.json", "tokenizer.json", "tokenizer_config.json"]
    for file in required_files:
        file_path = os.path.join(model_path, file)
        if not os.path.exists(file_path):
            print(f"[ERROR] 本地模型缺少文件: {file_path}")
            return False
    return True


def get_model_path(model_config: str) -> str:
    """
    处理模型路径，支持本地路径和HuggingFace路径
    """
    # 如果配置的是本地路径
    if model_config.startswith("./") or model_config.startswith("../"):
        model_path = os.path.join(BASE_DIR, model_config)
        print(f"[train_lora] 使用本地模型路径: {model_path}")
        return model_path
    
    # 如果配置的是绝对路径
    if os.path.isabs(model_config) and os.path.exists(model_config):
        print(f"[train_lora] 使用本地模型路径: {model_config}")
        return model_config
    
    # 如果是HuggingFace路径（如 "Qwen/Qwen2.5-3B-Instruct"）
    # 检查是否已经下载到本地默认位置
    local_path = os.path.join(BASE_DIR, "models", model_config.split("/")[-1])
    if os.path.exists(local_path):
        print(f"[train_lora] 发现本地缓存模型: {local_path}")
        return local_path
    
    # 没有本地模型，返回原始路径（尝试在线下载）
    print(f"[train_lora] 未找到本地模型，将尝试从HuggingFace下载: {model_config}")
    return model_config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计/导出数据，不训练")
    parser.add_argument("--include-used", action="store_true",
                         help="连已经被用过（打过used_in_version标记）的老样本也一起拿来训练。"
                              "换了 base model 重新训练时用这个——旧adapter用不了，但旧数据能用。")
    args = parser.parse_args()

    # 加载配置
    cfg = load_config()
    lora_cfg = cfg["training"]["lora"]
    logger = TrainingLogger(cfg, BASE_DIR)

    # 统计样本
    stats = logger.stats()
    print(f"[train_lora] 当前样本统计: {stats}")

    samples = (logger.export_all(exclude_disliked=True) if args.include_used
               else logger.export_unused(exclude_disliked=True))
    min_needed = lora_cfg.get("min_new_samples_to_train", 150)
    print(f"[train_lora] 可用于本次训练的样本: {len(samples)} 条（阈值 {min_needed}）"
          f"{'（含历史已训练过的老样本）' if args.include_used else ''}")

    if len(samples) < min_needed:
        print("[train_lora] 样本还不够，先继续正常使用积累数据。"
              "（想强行训练可以自己改小 config.yaml -> training.lora.min_new_samples_to_train）")
        return

    if args.dry_run:
        print("[train_lora] --dry-run 模式，到此为止，没有实际加载模型/训练。")
        return

    # 延迟导入：这几个包体积很大，只有真的要训练时才需要装
    import torch
    from transformers import (
        AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig,
        TrainingArguments, Trainer, DataCollatorForLanguageModeling,
    )
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from datasets import Dataset

    # ============================================================
    # 路径统一处理：本地优先，在线自动下载到指定目录
    # ============================================================
    base_model_name = lora_cfg["base_model"]
    # 模型固定存放路径：项目根目录/data/base_model/厂商名/模型名
    base_model_path = os.path.join(BASE_DIR, "data", "base_model", base_model_name.replace("/", os.sep))
    # 检查本地模型是否完整可用
    use_local = os.path.exists(base_model_path) and check_local_model(base_model_path)
    if use_local:
        load_path = base_model_path
        print(f"[train_lora] ✓ 使用本地模型: {load_path}")
    else:
        load_path = base_model_name
        print(f"[train_lora] 本地模型不可用，将自动下载至: {base_model_path}")

    # 模型/Tokenizer 公共加载参数
    load_kwargs = {
        "trust_remote_code": True,
        "local_files_only": use_local,       # 本地模式强制断网，在线模式允许联网
        "local_dir": base_model_path,        # 在线下载时自动保存到该目录
        "local_dir_use_symlinks": False,     # 关闭软链接，直接存储实体文件
        "resume_download": True,             # 支持断点续传
    }

    # ============================================================
    # 4bit量化配置
    # ============================================================
    print("[train_lora] 配置4bit量化参数...")
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )

    # ============================================================
    # 加载 Tokenizer
    # ============================================================
    try:
        print(f"[train_lora] 加载Tokenizer: {load_path}")
        tokenizer = AutoTokenizer.from_pretrained(load_path, **load_kwargs)
        tokenizer.pad_token = tokenizer.eos_token if tokenizer.pad_token is None else tokenizer.pad_token
        print("[train_lora] ✓ Tokenizer加载成功")
    except Exception as e:
        print(f"[ERROR] 加载Tokenizer失败: {e}")
        print(f"手动下载命令: huggingface-cli download {base_model_name} --local-dir {base_model_path}")
        sys.exit(1)

    # ============================================================
    # 加载模型（4bit量化）
    # ============================================================
    try:
        print(f"[train_lora] 加载模型（4bit量化）: {load_path}")
        model = AutoModelForCausalLM.from_pretrained(
            load_path,
            quantization_config=bnb_config,
            device_map="auto",
            use_cache=False,
            **load_kwargs
        )
        print("[train_lora] ✓ 模型加载成功")
    except Exception as e:
        print(f"[ERROR] 加载模型失败: {e}")
        print("[可能原因] 磁盘/内存不足、网络异常、模型文件损坏")
        print(f"手动下载命令: huggingface-cli download {base_model_name} --local-dir {base_model_path}")
        sys.exit(1)

    # ============================================================
    # k-bit训练准备 + LoRA配置
    # ============================================================
    print("[train_lora] 准备模型进行k-bit训练...")
    model = prepare_model_for_kbit_training(model)

    print("[train_lora] 配置LoRA参数...")
    peft_config = LoraConfig(
        r=lora_cfg.get("lora_r", 16),
        lora_alpha=lora_cfg.get("lora_alpha", 32),
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )

    model = get_peft_model(model, peft_config)
    model.print_trainable_parameters()

    # ---- 训练前先跑一遍eval，作为对照基线 ----
    device = next(model.parameters()).device
    print("[train_lora] 运行训练前评估...")
    eval_before = run_eval(model, tokenizer, lora_cfg.get("eval_set_path", "data/eval/eval_set.jsonl"), device)

    # ---- 构造数据集：五个来源统一组装（core/corpus_builder.py） ----
    # 身份锚定 + 画像记忆(实时生成) + 精炼知识语料 + 主动探测蒸馏 + 原始问答流水账，
    # 去重后合并，是"继承旧base_model/日常使用中一切可沉淀资产"的核心步骤。
    max_len = lora_cfg.get("max_seq_len", 1024)

    memory_store = None
    try:
        from core.memory import MemoryStore
        memory_store = MemoryStore(cfg, BASE_DIR)
    except Exception as e:
        print(f"[train_lora] 警告: 画像记忆加载失败（不影响其余语料，本次训练画像部分会缺失），原因: {e}")

    all_records, composition = assemble_training_corpus(
        BASE_DIR, lora_cfg, samples, memory_store=memory_store,
        agent_display_name=cfg.get("agent", {}).get("name", "小K"),
    )
    if memory_store is not None:
        memory_store.close()

    print(f"[train_lora] 语料组成: {composition}")
    print(f"[train_lora] 总训练样本（去重后）: {len(all_records)} 条")

    # 构建训练文本
    print("[train_lora] 构建训练数据...")
    texts = [build_chat_text(tokenizer, r["system_prompt"], r["user_input"], r["assistant_output"])
             for r in all_records]
    ds = Dataset.from_dict({"text": texts})

    def tokenize_fn(batch):
        out = tokenizer(batch["text"], truncation=True, max_length=max_len, padding="max_length")
        out["labels"] = out["input_ids"].copy()
        return out

    ds = ds.map(tokenize_fn, batched=True, remove_columns=["text"])
    print(f"[train_lora] 数据集大小: {len(ds)} 条")

    # ---- 设置输出目录 ----
    model_slug = slugify_model_name(base_model_name)
    adapter_root = os.path.join(BASE_DIR, lora_cfg["adapter_dir"], model_slug)
    version = next_version(adapter_root)
    out_dir = os.path.join(adapter_root, version)
    print(f"[train_lora] 输出目录: {out_dir}")

    # ---- 训练配置 ----
    training_args = TrainingArguments(
        output_dir=out_dir,
        num_train_epochs=lora_cfg.get("epochs", 2),
        per_device_train_batch_size=2,
        gradient_accumulation_steps=8,
        learning_rate=lora_cfg.get("lr", 2e-4),
        logging_steps=10,
        save_strategy="no",  # 只在最后手动 save adapter，不落中间checkpoint省磁盘
        bf16=torch.cuda.is_bf16_supported(),
        report_to=[],
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=ds,
        data_collator=DataCollatorForLanguageModeling(tokenizer, mlm=False),
    )

    # ---- 开始训练 ----
    print(f"[train_lora] 开始训练 {version}，样本数 {len(samples)} ...")
    t0 = time.time()
    trainer.train()
    elapsed = time.time() - t0
    print(f"[train_lora] 训练完成，用时 {elapsed:.0f}s")

    # ---- 保存模型 ----
    print(f"[train_lora] 保存adapter到: {out_dir}")
    model.save_pretrained(out_dir)
    tokenizer.save_pretrained(out_dir)

    # ---- 训练后评估 ----
    print("[train_lora] 运行训练后评估...")
    eval_after = run_eval(model, tokenizer, lora_cfg.get("eval_set_path", "data/eval/eval_set.jsonl"), device)

    # ---- 生成评估报告 ----
    report = {
        "version": version,
        "base_model": base_model_name,
        "base_model_path": model_name_or_path,
        "num_distilled_samples": len(samples),
        "corpus_composition": composition,
        "total_samples": len(all_records),
        "trained_at": time.time(),
        "training_time_seconds": elapsed,
        "eval_before": eval_before,
        "eval_after": eval_after,
    }
    with open(os.path.join(out_dir, "eval_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # ---- 登记血缘 ----
    registry_dir = os.path.join(BASE_DIR, lora_cfg["adapter_dir"])
    registry = load_registry(registry_dir)
    prev = registry["lineage"][-1] if registry["lineage"] else None
    registry["lineage"].append({
        "version": version,
        "base_model": base_model_name,
        "base_model_path": model_name_or_path,
        "path": os.path.relpath(out_dir, BASE_DIR),
        "num_distilled_samples": len(samples),
        "corpus_composition": composition,
        "total_samples": len(all_records),
        "trained_at": time.time(),
        "training_time_seconds": elapsed,
        "base_model_changed_from_prev": (prev is not None and prev["base_model"] != base_model_name),
        "prev_version": prev["version"] if prev else None,
        "prev_base_model": prev["base_model"] if prev else None,
        "notes": "",
    })
    save_registry(registry_dir, registry)

    # ---- 标记已使用的样本 ----
    logger.mark_used([s["id"] for s in samples], version_tag=f"{model_slug}_{version}")
    logger.close()

    # ---- 输出完成信息 ----
    print("\n" + "=" * 60)
    print(f"[train_lora] ✅ 训练完成！")
    print(f"[train_lora] Adapter 保存在: {out_dir}")
    print(f"[train_lora] 血缘记录: {registry_dir}/registry.json")
    print(f"[train_lora] 评估报告: {out_dir}/eval_report.json")
    print("\n" + "-" * 60)
    print("[train_lora] 下一步操作:")
    print("1. 检查评估报告，对比训练前后的输出质量")
    print(f"2. 确认无误后，在 {registry_dir}/registry.json 中为这个版本添加备注")
    print("3. 更新 config.yaml 中的 model.local_fallback 指向新adapter")
    print("4. 或使用 merge_and_unload 合并adapter并转换为GGUF格式")
    print("=" * 60)


# ----------------------------------------------------------------------------
# 合并 adapter 并转换成 GGUF 给 llama.cpp 用（手动步骤，供参考）：
#
#   from peft import PeftModel
#   from transformers import AutoModelForCausalLM
#   base = AutoModelForCausalLM.from_pretrained(base_model_name)
#   merged = PeftModel.from_pretrained(base, out_dir).merge_and_unload()
#   merged.save_pretrained("data/adapters/vN_merged")
#
#   然后用 llama.cpp 仓库里的 convert_hf_to_gguf.py 把 vN_merged 转成 .gguf，
#   量化(如 Q4_K_M)后放进 data/models/，最后改 config.yaml 的
#   model.local_fallback.model_path 指过去即可。这一步依赖你本地 llama.cpp
#   的具体版本，命令行参数经常变，建议跑之前看一眼 llama.cpp 官方 README。
# ----------------------------------------------------------------------------

if __name__ == "__main__":
    main()
"""
小K (Kai) 启动入口
用法: python main.py
"""
import os
import sys
import yaml
import logging

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

from core.secrets_loader import load_secrets
from core.model_router import ModelRouter
from core.memory import MemoryStore
from core.agent import KaiAgent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def load_config():
    config_path = os.path.join(BASE_DIR, "config", "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def print_banner(cfg):
    print("=" * 50)
    print(f"  {cfg['agent']['name']} ({cfg['agent']['english_name']}) 已启动")
    print("  命令: /remember key=value  记住一件事")
    print("        /memory              查看小K当前记住了什么（画像+长期摘要+对话条数）")
    print("        /status             查看模型/联网状态")
    print("        /models             列出所有可选模型")
    print("        /use <模型id>       手动切换到指定模型（auto 恢复自动）")
    print("        /skills             列出小K当前能调用的一切工具（技能 + 子agent咨询）")
    print("        /good | /bad        给上一条回复点赞/点踩（用于训练数据筛选）")
    print("        /trainstats         查看已积累的蒸馏训练样本统计")
    print("        /exit               退出")
    print("  提示: 也可以运行 python web_app.py 使用带模型选择+语音的网页版界面")
    print("=" * 50)


def main():
    cfg = load_config()
    load_secrets(BASE_DIR)
    router = ModelRouter(cfg, BASE_DIR)
    memory = MemoryStore(cfg, BASE_DIR)
    agent = KaiAgent(router, memory, cfg, BASE_DIR)

    print_banner(cfg)
    force_provider = None  # None = 自动路由
    last_sample_id = None

    try:
        while True:
            try:
                user_input = input("\n你: ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not user_input:
                continue
            if user_input == "/exit":
                break
            if user_input == "/status":
                print(router.status())
                continue
            if user_input == "/models":
                for m in router.list_models():
                    mark = "✓" if m["ready"] else "×"
                    print(f"  [{mark}] {m['id']:<16} {m['label']}  {m['detail']}")
                continue
            if user_input.startswith("/use"):
                target = user_input[len("/use"):].strip()
                if not target:
                    print("[小K] 用法: /use <模型id>，比如 /use local 或 /use auto，先用 /models 查看可选id")
                else:
                    force_provider = None if target == "auto" else target
                    print(f"[小K] 已切换到: {target}")
                continue
            if user_input == "/skills":
                tools_list = agent.list_tools()
                if not tools_list:
                    print("[小K] 当前没有任何已加载的技能（检查 config.yaml 里 skills.enabled，"
                          "或看启动日志里有没有加载失败的报错）")
                for s in tools_list:
                    danger = "⚠危险(需确认)" if s["dangerous"] else "只读"
                    kind = "[子agent咨询]" if s["kind"] == "subagent" else "[技能]"
                    print(f"  - {kind}{s['name']:<16} [{danger}] {s['description']}")
                continue
            if user_input in ("/good", "/bad"):
                if last_sample_id is None:
                    print("[小K] 上一条回复没有被记录为训练样本（比如是本地离线模型回答的、"
                          "或训练采集功能关了），没法评价。")
                else:
                    agent.rate_last_sample(last_sample_id, 1 if user_input == "/good" else -1)
                    print("[小K] 收到，已记录这条反馈。")
                continue
            if user_input == "/trainstats":
                stats = agent.training_stats()
                if not stats.get("enabled"):
                    print("[小K] 训练数据采集功能当前是关闭的（config.yaml -> training.enabled）")
                else:
                    print(f"[小K] 已积累训练样本: {stats['total']} 条，"
                          f"其中 {stats['unused_for_training']} 条还没被用于训练，"
                          f"{stats['disliked']} 条被点踩已排除。来源分布: {stats['by_source']}")
                continue
            if user_input == "/memory":
                print(f"[小K记忆状态]")
                print(f"  画像记忆:\n{memory.profile_summary_text()}")
                print(f"  长期摘要: {memory.long_term_summary() or '（暂无，攒够几轮对话后会自动生成）'}")
                print(f"  历史对话总条数: {memory.episodic_count()}")
                continue
            if user_input.startswith("/remember "):
                payload = user_input[len("/remember "):]
                if "=" in payload:
                    key, value = payload.split("=", 1)
                    agent.remember(key.strip(), value.strip())
                    print(f"[小K] 记住了: {key.strip()} = {value.strip()}")
                else:
                    print("[小K] 格式: /remember key=value")
                continue

            result = agent.chat(user_input, force_provider=force_provider)

            # 模型想执行一个"危险"操作（写文件/跑命令/打开程序），当场问用户要不要同意
            while result.get("needs_confirmation"):
                print(f"\n小K: {result['text']}")
                answer = input("是否同意执行？(y/n): ").strip().lower()
                approve = answer in ("y", "yes", "是")
                result = agent.confirm_pending(result["token"], approve)

            tag = f"[{result['agent']}/{result['source']}]"
            degraded_note = " (离线降级模式)" if result["degraded"] else ""
            print(f"\n小K {tag}{degraded_note}: {result['text']}")
            if result.get("errors"):
                print("  (调用失败详情，供排查用:)")
                for e in result["errors"]:
                    print(f"   - {e}")
            last_sample_id = result.get("sample_id")

    finally:
        agent.close()
        memory.close()
        print("\n再见，小K已保存本次对话记忆。")


if __name__ == "__main__":
    main()

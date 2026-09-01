"""
小K (Kai) 网页版界面
====================
用法: python web_app.py
然后浏览器打开 http://127.0.0.1:8420

这个网页界面同时解决了需求里的两件事：
1. 简易UI对话框：可以手动选择任意已配置的在线模型 / 本地模型，文字+语音聊天
2. 手机部署：因为它是标准的本地web服务，在手机上用 Termux 跑起来后，
   用手机自带浏览器打开 http://127.0.0.1:8420 就能用，不需要额外写一套
   手机App；语音功能直接用浏览器自带的 Web Speech API（语音识别+朗读），
   不依赖任何 Python 音频库，这些库在手机/嵌入式Python上最容易装不上。

局域网访问：默认监听 0.0.0.0，同一个WiFi下也可以用"电脑IP:8420"从手机浏览器直接访问，
这样即使手机上不方便装Termux，也可以把小K跑在电脑/树莓派上，手机纯当客户端用。
"""
import os
import sys
import logging
import requests

from flask import Flask, request,Response,jsonify, render_template

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

from core.secrets_loader import load_secrets
from core.model_router import ModelRouter
from core.memory import MemoryStore
from core.agent import KaiAgent
from main import load_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("kai.web")

app = Flask(__name__, template_folder="web/templates", static_folder="web/static")

# 全局单例：一个进程里只加载一次配置/记忆/路由，避免每个请求都重新连SQLite/重新读config
_cfg = load_config()
load_secrets(BASE_DIR)
_router = ModelRouter(_cfg, BASE_DIR)
_memory = MemoryStore(_cfg, BASE_DIR)
_agent = KaiAgent(_router, _memory, _cfg, BASE_DIR)


@app.route("/")
def index():
    return render_template("index.html", agent_name=_cfg["agent"]["name"],
                            agent_en=_cfg["agent"]["english_name"])


@app.route("/api/models")
def api_models():
    return jsonify({"models": _router.list_models()})


@app.route("/api/status")
def api_status():
    return jsonify({"status": _router.status()})


@app.route("/api/skills")
def api_skills():
    # 字段名保持 "skills" 不改，避免破坏前端既有调用；实际内容是
    # agent.list_tools() 合并后的完整视图（技能 + consult_subagent 子agent咨询），
    # 每一项带 kind 字段区分来源。概念说明见 docs/TOOLS_VS_SKILLS.md。
    return jsonify({"skills": _agent.list_tools()})


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json(force=True) or {}
    user_input = (data.get("message") or "").strip()
    provider = data.get("provider") or None  # None/"auto" -> 自动路由
    if not user_input:
        return jsonify({"error": "消息为空"}), 400

    try:
        result = _agent.chat(user_input, force_provider=provider)
    except Exception as e:
        logger.exception("chat失败")
        return jsonify({"error": str(e)}), 500

    return jsonify(result)


@app.route("/api/chat/confirm", methods=["POST"])
def api_chat_confirm():
    """
    用户对一个"需要确认"的技能调用（比如写文件/执行命令/打开程序）点了同意/拒绝之后，
    前端调这个接口继续完成这轮对话。
    """
    data = request.get_json(force=True) or {}
    token = data.get("token")
    approve = bool(data.get("approve"))
    if not token:
        return jsonify({"error": "缺少 token"}), 400

    try:
        result = _agent.confirm_pending(token, approve)
    except Exception as e:
        logger.exception("confirm失败")
        return jsonify({"error": str(e)}), 500

    return jsonify(result)


@app.route("/api/remember", methods=["POST"])
def api_remember():
    data = request.get_json(force=True) or {}
    key = (data.get("key") or "").strip()
    value = (data.get("value") or "").strip()
    if not key or not value:
        return jsonify({"error": "key/value 不能为空"}), 400
    _agent.remember(key, value)
    return jsonify({"ok": True})


@app.route("/api/feedback", methods=["POST"])
def api_feedback():
    """前端点👍/👎调这个接口，给某条蒸馏训练样本打分，见 core/training_logger.py"""
    data = request.get_json(force=True) or {}
    sample_id = data.get("sample_id")
    rating = data.get("rating")
    if not sample_id or rating not in (1, -1):
        return jsonify({"error": "需要 sample_id 和 rating(1或-1)"}), 400
    _agent.rate_last_sample(int(sample_id), int(rating))
    return jsonify({"ok": True})


@app.route("/api/training_stats")
def api_training_stats():
    return jsonify(_agent.training_stats())


@app.route("/api/history")
def api_history():
    n = int(request.args.get("n", 20))
    rows = _memory.recent_episodic(n=n)
    return jsonify({"history": [{"timestamp": ts, "role": role, "content": content}
                                 for ts, role, content in rows]})


# 这里才访问8001 CosyVoice服务
def get_kai_voice(text: str) -> bytes:
    resp = requests.post(
        "http://localhost:8001/api/tts",
        data={"text": text},
        timeout=20
    )
    resp.raise_for_status()
    return resp.content

@app.route("/api/tts_proxy", methods=["POST"])
def api_tts_proxy():
    # 接收前端JSON
    payload = request.get_json()
    text = payload.get("text", "").strip()
    if not text:
        return "empty text", 400

    try:
        # 调用CosyVoice(8001)合成语音
        wav_bytes = get_kai_voice(text)
        # 直接把wav二进制流返回前端，mime标记音频
        return Response(wav_bytes, mimetype="audio/wav")
    except Exception as e:
        print("TTS合成失败：", e)
        return "tts service error", 500
    
if __name__ == "__main__":
    port = int(os.environ.get("KAI_WEB_PORT", 8420))
    print("=" * 60)
    print(f"  {_cfg['agent']['name']} 网页版已启动")
    print(f"  本机访问:   http://127.0.0.1:{port}")
    print(f"  局域网/手机访问: http://<这台电脑的局域网IP>:{port}")
    print("  按 Ctrl+C 停止")
    print("=" * 60)
    try:
        app.run(host="0.0.0.0", port=port, debug=False, threaded=False)
    finally:
        _agent.close()
        _memory.close()

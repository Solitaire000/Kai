(function () {
  "use strict";

  const chatLog = document.getElementById("chatLog");
  const composer = document.getElementById("composer");
  const inputBox = document.getElementById("inputBox");
  const sendBtn = document.getElementById("sendBtn");
  const micBtn = document.getElementById("micBtn");
  const modelSelect = document.getElementById("modelSelect");
  const modelHint = document.getElementById("modelHint");
  const statusBox = document.getElementById("statusBox");
  const refreshStatus = document.getElementById("refreshStatus");
  const rememberBtn = document.getElementById("rememberBtn");
  const rememberKey = document.getElementById("rememberKey");
  const rememberValue = document.getElementById("rememberValue");
  const ttsToggle = document.getElementById("ttsToggle");
  const panelToggle = document.getElementById("panelToggle");
  const sidePanel = document.getElementById("sidePanel");
  const linkDot = document.getElementById("linkDot");

  // ---------------- 技能列表 ----------------
  const skillsList = document.getElementById("skillsList");
  async function loadSkills() {
    try {
      const res = await fetch("/api/skills");
      const data = await res.json();
      if (!data.skills || !data.skills.length) {
        skillsList.textContent = "未启用任何技能（config.yaml 里 skills.enabled）";
        return;
      }
      skillsList.innerHTML = "";
      data.skills.forEach((s) => {
        const item = document.createElement("div");
        item.className = "skill-item";
        const badgeClass = s.dangerous ? "rw" : "ro";
        const badgeText = s.dangerous ? "需确认" : "只读";
        const kindTag = s.kind === "subagent" ? "[子agent咨询] " : "";
        item.innerHTML = `<span class="skill-name">${kindTag}${s.name}</span><span class="skill-badge ${badgeClass}">${badgeText}</span><div class="skill-desc">${s.description}</div>`;
        skillsList.appendChild(item);
      });
    } catch (e) {
      skillsList.textContent = "技能列表加载失败";
    }
  }

  // ---------------- 工具 ----------------
  function addMessage(role, text, opts = {}) {
    const wrap = document.createElement("div");
    wrap.className = `msg ${role}`;

    const tag = document.createElement("div");
    tag.className = "msg-tag";
    if (opts.tagText) {
      tag.textContent = opts.tagText;
      if (opts.tagClass) tag.classList.add(opts.tagClass);
    } else {
      tag.textContent = role === "user" ? "你" : role;
    }
    wrap.appendChild(tag);

    const body = document.createElement("div");
    body.className = "msg-text";
    body.textContent = text;
    wrap.appendChild(body);

    if (opts.errors && opts.errors.length) {
      const errBox = document.createElement("div");
      errBox.className = "msg-errors";
      errBox.textContent = "调用失败详情：\n" + opts.errors.join("\n");
      wrap.appendChild(errBox);
    }

    // 有 sampleId 说明这条回复被记录为训练样本了（教师模型的在线回答），
    // 给个反馈入口，反馈会写回 training_samples.db，影响下次LoRA训练要不要用这条数据
    if (opts.sampleId) {
      const fb = document.createElement("div");
      fb.className = "msg-feedback";
      const up = document.createElement("button");
      up.textContent = "👍 有帮助";
      const down = document.createElement("button");
      down.textContent = "👎 不满意";
      const sendFeedback = async (rating, btn) => {
        up.disabled = true; down.disabled = true;
        try {
          await fetch("/api/feedback", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sample_id: opts.sampleId, rating }),
          });
          btn.textContent += "（已记录）";
        } catch (e) { btn.textContent += "（记录失败）"; }
      };
      up.addEventListener("click", () => sendFeedback(1, up));
      down.addEventListener("click", () => sendFeedback(-1, down));
      fb.appendChild(up);
      fb.appendChild(down);
      wrap.appendChild(fb);
    }

    chatLog.appendChild(wrap);
    chatLog.scrollTop = chatLog.scrollHeight;
    return wrap;
  }
  
  async function speak(text) {
	if (!ttsToggle.checked) return;
	try {
	  const res = await fetch('/api/tts_proxy', { 
			method: 'POST',
			headers: { "Content-Type": "application/json" }, // 必不可少
			body: JSON.stringify({ text }) 
		  });
	  const blob = await res.blob();
	  new Audio(URL.createObjectURL(blob)).play();
	} catch (e) { 
	  console.warn("AI TTS请求失败", e);
	}
  }

  

  // ---------------- 模型列表 ----------------
  async function loadModels() {
    try {
      const res = await fetch("/api/models");
      const data = await res.json();
      modelSelect.innerHTML = "";
      data.models.forEach((m) => {
        const opt = document.createElement("option");
        opt.value = m.id;
        opt.textContent = `${m.ready ? "✓" : "×"} ${m.label}`;
        opt.dataset.detail = m.detail || "";
        opt.dataset.ready = m.ready;
        modelSelect.appendChild(opt);
      });
      updateModelHint();
    } catch (e) {
      modelHint.textContent = "模型列表加载失败，检查后端是否启动";
    }
  }

  function updateModelHint() {
    const opt = modelSelect.options[modelSelect.selectedIndex];
    if (!opt) return;
    const ready = opt.dataset.ready === "true";
    modelHint.textContent = opt.dataset.detail
      ? (ready ? opt.dataset.detail : `⚠ ${opt.dataset.detail}`)
      : "";
  }
  modelSelect.addEventListener("change", updateModelHint);

  // ---------------- 状态面板 ----------------
  async function loadStatus() {
    statusBox.textContent = "刷新中…";
    try {
      const res = await fetch("/api/status");
      const data = await res.json();
      statusBox.textContent = data.status;
      const online = /已配置/.test(data.status);
      linkDot.className = "dot " + (online ? "ok" : "warn");
    } catch (e) {
      statusBox.textContent = "状态获取失败: " + e;
      linkDot.className = "dot warn";
    }
  }
  refreshStatus.addEventListener("click", loadStatus);

  // ---------------- 记忆 ----------------
  rememberBtn.addEventListener("click", async () => {
    const key = rememberKey.value.trim();
    const value = rememberValue.value.trim();
    if (!key || !value) return;
    rememberBtn.disabled = true;
    try {
      await fetch("/api/remember", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key, value }),
      });
      addMessage("system", `已记住: ${key} = ${value}`, { tagText: "system" });
      rememberKey.value = "";
      rememberValue.value = "";
    } finally {
      rememberBtn.disabled = false;
    }
  });

  function renderFinalResult(data) {
    if (data.error) {
      addMessage("assistant error", `出错了: ${data.error}`, { tagText: "error", tagClass: "source-degraded" });
      return;
    }
    const tagClass = data.degraded
      ? "source-degraded"
      : (data.source === "local_gguf" ? "source-local_gguf" : "source-online");
    const tagText = `${data.agent || ""}/${data.source || ""}${data.degraded ? " · 离线降级" : ""}`;
    addMessage("assistant", data.text, { tagText, tagClass, errors: data.errors, sampleId: data.sample_id });
    speak(data.text);
  }

  function renderConfirmCard(data) {
    const wrap = document.createElement("div");
    wrap.className = "msg assistant";

    const tag = document.createElement("div");
    tag.className = "msg-tag source-degraded";
    tag.textContent = `需要确认 · ${data.tool_name}`;
    wrap.appendChild(tag);

    const card = document.createElement("div");
    card.className = "confirm-card";
    card.innerHTML = `
      <div class="confirm-title">小K想执行一个操作</div>
      <div>${data.preview}</div>
      <div class="confirm-actions">
        <button class="confirm-btn approve">同意执行</button>
        <button class="confirm-btn deny">拒绝</button>
      </div>
    `;
    wrap.appendChild(card);
    chatLog.appendChild(wrap);
    chatLog.scrollTop = chatLog.scrollHeight;

    const approveBtn = card.querySelector(".approve");
    const denyBtn = card.querySelector(".deny");
    const decide = async (approve) => {
      approveBtn.disabled = true;
      denyBtn.disabled = true;
      try {
        const res = await fetch("/api/chat/confirm", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token: data.token, approve }),
        });
        const next = await res.json();
        if (next.needs_confirmation) {
          renderConfirmCard(next);
        } else {
          renderFinalResult(next);
        }
      } catch (e) {
        addMessage("assistant error", `确认请求失败: ${e}`, { tagText: "error", tagClass: "source-degraded" });
      }
    };
    approveBtn.addEventListener("click", () => decide(true));
    denyBtn.addEventListener("click", () => decide(false));
  }

  // ---------------- 发送消息 ----------------
  async function sendMessage(text) {
    if (!text.trim()) return;
    addMessage("user", text);
    inputBox.value = "";
    autoResize();
    sendBtn.disabled = true;

    const thinking = addMessage("assistant", "…", { tagText: "思考中" });

    try {
      const provider = modelSelect.value === "auto" ? null : modelSelect.value;
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, provider }),
      });
      const data = await res.json();
      thinking.remove();

      if (data.needs_confirmation) {
        renderConfirmCard(data);
      } else {
        renderFinalResult(data);
      }
    } catch (e) {
      thinking.remove();
      addMessage("assistant error", `网络请求失败: ${e}`, { tagText: "error", tagClass: "source-degraded" });
    } finally {
      sendBtn.disabled = false;
    }
  }

  composer.addEventListener("submit", (e) => {
    e.preventDefault();
    sendMessage(inputBox.value);
  });

  inputBox.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(inputBox.value);
    }
  });

  function autoResize() {
    inputBox.style.height = "auto";
    inputBox.style.height = Math.min(inputBox.scrollHeight, 140) + "px";
  }
  inputBox.addEventListener("input", autoResize);

  // ---------------- 语音输入 (Web Speech API) ----------------
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recognizer = null;
  let recording = false;

  if (SpeechRecognition) {
    recognizer = new SpeechRecognition();
    recognizer.lang = "zh-CN";
    recognizer.interimResults = false;
    recognizer.maxAlternatives = 1;

    recognizer.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      inputBox.value = (inputBox.value ? inputBox.value + " " : "") + transcript;
      autoResize();
    };
    recognizer.onend = () => {
      recording = false;
      micBtn.classList.remove("recording");
    };
    recognizer.onerror = () => {
      recording = false;
      micBtn.classList.remove("recording");
    };

    micBtn.addEventListener("click", () => {
      if (recording) {
        recognizer.stop();
        return;
      }
      try {
        recognizer.start();
        recording = true;
        micBtn.classList.add("recording");
      } catch (e) { /* 已经在录音时再次调用start会抛错，忽略 */ }
    });
  } else {
    micBtn.disabled = true;
    micBtn.title = "当前浏览器不支持语音识别（推荐用 Chrome / Edge，手机上用 Chrome）";
    micBtn.style.opacity = "0.4";
  }

  // ---------------- 手机端侧栏折叠 ----------------
  panelToggle.addEventListener("click", () => {
    sidePanel.classList.toggle("open");
  });
  document.addEventListener("click", (e) => {
    if (window.innerWidth > 820) return;
    if (sidePanel.classList.contains("open") &&
        !sidePanel.contains(e.target) &&
        e.target !== panelToggle) {
      sidePanel.classList.remove("open");
    }
  });

  // ---------------- 初始化 ----------------
  loadModels();
  loadStatus();
  loadSkills();
  inputBox.focus();
})();

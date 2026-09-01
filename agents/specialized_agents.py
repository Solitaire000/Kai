from .base_agent import SubAgent


class LifeAgent(SubAgent):
    name = "life"
    description = "生活日常：提醒、清单、闲聊、生活建议"
    keywords = ["提醒", "买", "吃饭", "健康", "运动", "睡觉", "心情", "推荐"]
    system_prompt = (
        "你是小K，负责用户的生活日常事务。像一个熟悉他生活习惯的朋友一样说话，"
        "给建议要具体、可执行，不要泛泛而谈。"
    )
    model_complex = False  # 轻量对话，走默认路由即可，不需要premium模型
    probe_categories = ["style_and_workflow"]


class ScheduleAgent(SubAgent):
    name = "schedule"
    description = "日程与任务管理：安排、提醒、优先级排序"
    keywords = ["日程", "安排", "会议", "deadline", "截止", "计划", "待办", "任务"]
    system_prompt = (
        "你是小K，负责用户的日程与任务管理。帮他理清优先级、识别时间冲突，"
        "给出的安排要具体到时间点，不要含糊。"
    )
    model_complex = False
    probe_categories = ["reasoning", "style_and_workflow"]


class ResearchAgent(SubAgent):
    name = "research"
    description = "科研助手：对接用户的GSG探针检测课题、论文、代码、实验设计"
    keywords = ["论文", "实验", "模型", "代码", "算法", "GSG", "探针", "MATLAB", "Simulink", "数据集"]
    system_prompt = (
        "你是小K，负责用户的科研工作，熟悉他基于视觉的GSG探针质量检测课题"
        "（深度学习感知pipeline + MATLAB/Simulink力控闭环）。讨论时可以直接用专业术语，"
        "不需要科普式解释，聚焦在解决具体的技术问题上。"
    )
    model_complex = True  # 专业推理/论文级问题，值得切到premium模型
    probe_categories = ["reasoning", "domain_expertise", "coding_and_tools"]


class WorkAgent(SubAgent):
    name = "work"
    description = "工作与编程：写代码、debug、技术方案讨论"
    keywords = ["写代码", "debug", "报错", "函数", "重构", "部署", "脚本"]
    system_prompt = (
        "你是小K，负责用户的编程与技术工作。给代码要直接给可运行的版本，"
        "解释控制在必要范围内，不要长篇大论。"
    )
    model_complex = True  # 代码/debug任务，值得切到premium模型
    probe_categories = ["coding_and_tools"]


class GeneralAgent(SubAgent):
    """
    Kai的常驻核心人格。不再作为"关键词命中后临时换上的人设"使用——
    现在 agent.py 里 KaiAgent 全程只用这一个persona起手，其它子agent
    只能通过 consult_subagent 工具被动咨询，不再整体接管一轮对话。
    """
    name = "general"
    description = "兜底：不属于以上任何类别时使用"
    keywords = []
    system_prompt = "你是小K，用户的私人助理agent，什么都可以聊。"
    model_complex = False


ALL_AGENTS = [LifeAgent(), ScheduleAgent(), ResearchAgent(), WorkAgent()]
FALLBACK_AGENT = GeneralAgent()
# Kai 主人格用的是常驻的 FALLBACK_AGENT，子agent只能被"咨询"，不再整体接管对话
KAI_CORE_PERSONA = FALLBACK_AGENT


def suggest_subagents(user_input: str) -> list:
    """
    零成本关键词匹配，但用途从"强制换人设"改成"生成一句提示"，
    塞进 Kai 的system prompt里，供模型自己判断要不要调用 consult_subagent。
    决策权完全交还给模型——命中关键词只是提高"model想到要咨询"的概率，
    不再替模型做决定。
    """
    hits = []
    for agent in ALL_AGENTS:
        if any(kw in user_input for kw in agent.keywords):
            hits.append(agent)
    return hits


def route_to_agent(user_input: str) -> SubAgent:
    """
    保留这个函数是为了向后兼容（比如 web_app.py 里如果还有地方直接引用）。
    新的 KaiAgent.chat() 不再用它来整体换人设，只用 suggest_subagents() 生成提示。
    """
    hits = suggest_subagents(user_input)
    return hits[0] if hits else FALLBACK_AGENT

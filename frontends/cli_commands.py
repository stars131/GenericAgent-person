import json
import os
import re
from dataclasses import dataclass

from ga import smart_format
try:
    from continue_cmd import handle_frontend_command, reset_conversation
except ImportError:
    from .continue_cmd import handle_frontend_command, reset_conversation


HELP_COMMANDS = (
    ("/help", "显示帮助"),
    ("/status", "查看状态"),
    ("/stop", "停止当前任务"),
    ("/new", "开启新对话并清空当前上下文"),
    ("/restore", "恢复上次对话历史"),
    ("/continue", "列出可恢复会话"),
    ("/continue [n]", "恢复第 n 个会话"),
    ("/llm", "查看当前模型列表"),
    ("/llm [n]", "切换到第 n 个模型"),
    ("/session.<key>=<value>", "设置当前 LLM session 参数"),
)


TELEGRAM_MENU_COMMANDS = (
    ("help", "显示帮助"),
    ("status", "查看状态"),
    ("stop", "停止当前任务"),
    ("new", "开启新对话并清空当前上下文"),
    ("restore", "恢复上次对话历史"),
    ("continue", "列出可恢复会话；/continue n 恢复第 n 个"),
    ("llm", "查看模型列表；/llm n 切换到指定模型"),
)


def build_help_text(commands=HELP_COMMANDS):
    return "📖 命令列表:\n" + "\n".join(f"{cmd} - {desc}" for cmd, desc in commands)


HELP_TEXT = build_help_text()


@dataclass
class CommandResult:
    handled: bool
    message: str | None = None
    query: str | None = None
    should_exit: bool = False


class SharedCommandHandler:
    def __init__(self, agent):
        self.agent = agent

    def handle(self, raw_query):
        text = (raw_query or "").strip()
        if not text.startswith("/"):
            return CommandResult(False, query=raw_query)
        parts = text.split()
        op = (parts[0] if parts else "").lower()
        if op == "/help":
            return CommandResult(True, HELP_TEXT)
        if op == "/stop":
            self.agent.abort()
            return CommandResult(True, "⏹️ 正在停止...")
        if op == "/status":
            return CommandResult(True, self._status())
        if op == "/llm":
            return CommandResult(True, self._llm(parts))
        if op == "/new":
            return CommandResult(True, reset_conversation(self.agent))
        if op == "/restore":
            return CommandResult(True, self._restore_latest())
        if op == "/continue":
            return CommandResult(True, handle_frontend_command(self.agent, text))
        if op == "/resume":
            return CommandResult(False, query=r'用re.findall(r"<history>\\n\[(?:USER\|Agent)\].*?</history>", content, re.DOTALL) 扫temp/model_responses/下时间最近的10个文件(除本PID)，取每文件最后一个匹配(注意JSON里换行是字面\\n)作为该会话内容，按mtime倒序，每个用一句话总结聊了什么让我选择；选定后再简单读该文件末尾作为聊天基础')
        if m := re.match(r"/session\.(\w+)=(.*)", text):
            return CommandResult(True, self._set_session(m.group(1), m.group(2)))
        return CommandResult(True, HELP_TEXT)

    def _status(self):
        llm = self.agent.get_llm_name() if getattr(self.agent, "llmclient", None) else "未配置"
        running = "🔴 运行中" if getattr(self.agent, "is_running", False) else "🟢 空闲"
        lines = [f"状态: {running}", f"LLM: [{self.agent.llm_no}] {llm}"]
        if root := getattr(self.agent, "project_root", ""):
            lines.append(f"Project: {root}")
        if mode := getattr(self.agent, "permission_mode", ""):
            lines.append(f"Permission: {mode}")
        if ctx := getattr(self.agent, "project_context", None):
            files = getattr(ctx, "files", []) or []
            lines.append(f"Context files: {len(files)}")
            lines.extend(f"  - {os.path.basename(str(p))}" for p in files[:5])
        lines.append(f"History: {len(getattr(self.agent, 'history', []))}")
        return "\n".join(lines)

    def _llm(self, parts):
        if not getattr(self.agent, "llmclient", None):
            return "❌ 当前没有可用的 LLM 配置"
        if len(parts) > 1:
            try:
                self.agent.next_llm(int(parts[1]))
                return f"✅ 已切换到 [{self.agent.llm_no}] {self.agent.get_llm_name()}"
            except Exception:
                return f"用法: /llm <0-{len(self.agent.list_llms()) - 1}>"
        lines = [f"{'→' if cur else ' '} [{i}] {name}" for i, name, cur in self.agent.list_llms()]
        return "LLMs:\n" + "\n".join(lines)

    def _set_session(self, key, value):
        vfile = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "temp", value)
        if os.path.isfile(vfile):
            value = open(vfile, encoding="utf-8").read().strip()
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            pass
        setattr(self.agent.llmclient.backend, key, value)
        return smart_format(f"✅ session.{key} = {repr(value)}", max_str_len=500)

    def _restore_latest(self):
        try:
            from chatapp_common import format_restore
            restored_info, err = format_restore()
            if err:
                return err
            restored, fname, count = restored_info
            self.agent.abort()
            self.agent.history.extend(restored)
            return f"✅ 已恢复 {count} 轮对话\n来源: {fname}\n(仅恢复上下文，请输入新问题继续)"
        except Exception as e:
            return f"❌ 恢复失败: {e}"

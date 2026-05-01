# 配置文件层级与覆盖规则

GenericAgent 启动时会从三处加载配置，按下列顺序合并：

1. **`mykey.py`**（必需）
   - 由用户从 `mykey_template_minimal.py` 或 `mykey_template.py` 复制而来。
   - 这是配置的"基础层"，适合手工维护。

2. **`mykey_local_override.py`**（可选，自动生成）
   - 由 `python launch.pyw --qt`（Qt launcher）的"API 配置"面板写入。
   - 加载顺序在 `mykey.py` 之后，**同名变量会覆盖** `mykey.py` 的值。
   - 文件顶部带有警告："Edit through the launcher UI; manual changes may be overwritten."

3. **`mykey.json`**（兜底，仅当 `mykey.py` 不存在时使用）
   - 适合容器化部署或不方便维护 .py 配置的环境。

合并逻辑见 `llmcore.py:21-39` 的 `_load_mykeys()`。

## 变量命名决定 Session 类型

`agentmain.py` 启动时只扫描变量名包含 `api` / `config` / `cookie` 的条目，并按变量名里的关键字决定使用哪种 Session：

| 变量名包含                     | Session 类             | 适用场景                       |
| ------------------------------ | ---------------------- | ------------------------------ |
| `native` + `claude`            | `NativeClaudeSession`  | Claude 原生工具协议（推荐）    |
| `native` + `oai`               | `NativeOAISession`     | OpenAI 原生工具协议（推荐）    |
| `claude`（不含 `native`）      | `ClaudeSession`        | 文本协议（deprecated）         |
| `oai`（不含 `native`）         | `LLMSession`           | 文本协议（deprecated）         |
| `mixin`                        | `MixinSession`         | 多渠道故障转移                 |

> 改一个变量名就会切换协议——这是设计上的约定，请勿随意改名。

## 配置入口选择

| 你想做的事                                  | 推荐路径                                 |
| ------------------------------------------- | ---------------------------------------- |
| 第一次配置一个 API key                      | `cp mykey_template_minimal.py mykey.py`  |
| 接入多渠道、思考预算、CC 透传等高级配置     | 参考 `mykey_template.py`                 |
| 在 GUI 里管理多个 API 凭证（增删改查）      | `python launch.pyw --qt` 的"API 配置"面板 |
| 想编辑 Qt launcher 写入的内容               | 通过 GUI 改；手动改 `mykey_local_override.py` 会被下次写入覆盖（已自动备份到 `temp/mykey_local_override.py.bak.*`） |
| 想保存多套配置档随时一键切换（cc-switch 风格） | Qt launcher 的"Profile"栏，详见下文 |

## Profiles —— 多档位配置切换

Qt launcher 顶部的"Profile"栏类似 cc-switch：

- 一个 **profile** 是一组**同时启用的 configs**（不是 cc-switch 的"档位互斥"语义；GA 允许多个 LLM 同时挂载，便于 mixin 故障转移）。
- 切换激活 profile 会重新生成 `mykey_local_override.py`，**只写入该 profile 选中的 configs**；其他 configs 仍保存在 `temp/launcher_api_configs.json` 中不会丢。
- 没有任何 profile 激活时，所有 configs 都会被写入（向后兼容旧用户）。
- 数据存放：`temp/launcher_profiles.json`，结构 `{"active": "name", "profiles": {"name": ["config_name_1", ...]}}`。

**典型用法：**

| 场景 | 操作 |
| ---- | ---- |
| 公司号 vs 个人号 | 建两个 profile，各放各的 key，切换 profile 即换号 |
| 在线/离线模型 | profile A = 远程 OpenAI 中继，profile B = 本地 vLLM，按网络情况切 |
| 高质量 vs 高速度 | profile A = Opus + 高 reasoning_effort，profile B = Haiku + low |
| 故障转移测试 | profile = mixin + 多 native，挂载多渠道便于 mixin 自动切换 |

**API（如果你想脚本化）：**

`launcher/api_config.py` 暴露了：`load_profiles` / `save_profiles` / `set_active_profile(base_dir, name|None)` / `upsert_profile(base_dir, name, [member_names])` / `rename_profile` / `delete_profile` / `apply_active_profile(base_dir)`。

## 飞书命令

`frontends/fs_commands.py` 提供一组斜杠命令，飞书侧直接发就生效，**不走 LLM**，响应即时。

| 命令 | 用途 |
| --- | --- |
| `/sop <query>` | 在 Sophub 检索别人分享的 SOP（top 5） |
| `/sop read <id>` | 拉取完整 SOP；超过 3KB 落盘成 `.md` 文件发送 |
| `/sop stats` | Sophub 库统计 |
| `/screenshot [N]` | 截屏发回；`N` 为显示器序号（0=全屏，1/2…=单屏）。需 `pip install mss`（推荐）或 `pip install pillow` |
| `/run <cmd>` | 执行 shell 命令，30s 超时，stdout+stderr 截断到 4000 字符 |
| `/clip` | 读剪贴板 |
| `/clip <text>` | 写剪贴板 |
| `/open <path\|url>` | 用默认程序打开文件或 URL |

**安全门禁**：当 `fs_allowed_users = ['*']`（公开访问）时，**写类命令** `/run` `/clip <text>` `/open` 自动禁用，防止陌生人远程操控。`/sop /screenshot /clip`（读）始终可用。

## SOP 检索作为 GA 工具

除飞书命令外，**LLM 在 reasoning 时也能直接调** `sop_search` / `sop_read` 两个工具（在 `assets/tools_schema.json` 中注册）。当 GA 遇到陌生任务时，工具描述会引导它先去 Sophub 看有没有现成参考，避免从零摸索。

工具实现位于 `tools/sop_tools.py`，复用 `memory/skill_search/` 的 Sophub 客户端。设置 `SOPHUB_API_KEY` 或通过 `python -m skill_search --register-agent <name>` 注册一个匿名 agent，即可获得读权限（写权限需要邮箱认证）。

## 安全说明

- `mykey.py` 与 `mykey_local_override.py` 已写入 `.gitignore`，不会被提交。
- POSIX 系统下 `mykey_local_override.py` 写入时会被设为 `0o600`（仅当前用户可读写）。Windows 上 `os.chmod` 仅影响 read-only 位，请自行注意权限。
- 强烈建议不要把 `mykey.py` 拷贝到协作目录、共享硬盘或随项目打 zip 分发。

## 启动器分工

| 启动器                              | 用途                                               |
| ----------------------------------- | -------------------------------------------------- |
| `python launch.pyw`（默认推荐）     | Qt 主窗口：会话 / Bots / API 配置 / 设置 四个标签页 |
| `python launch.pyw --legacy-shell`  | 旧的 webview + Streamlit 默认会话流（向后兼容）    |
| `python agentmain.py`               | 纯 CLI / REPL 模式（headless / SSH）               |
| `python frontends/qtapp.py`         | 单文件 Qt 聊天面板（独立聊天窗，不带 launcher）    |

CLI flag（`--feishu` `--tg` `--qq` `--wecom` `--dingtalk` `--wechat` `--sched`/`--no-sched` `--llm_no`）会写入 `temp/launcher_options.json`，启动后由 Qt launcher 自动读取并启用。下次不带 flag 运行也保持启用，直到通过设置标签页或 `--no-feishu` 之类的反向 flag 关闭。

其它 `hub.pyw` / `start_*.cmd` / `frontends/stapp2.py` / `frontends/desktop_pet.pyw` 已弃用，仅保留兼容性，新用户请勿使用。

## Qt 主窗口 4 标签页

- **会话**：左列项目列表 + 右列项目详情；按钮含新建 / 启动 / 停止 / 打开 Streamlit / 激活 / 重命名 / 置顶 / 删除。多会话同时跑互不干扰。
- **Bots**：6 行表格，列出每个聊天平台 bot 的"配置 ✅/❌/⚠️ SDK 未装"、"状态 🟢 本进程 / 🟡 外部进程 / ⚪ 已停"，每行 [启动] [停止] [日志] 三个按钮；状态每 3 秒刷新。
- **API 配置**：参见上文「Profiles —— 多档位配置切换」。
- **设置**：全局默认 LLM 索引、权限模式、项目根、context/autonomous 默认开关、L4 调度器开关。修改后点保存生效；运行中的会话需重启才能采用新默认值。

菜单栏含 文件（新建会话 / 退出）、视图（切换标签 / 立即刷新）、帮助（配置文档 / 关于）。状态栏显示运行中会话数、Bot 数、L4 调度器状态、版本号。

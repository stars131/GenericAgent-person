# GenericAgent — minimal mykey template
#
# 三步上手：
#   1) 把本文件复制为 mykey.py
#   2) 填入下面的 apikey 与 apibase
#   3) python launch.pyw   或   python agentmain.py
#
# 进阶配置（Claude / Kimi / MiniMax / CRS / CC-relay / OpenRouter / 多渠道
# 故障转移 / thinking / reasoning_effort 等）请参考 mykey_template.py。
# 配置优先级与多文件覆盖规则参见 docs/CONFIG.md。

native_oai_config = {
    'name': 'default',
    'apikey': 'sk-YOUR-KEY',
    'apibase': 'https://api.openai.com/v1',
    'model': 'gpt-5.4',
}

# 可选：聊天平台接入。需要再取消注释并填值。
# tg_bot_token = '...'
# tg_allowed_users = [...]
# fs_app_id = 'cli_...'
# fs_app_secret = '...'
# fs_allowed_users = ['ou_...']

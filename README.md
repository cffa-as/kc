# KC 游戏机器人

基于 WebSocket 的游戏房间机器人，支持排行榜查询、AI总结、房间管理等功能。

## 项目结构

```
kc/
├── main.py                 # 入口文件
├── config.py               # 配置管理模块
├── ai/
│   ├── __init__.py
│   └── summarizer.py       # AI 通义千问 API 封装
├── rank/
│   ├── __init__.py
│   └── query.py            # 道具排行榜查询
├── bot/
│   ├── __init__.py
│   ├── core.py             # Bot 核心类
│   ├── connection.py       # 连接管理（预留）
│   └── handlers/
│       ├── __init__.py
│       ├── dispatcher.py   # 消息分发器
│       ├── ai.py           # AI 相关处理
│       ├── rank.py         # 排行榜处理
│       ├── room.py         # 房间查询处理
│       └── crack.py        # 破解和用户处理
├── utils/
│   └── __init__.py         # 通用工具（Logger、Censor 等）
└── game_bot.py             # 原始单文件（已废弃）
```

## 快速开始

```bash
# 安装依赖
pip install websockets requests

# 运行机器人
python main.py
```

## 命令列表

| 命令 | 功能 |
|------|------|
| `菜单` | 显示功能列表 |
| `查周榜` / `查月榜` | 查询道具排行榜 |
| `查周榜道具名` / `查月榜道具名` | 查询指定道具排行榜 |
| `总结喇叭` | AI 总结喇叭消息（默认5分钟） |
| `总结喇叭10` | 总结最近10分钟的喇叭 |
| `喇叭提问问题` | 根据喇叭消息回答问题 |
| `AI问题` | AI 直接问答 |
| `查房房间号` | 查询房间玩家列表 |
| `破解房间号` | 破解房间密码 |
| `固定房间房间号` | 设置固定房间 |
| `取消固定` | 取消固定房间 |
| `开启明星提醒` / `关闭明星提醒` | 整点明星提醒 |
| `聊天记录N` | 查看最近N条聊天记录 |
| `总结房间N` | AI 总结最近N分钟的房间消息 |
| `分析动态用户SID` | 查询用户信息 + MBTI预测 |
| `锐评动态用户SID` | AI生成用户吐槽（毒舌版） |
| `关注用户SID` | 关注用户 |
| `取关用户SID` | 取关用户 |
| `#上树` | 上树 |
| `#换位号` | 换到指定位置 |

## 配置文件

| 文件 | 说明 |
|------|------|
| `config.json` | 机器人配置（固定房间、跟随设置等） |
| `敏感词.json` | 敏感词过滤列表 |
| `道具完整数据.json` | 道具数据缓存 |
| `bot.log` | 运行日志 |

### config.json 示例

```json
{
  "fixed_room": "3045",
  "star_reminder": false,
  "allowed_users": [],
  "owners": ["123456789"]
}
```

## 模块说明

### ai/summarizer.py
封装通义千问 API，提供喇叭总结、问答、房间总结等功能。

### rank/query.py
处理道具排行榜查询，支持周榜/月榜、单道具/全道具查询。

### bot/core.py
Bot 核心类，管理连接、会话、消息处理循环。

### bot/handlers/
- `dispatcher.py` - 消息分发器，根据正则匹配路由到对应处理器
- `ai.py` - AI 相关处理（日志读取、总结、问答）
- `rank.py` - 排行榜查询处理
- `room.py` - 房间查询、换位处理
- `crack.py` - 破解房间、用户分析/关注

### utils/
通用工具模块：
- `Logger` - 日志记录
- `Censor` - 敏感词过滤
- `parse_room_sync` - 解析房间同步消息
- `split_message` - 消息分片

## 开发指南

### 添加新命令

在 `bot/handlers/dispatcher.py` 中注册新处理器：

```python
# 注册命令
self.add_handler(r'^新命令(\d+)', self._handle_new_command)

# 实现处理器
async def _handle_new_command(self, match):
    param = match.group(1)
    # 处理逻辑
```

### 添加新的处理器类

1. 在 `bot/handlers/` 创建新文件
2. 在 `bot/handlers/__init__.py` 导出
3. 在 `bot/core.py` 初始化并添加到 `self.handlers`

## 注意事项

1. 原始 `game_bot.py` 保留作为参考，新代码使用 `main.py` 入口
2. 日志文件会无限增长，可定期清理或配置日志轮转
3. AI API 有调用频率限制，注意防刷

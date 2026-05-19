"""游戏机器人入口"""

import asyncio
import os
import sys

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot import GameBot


async def main():
    """主函数"""
    servers = GameBot.SERVERS

    bot = None
    connected = False

    # 登录参数
    login_token = "+NemHgNs1Fr0wV8slM6jSbBDDmmWEV6H"
    login_device = "html5:1461"
    login_p = "VzG6JI4TXVgkroND+wq1kA=="

    # 尝试连接每个服务器
    for ws_url, http_url in servers:
        print(f"尝试连接: {ws_url}")
        bot = GameBot(ws_url, http_url)
        bot._open_log()

        # 显示配置
        fixed_room = bot.get_fixed_room()
        if fixed_room:
            print(f"固定房间: {fixed_room}")

        auto_follow_sid = bot.get_auto_follow_sid()
        if auto_follow_sid:
            print(f"自动跟随: sid={auto_follow_sid}, userId={bot.get_auto_follow_user_id()}")

        if await bot.connect():
            print(f"成功连接到: {ws_url}")
            connected = True
            await bot.login(login_token, login_device, login_p)
            await bot.run()
            break
        else:
            print(f"连接失败: {ws_url}")
            bot.close_log()
            bot = None

    if not connected:
        print("所有服务器连接失败")

    if bot:
        bot.close_log()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n已停止")

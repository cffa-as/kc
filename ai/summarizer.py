"""AI模块 - DeepSeek API封装"""

import os
from openai import OpenAI


class AISummarizer:
    """AI总结工具 - 基于DeepSeek V4 Flash"""

    SYSTEM_PROMPTS = {
        "喇叭总结": "你是一个游戏喇叭消息总结助手。请只根据提供的喇叭消息内容进行总结，不要猜测或编造任何信息。重要提示：1.房间号是4位数（如1001、2008、3005等），不是13172这样的数字。如果消息中没有明确提到房间号，不要猜测。2.明星/mx指的是明星大乱斗玩法。回复格式要求：每个要点用分号+换行分隔，不要使用JSON格式，不要使用markdown格式。",
        "喇叭问答": "你是一个游戏喇叭助手。请根据提供的喇叭消息回答玩家的问题，只回答消息中确实存在的信息，不要猜测或编造。房间号是4位数（如1001、2008等）。重要：1.不要使用markdown格式 2.用分号+换行分隔多个信息 3.引用消息时保留玩家原话 4.明星/mx指的是明星大乱斗玩法。",
        "房间总结": "你是一个游戏房间消息总结助手。请只根据提供的内容进行总结，不要猜测或编造。重要提示：明星/mx指的是明星大乱斗玩法。回复格式要求：每个要点用分号+换行分隔，不要使用JSON格式，不要使用markdown格式。",
        "通用问答": "你是一个友好的助手。请直接回答问题，回答简洁明了。重要提示：1.明星/mx指的是明星大乱斗玩法，会在1-10号明星中出一个结果，可以预测1-3个数字，1-5号概率较高但6-10也可能出，预测时可以运用古风、网络用语、押韵等多种风格，让预测更有趣味性。不要使用markdown格式，用分号+换行分隔多个信息。"
    }

    def __init__(self, api_key: str, base_url: str, model_name: str):
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )
        self.model_name = model_name

    def _post(self, system_key: str, user_content: str) -> str:
        """发送请求到AI API"""
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPTS.get(system_key, self.SYSTEM_PROMPTS["通用问答"])},
                    {"role": "user", "content": user_content}
                ],
                max_tokens=800,
                temperature=0.7
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"调用AI失败: {e}"

    def _format_messages(self, messages: list, formatter: callable) -> str:
        """统一格式化消息列表"""
        msg_texts = [formatter(msg) for msg in messages]
        return "\n".join(msg_texts)

    def _speaker_formatter(self, msg: dict) -> str:
        """喇叭消息格式化"""
        return f"{msg.get('userName', '未知玩家')}：{msg.get('msg', '')}"

    def _room_formatter(self, msg: dict) -> str:
        """房间消息格式化"""
        user_id = msg.get('userId', '')
        uid_str = f"[{user_id}]" if user_id else ""
        return f"{msg.get('site', '?')}{uid_str}{msg.get('userName', '未知玩家')}：{msg.get('msg', '')}"

    def summarize(self, messages: list, minutes: int = 5) -> str:
        """总结喇叭消息"""
        if not messages:
            return f"最近{minutes}分钟暂无喇叭消息"

        prompt = f"请总结以下游戏喇叭消息（每个消息格式为：玩家名：消息内容）：\n"
        prompt += self._format_messages(messages, self._speaker_formatter)
        prompt += "\n\n请用简洁的中文总结这些喇叭的主要内容。"
        return self._post("喇叭总结", prompt)

    def answer_question(self, messages: list, question: str, minutes: int = 60) -> str:
        """根据喇叭消息回答问题"""
        if not messages:
            return f"最近{minutes}分钟暂无喇叭消息，无法回答"

        prompt = f"以下是最近{minutes}分钟的游戏喇叭消息：\n"
        prompt += self._format_messages(messages, self._speaker_formatter)
        prompt += f"\n\n请根据以上喇叭消息回答问题：{question}\n\n"
        prompt += "要求：1. 只根据消息内容回答，不要猜测 2. 如果没有相关信息，说明没有 3. 引用消息时保留原内容 4. 用分号+换行分隔多个信息"
        return self._post("喇叭问答", prompt)

    def summarize_room_messages(self, messages: list, minutes: int = 5) -> str:
        """总结房间消息"""
        if not messages:
            return f"最近{minutes}分钟暂无消息"

        prompt = f"请总结以下房间消息（每个消息格式为：玩家名：消息内容）：\n"
        prompt += self._format_messages(messages, self._room_formatter)
        prompt += "\n\n请用简洁的中文总结这些消息的主要内容。"
        return self._post("房间总结", prompt)

    def answer_room_question(self, messages: list, question: str, count: int = 100) -> str:
        """根据房间消息回答问题"""
        if not messages:
            return f"暂无聊天记录，无法回答"

        prompt = f"以下是最近{count}条房间消息：\n"
        prompt += self._format_messages(messages, self._room_formatter)
        prompt += f"\n\n请根据以上房间消息回答问题：{question}\n\n"
        prompt += "要求：1. 只根据消息内容回答，不要猜测 2. 如果没有相关信息，说明没有 3. 用分号+换行分隔多个信息"
        return self._post("房间总结", prompt)

    def direct_answer(self, question: str) -> str:
        """直接回答问题"""
        return self._post("通用问答", question)

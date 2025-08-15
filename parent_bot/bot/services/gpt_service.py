import os
from typing import List, Dict

import openai
from dotenv import load_dotenv

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY", "")


class MemoryStore:
    """Простая оперативная память на уровне процесса: хранит историю на пользователя."""
    def __init__(self, max_messages: int = 20):
        self.max_messages = max_messages
        self.user_to_messages: Dict[int, List[dict]] = {}

    def append(self, user_id: int, role: str, content: str) -> List[dict]:
        history = self.user_to_messages.setdefault(user_id, [])
        history.append({"role": role, "content": content})
        # храним только последние N
        if len(history) > self.max_messages:
            history[:] = history[-self.max_messages :]
        return history

    def get(self, user_id: int) -> List[dict]:
        return list(self.user_to_messages.get(user_id, []))

    def clear(self, user_id: int) -> None:
        self.user_to_messages.pop(user_id, None)


memory_store = MemoryStore(max_messages=20)


async def chat_with_gpt(user_id: int, system_prompt: str, user_message: str) -> str:
    if not openai.api_key:
        raise RuntimeError("OPENAI_API_KEY is empty")

    # собрать историю
    history = memory_store.get(user_id)
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    resp = await openai.ChatCompletion.acreate(
        model="gpt-4o",
        messages=messages,
        temperature=0.3,
    )
    answer = resp.choices[0].message.content.strip()

    # дополняем память
    memory_store.append(user_id, "user", user_message)
    memory_store.append(user_id, "assistant", answer)
    return answer



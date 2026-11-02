"""Provider adapters. The agent talks to one tiny interface; history is provider-neutral:

  {"role": "user", "content": str}
  {"role": "assistant", "content": str, "tool_calls": [{"id", "name", "args"}]}
  {"role": "tool", "tool_call_id": str, "name": str, "content": str}
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class Turn:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLM:
    def complete(self, system: str, history: list[dict], tools: list[dict]) -> Turn:  # pragma: no cover
        raise NotImplementedError


class OpenAILLM(LLM):
    def __init__(self, model: str | None = None):
        from openai import OpenAI

        self.client = OpenAI()
        self.model = model or os.getenv("LLM_MODEL") or "gpt-4o-mini"

    @staticmethod
    def _messages(system: str, history: list[dict]) -> list[dict]:
        msgs = [{"role": "system", "content": system}]
        for m in history:
            if m["role"] == "assistant" and m.get("tool_calls"):
                msgs.append({"role": "assistant", "content": m.get("content") or None, "tool_calls": [
                    {"id": c["id"], "type": "function",
                     "function": {"name": c["name"], "arguments": json.dumps(c["args"], ensure_ascii=False)}}
                    for c in m["tool_calls"]]})
            elif m["role"] == "tool":
                msgs.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
            else:
                msgs.append({"role": m["role"], "content": m["content"]})
        return msgs

    def complete(self, system, history, tools):
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=self._messages(system, history),
            tools=[{"type": "function", "function": t} for t in tools],
            temperature=0.3,
        )
        msg = resp.choices[0].message
        calls = []
        for c in msg.tool_calls or []:
            try:
                args = json.loads(c.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(c.id, c.function.name, args))
        return Turn(msg.content or "", calls)


class AnthropicLLM(LLM):
    def __init__(self, model: str | None = None):
        import anthropic

        self.client = anthropic.Anthropic()
        self.model = model or os.getenv("LLM_MODEL") or "claude-haiku-4-5"

    @staticmethod
    def _messages(history: list[dict]) -> list[dict]:
        msgs: list[dict] = []
        for m in history:
            if m["role"] == "tool":
                block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
                if msgs and msgs[-1]["role"] == "user" and isinstance(msgs[-1]["content"], list):
                    msgs[-1]["content"].append(block)
                else:
                    msgs.append({"role": "user", "content": [block]})
            elif m["role"] == "assistant":
                blocks = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for c in m.get("tool_calls", []):
                    blocks.append({"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["args"]})
                msgs.append({"role": "assistant", "content": blocks})
            else:
                msgs.append({"role": "user", "content": m["content"]})
        return msgs

    def complete(self, system, history, tools):
        resp = self.client.messages.create(
            model=self.model, max_tokens=1024, system=system, temperature=0.3,
            messages=self._messages(history),
            tools=[{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        calls = [ToolCall(b.id, b.name, dict(b.input)) for b in resp.content if b.type == "tool_use"]
        return Turn(text, calls)


class FakeLLM(LLM):
    """Scripted LLM for offline tests: a list of Turns returned in order."""

    def __init__(self, turns: list[Turn]):
        self.turns = list(turns)
        self.seen: list[list[dict]] = []

    def complete(self, system, history, tools):
        self.seen.append(json.loads(json.dumps(history)))
        return self.turns.pop(0)


def make_llm() -> LLM:
    provider = (os.getenv("LLM_PROVIDER") or "").lower()
    if not provider:
        provider = "anthropic" if os.getenv("ANTHROPIC_API_KEY") else "openai"
    if provider == "anthropic":
        return AnthropicLLM()
    if provider == "openai":
        return OpenAILLM()
    raise SystemExit(f"LLM_PROVIDER inválido: {provider} (use openai ou anthropic)")

"""The agent loop: model <-> tools until the model answers in plain text."""
from __future__ import annotations

import json

from . import session as sessions
from .llm import LLM
from .prompts import system_prompt
from .tools import TOOL_SPECS, ToolBox

MAX_TOOL_ROUNDS = 6
MAX_USER_CHARS = 2000
MAX_HISTORY = 40  # messages sent to the model; older ones are dropped (customer state is kept separately)
FALLBACK = "Desculpa, tive um problema aqui para te responder. Pode tentar de novo ou falar com a gente no WhatsApp?"


class Agent:
    def __init__(self, llm: LLM, session_id: str = "default", toolbox: ToolBox | None = None,
                 persist: bool = True, sessions_dir=None):
        self.llm = llm
        self.session_id = session_id
        self.persist = persist
        self.sessions_dir = sessions_dir
        data = sessions.load(session_id, sessions_dir) if persist else {"history": [], "state": {}}
        self.history: list[dict] = data["history"]
        self.tools = toolbox or ToolBox(state=data["state"])
        self.trace: list[dict] = []  # tool calls of the last turn, for transcripts/debugging

    def _window(self) -> list[dict]:
        """Last MAX_HISTORY messages, trimmed to start at a user message so tool-call pairs stay intact.
        If the tail has no user message (one very long tool loop), start at the latest user message."""
        start = max(0, len(self.history) - MAX_HISTORY)
        for i in range(start, len(self.history)):
            if self.history[i]["role"] == "user":
                return self.history[i:]
        for i in range(len(self.history) - 1, -1, -1):
            if self.history[i]["role"] == "user":
                return self.history[i:]
        return list(self.history)

    def send(self, user_text: str) -> str:
        self.trace = []
        self.history.append({"role": "user", "content": user_text[:MAX_USER_CHARS]})
        reply = FALLBACK
        try:
            for _ in range(MAX_TOOL_ROUNDS):
                turn = self.llm.complete(system_prompt(), self._window(), TOOL_SPECS)
                if not turn.tool_calls:
                    reply = turn.text.strip() or FALLBACK
                    self.history.append({"role": "assistant", "content": reply})
                    break
                self.history.append({"role": "assistant", "content": turn.text,
                                     "tool_calls": [{"id": c.id, "name": c.name, "args": c.args} for c in turn.tool_calls]})
                for c in turn.tool_calls:
                    result = self.tools.call(c.name, c.args)
                    self.trace.append({"tool": c.name, "args": c.args, "result": result})
                    self.history.append({"role": "tool", "tool_call_id": c.id, "name": c.name,
                                         "content": json.dumps(result, ensure_ascii=False)})
            else:
                self.history.append({"role": "assistant", "content": FALLBACK})
        except Exception as e:  # network/API errors must not kill the chat loop
            self.history.append({"role": "assistant", "content": FALLBACK})
            self.trace.append({"error": f"{type(e).__name__}: {e}"})
        if self.persist:
            sessions.save(self.session_id, {"history": self.history, "state": self.tools.state}, self.sessions_dir)
        return reply

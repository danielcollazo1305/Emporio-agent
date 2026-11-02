import json

from emporio_agent.agent import FALLBACK, Agent
from emporio_agent.llm import AnthropicLLM, FakeLLM, OpenAILLM, ToolCall, Turn


def test_tool_loop_executes_tool_and_returns_text(tmp_path):
    llm = FakeLLM([
        Turn(tool_calls=[ToolCall("c1", "search_products", {"query": "Takamine GD20"})]),
        Turn(text="O Takamine GD20 sai por R$ 2.199,00."),
    ])
    agent = Agent(llm, "t1", sessions_dir=tmp_path)
    assert "2.199" in agent.send("quanto custa o Takamine GD20?")
    # the model must have seen the tool result on its second call
    assert any(m["role"] == "tool" and "2.199,00" in m["content"] for m in llm.seen[1])


def test_session_persists_verification_state(tmp_path):
    llm = FakeLLM([
        Turn(tool_calls=[ToolCall("c1", "verify_customer", {"email_or_phone": "lucas.mendes@jmail.com"})]),
        Turn(text="Oi Lucas!"),
        Turn(tool_calls=[ToolCall("c2", "get_order_status", {"order_id": 4})]),
        Turn(text="Seu pedido foi entregue."),
    ])
    a = Agent(llm, "t2", sessions_dir=tmp_path)
    a.send("meu email é lucas.mendes@jmail.com")
    b = Agent(llm, "t2", sessions_dir=tmp_path)  # new process, same session
    b.send("status do pedido 4?")
    assert b.trace[0]["result"]["order_id"] == 4


def test_endless_tool_loop_is_capped(tmp_path):
    llm = FakeLLM([Turn(tool_calls=[ToolCall(f"c{i}", "get_store_hours", {})]) for i in range(20)])
    assert Agent(llm, "t3", sessions_dir=tmp_path).send("oi") == FALLBACK


def test_llm_failure_returns_fallback(tmp_path):
    class Boom(FakeLLM):
        def complete(self, *a, **k):
            raise RuntimeError("network down")

    a = Agent(Boom([]), "t4", sessions_dir=tmp_path)
    assert a.send("oi") == FALLBACK


def test_history_window_never_starts_on_tool_message(tmp_path):
    a = Agent(FakeLLM([]), "t5", persist=False)
    a.history = [{"role": "user", "content": "x"}] + [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "name": "n", "args": {}}]},
        {"role": "tool", "tool_call_id": "1", "name": "n", "content": "{}"},
    ] * 30
    w = a._window()
    assert w and w[0]["role"] == "user"


def test_openai_and_anthropic_message_conversion():
    history = [
        {"role": "user", "content": "oi"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "a", "name": "get_store_hours", "args": {}},
                                                           {"id": "b", "name": "get_store_hours", "args": {}}]},
        {"role": "tool", "tool_call_id": "a", "name": "get_store_hours", "content": "{}"},
        {"role": "tool", "tool_call_id": "b", "name": "get_store_hours", "content": "{}"},
    ]
    oa = OpenAILLM._messages("sys", history)
    assert oa[0]["role"] == "system" and oa[2]["tool_calls"][1]["id"] == "b" and oa[3]["role"] == "tool"
    an = AnthropicLLM._messages(history)
    assert len(an[-1]["content"]) == 2  # both tool results grouped in one user message
    json.dumps(an)

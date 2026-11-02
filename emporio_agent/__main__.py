"""CLI chat: `python -m emporio_agent [--session NAME] [--debug]`."""
from __future__ import annotations

import argparse

from dotenv import load_dotenv

from .agent import Agent
from .config import ROOT
from .llm import make_llm


def main() -> None:
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser(description="Atendente virtual da Empório da Música")
    ap.add_argument("--session", default="default", help="nome da sessão (a conversa é salva em sessions/)")
    ap.add_argument("--debug", action="store_true", help="mostra as ferramentas chamadas")
    args = ap.parse_args()
    agent = Agent(make_llm(), session_id=args.session)
    print("Empório da Música — atendimento (digite 'sair' para encerrar)\n")
    if not agent.history:
        print("Jimi: Opa! Aqui é o Jimi, da Empório da Música. Como posso te ajudar hoje?\n")
    while True:
        try:
            text = input("Você: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if text.lower() in {"sair", "exit", "quit"}:
            break
        if not text:
            continue
        reply = agent.send(text)
        if args.debug:
            for t in agent.trace:
                print(f"  [tool] {t.get('tool', 'error')} {t.get('args', t.get('error'))}")
        print(f"\nLeo: {reply}\n")


if __name__ == "__main__":
    main()


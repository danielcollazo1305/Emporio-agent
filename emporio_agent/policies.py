"""Policy retrieval over the store manual.

The manual is 8 pages, so a vector database would be over-engineering. The markdown
transcription is split into sections (### level, or ## when it has no children) and ranked
with accent-insensitive keyword overlap plus a small synonym table. Each section can carry a
"conflict note": places where the manual contradicts itself, which the agent must surface
instead of silently picking a side.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import DATA_DIR
from .text import tokens

SYNONYMS = {
    "devolver": "devolucao arrependimento reembolso",
    "devolucao": "arrependimento reembolso trocas",
    "arrepender": "arrependimento devolucao reembolso",
    "arrependimento": "devolucao reembolso",
    "arrependi": "arrependimento devolucao reembolso",
    "desistir": "arrependimento devolucao",
    "trocar": "troca trocas defeito preferencia",
    "troca": "trocas defeito preferencia",
    "defeito": "trocas defeito garantia",
    "quebrou": "defeito garantia trocas",
    "estragou": "defeito garantia trocas",
    "reembolso": "devolucao arrependimento",
    "parcelar": "parcelamento credito parcela",
    "parcela": "parcelamento credito",
    "parcelas": "parcelamento credito",
    "pagar": "pagamento pix cartao boleto",
    "pagamento": "pix cartao boleto credito",
    "cartao": "credito debito parcelamento",
    "frete": "entrega entregas",
    "entregar": "entrega entregas frete",
    "envio": "entrega entregas frete correios",
    "rastrear": "rastreamento codigo",
    "rastreio": "rastreamento codigo",
    "endereco": "empresa loja horario",
    "onde": "endereco empresa loja",
    "localizacao": "endereco empresa loja",
    "telefone": "whatsapp contato empresa",
    "whatsapp": "telefone contato atendimento",
    "horario": "funcionamento aberto fechado",
    "abre": "horario funcionamento",
    "fecha": "horario funcionamento",
    "aberto": "horario funcionamento",
    "promocao": "promocoes desconto cumulativo",
    "desconto": "promocao promocoes pix",
    "garantia": "defeito fabricante",
    "dados": "privacidade lgpd",
    "lgpd": "privacidade dados",
    "excluir": "privacidade dados exclusao",
    "acessorio": "escopo cordas palhetas cabos pedais amplificadores cases",
    "corda": "escopo acessorios",
    "palheta": "escopo acessorios",
    "reclamacao": "reclamar situacoes especiais",
    "reclamar": "reclamacao",
}

# Known contradictions / ambiguities in the manual, keyed by section id.
CONFLICT_NOTES = {
    "0": "O telefone da capa/seção 1.2 é (67) 3341-4444, mas a seção 7 cita o WhatsApp (67) 3321-4500. "
         "Informe os dois com transparência e diga que a loja confirma qual é o canal oficial.",
    "1.2": "O e-mail aparece como contato@emporiodamusica.com.br na capa e contato@empóriodamusica.com.br "
           "(com acento) na tabela de dados da empresa. Use a versão sem acento e avise que o manual diverge.",
    "3": "A tabela diz 'parcela mínima de R$ 100,00' para crédito até 12x, mas a seção 3.1 define mínimos "
         "por faixa (3x sem mínimo, 4–6x R$ 80, 7–12x R$ 100). Assumimos a seção 3.1, que é a mais específica.",
    "3.1": "Conflito com a tabela da seção 3 (parcela mínima única de R$ 100). Prevalece a regra por faixa daqui.",
    "4.1": "O manual só descreve o direito de arrependimento para compras ONLINE; não diz como funciona em "
           "compras presenciais. Não afirme nada sobre compras presenciais.",
    "4.2": "Aqui o prazo de troca por defeito é 30 dias após a COMPRA, enquanto a seção 8.1 fala em 90 dias de "
           "garantia legal a partir do RECEBIMENTO. Explique as duas coisas: troca na loja em 30 dias; "
           "depois disso, garantia (legal/fabricante).",
    "8.1": "Compare com a seção 4.2 (30 dias de troca por defeito, contados da compra). Não são o mesmo prazo.",
    "7": "O WhatsApp aqui é (67) 3321-4500, diferente do telefone (67) 3341-4444 da seção 1.2.",
    "5.1": "O manual não define 'Região Metropolitana de Campo Grande' nem lista as cidades. Nos dados, os "
           "clientes de outras cidades são de Dourados, Três Lagoas, Corumbá e Ponta Porã (envio por Correios/Jadlog).",
}


@dataclass
class Section:
    sid: str
    title: str
    body: str
    conflict: str | None = None

    def as_dict(self) -> dict:
        out = {"section": self.sid, "title": self.title, "text": self.body}
        if self.conflict:
            out["conflict_note"] = self.conflict
        return out


def load_sections(path: Path | None = None) -> list[Section]:
    path = path or DATA_DIR / "politicas_da_loja.md"
    raw = path.read_text(encoding="utf-8")
    blocks: list[tuple[int, str, list[str]]] = []
    for line in raw.splitlines():
        m = re.match(r"^(#{2,3}) (.+)$", line)
        if m:
            blocks.append((len(m.group(1)), m.group(2).strip(), []))
        elif blocks:
            blocks[-1][2].append(line)
    sections: list[Section] = []
    for i, (level, title, lines) in enumerate(blocks):
        has_children = level == 2 and i + 1 < len(blocks) and blocks[i + 1][0] == 3
        body = "\n".join(lines).strip()
        if has_children and not body:
            continue
        sid = title.split(" ", 1)[0].rstrip(".")
        clean_title = title.split(" ", 1)[1] if sid[0].isdigit() else title
        sections.append(Section(sid, clean_title, body, CONFLICT_NOTES.get(sid)))
    return sections


class PolicyIndex:
    def __init__(self, sections: list[Section] | None = None):
        self.sections = sections or load_sections()
        self._tok = [set(tokens(f"{s.title} {s.title} {s.body}")) for s in self.sections]

    def _expand(self, query: str) -> set[str]:
        base = tokens(query)
        out = set(base)
        for t in base:
            out |= set(tokens(SYNONYMS.get(t, "")))
        return out

    def search(self, query: str, k: int = 3) -> list[Section]:
        q = self._expand(query)
        scored = []
        for sec, toks in zip(self.sections, self._tok):
            title_toks = set(tokens(sec.title))
            score = len(q & toks) + 2 * len(q & title_toks)
            if score:
                scored.append((score, sec))
        scored.sort(key=lambda x: -x[0])
        return [s for _, s in scored[:k]]

    def get(self, sid: str) -> Section | None:
        return next((s for s in self.sections if s.sid == sid), None)

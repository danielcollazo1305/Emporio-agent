"""Small accent-insensitive text helpers shared by product search and policy retrieval."""
from __future__ import annotations

import re
import unicodedata

STOPWORDS = {
    "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das", "em", "no", "na",
    "nos", "nas", "com", "sem", "para", "pra", "por", "e", "ou", "que", "qual", "quais", "quanto",
    "quanta", "tem", "ter", "voces", "voce", "meu", "minha", "me", "eu", "ate", "ao", "aos", "se",
    "ha", "sao", "e", "custa", "custando", "preco", "valor",
}


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text.lower()).strip()


def stem(token: str) -> str:
    """Very light Portuguese plural stripping (violoes -> violao, guitarras -> guitarra)."""
    if len(token) > 4 and token.endswith(("oes", "aes")):
        return token[:-3] + "ao"
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def tokens(text: str, drop_stopwords: bool = True) -> list[str]:
    words = re.findall(r"[a-z0-9]+", norm(text))
    if drop_stopwords:
        words = [w for w in words if w not in STOPWORDS]
    return [stem(w) for w in words]

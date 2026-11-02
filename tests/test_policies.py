import re
import shutil
import subprocess
from pathlib import Path

import pytest

from emporio_agent.policies import PolicyIndex

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="module")
def idx():
    return PolicyIndex()


@pytest.mark.parametrize("question,expected", [
    ("quero devolver um violão que comprei online", "4.1"),
    ("qual o endereço da loja", "1.2"),
    ("posso parcelar em 10x", "3.1"),
    ("vocês vendem cordas?", "7.1"),
    ("a loja abre sábado?", "2"),
    ("o pix tem desconto em produto em promoção", "6.2"),
    ("meu violão veio com defeito", "4.2"),
    ("como rastrear meu pedido", "5.3"),
])
def test_retrieval_finds_right_section(idx, question, expected):
    assert expected in [s.sid for s in idx.search(question)]


def test_conflicts_are_attached(idx):
    assert idx.get("4.2").conflict and "8.1" in idx.get("4.2").conflict
    assert idx.get("3.1").conflict


def test_unrelated_question_returns_nothing(idx):
    assert idx.search("qual a capital da França") == []


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext not installed")
def test_markdown_numbers_match_pdf():
    pdf_text = subprocess.run(["pdftotext", "-layout", str(DATA / "politicas_da_loja.pdf"), "-"],
                              capture_output=True, text=True, check=True).stdout
    md = (DATA / "politicas_da_loja.md").read_text(encoding="utf-8")
    numbers = lambda s: set(re.findall(r"\d[\d.,:/-]*\d|\d", s))
    missing = numbers(md) - numbers(pdf_text)
    # Only the md header (version note) and section numbering may differ.
    allowed = {"2.1", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "0"}
    assert not {m for m in missing if m not in allowed and not re.fullmatch(r"\d+\.\d+", m)}, missing

<p align="center"><img src="docs/logo.png" alt="Empório da Música" width="420"></p>

# Empório da Música — customer-service agent

A text-message (WhatsApp-style) customer-service agent for **Empório da Música**, a fictional musical-instrument store in Campo Grande/MS. It answers from the store's CSV data (products, promotions, customers, orders) and from the policy manual (PDF), decides which of the two a question needs, and politely refuses what is out of scope.

Built in Python for the Artefact AI Engineer technical challenge. The assistant is called **Jimi**, speaks Brazilian Portuguese, and keeps an informal-but-professional tone, as the manual asks (section 7.1).

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # then put YOUR key in .env (never commit it)
python -m emporio_agent --session demo --debug          # interactive chat; --debug shows tool calls
pytest -q                   # 37 offline tests, no API key needed (one needs pdftotext and is skipped without it)
python scripts/run_scenarios.py                         # regenerates examples/*.md with your key
```

Choose the provider with `LLM_PROVIDER=openai|anthropic` (default: Anthropic if `ANTHROPIC_API_KEY` is set, otherwise OpenAI) and the model with `LLM_MODEL`. Set `AGENT_NOW=2026-03-25T10:30:00` to pin the store clock (the dataset snapshot is from March 2026; the examples use this date).

## Example conversations

See [`examples/`](examples/): each file is a real run of `scripts/run_scenarios.py` (the provider/model is printed at the top of each file), including the tool calls the agent made. Covered: catalogue search with price filter, store address/hours, price of the Takamine GD20 with an expired promotion and the PIX rule, a regret/return request that needs identity verification + order data + policy, and out-of-scope questions (accessories, weather).

## How it works

```
customer message ──► Agent loop ──► LLM (OpenAI or Anthropic, same interface)
                        ▲   │ tool calls
                        │   ▼
                     ToolBox ──► Store (CSV)      search_products, get_product, list_my_orders,
                        │                         get_order_status, check_return_eligibility,
                        └──────► PolicyIndex (manual)  calculate_payment, calculate_shipping, get_store_hours,
                                                       verify_customer, get_store_policy
```

* **Data vs. policy routing** is done by the model through tool descriptions and a short system prompt ("never answer prices, stock or rules from memory"). Mixed questions ("can I return order 4?") call both order tools and the policy tools.
* **Business rules live in code, not in the prompt** (`tools.py`), so they are deterministic and unit-tested: only *active* promotions count; PIX 5% never stacks with promotional prices; installment minimums per section 3.1; return windows (7 days regret/preference, 30 days defect); shipping by city.
* **Privacy (LGPD, manual section 9):** order data is only reachable after `verify_customer` (e-mail or phone). A customer can only see their own orders, and "order doesn't exist" and "order belongs to someone else" return the same answer. Three failed attempts lock verification. A duplicated e-mail in the data is treated as ambiguous instead of guessed.
* **Out of scope:** accessories are redirected (the manual forbids selling them and asks to suggest partner stores); unrelated topics get a one-line refusal and a way back; prompt-injection attempts are ignored by instruction, and data protection does not depend on the model's goodwill because it is enforced in the tools.

## Technical decisions and justification

| Decision | Why |
|---|---|
| **No framework** (plain Python function-calling loop) | The problem is small: ten tools and one loop. A framework (LangChain/LangGraph) would add abstraction without adding behaviour I can reason about or test. The loop is ~50 lines and easy to explain. |
| **Two providers behind one interface** (`llm.py`) | The case leaves the model free. Provider-neutral history means a conversation can be replayed on either; a `FakeLLM` lets the whole loop be tested offline and deterministically. |
| **Policy retrieval = keyword + synonym scoring over ~26 manual sections** (no vector DB) | The manual is 8 pages. Embeddings would add a dependency, cost and non-determinism for no recall gain at this size. Sections are the natural unit and are returned whole, with citations by section number. If the manual grew, I would swap `PolicyIndex.search` for embeddings without touching the rest. |
| **Hand-cleaned Markdown copy of the manual** (`data/politicas_da_loja.md`) | Generic PDF extraction lost the headings and tables. A test (`test_markdown_numbers_match_pdf`) checks that every number in the Markdown appears in the original PDF; the PDF remains the source of truth. |
| **CSV loaded in memory** (no database) | 65 products, 20 orders. Pandas/SQL would be ceremony. Data is read-only; promotions are pre-filtered to active ones at load. |
| **Persistence = one JSON file per session** | Enough to survive restarts and keep verification state; trivial to inspect. Not suitable for concurrent multi-user serving (see limitations). |
| **CLI interface** | The case is a prototype; the agent core (`Agent.send(text) -> str`) is channel-agnostic and could sit behind a WhatsApp webhook. |
| **Tool-round cap, history window, error fallback** | Protect against loops, unbounded context and API failures; the user always gets a polite reply. |

## Handling inconsistencies

The data and the manual contain contradictions (two phone numbers, installment minimums that disagree, descriptions that contradict product names, a duplicated e-mail, order totals that do not add up…). The agent does not silently pick a side: where the manual conflicts with itself, the policy tool attaches a `conflict_note` and the prompt tells Jimi to explain the divergence and offer to confirm with the team. The full list and the chosen behaviour is in [`docs/data_findings.md`](docs/data_findings.md).

## Assumptions

* Section 3.1 (installments per tier) overrides the single R$ 100 minimum shown in the payments table.
* The real receipt date is not in the data, so return windows use `estimated_delivery` and the answer says it is an estimate. Defect exchange counts from purchase date, regret from receipt (as the manual states).
* Only Campo Grande city is "local" for delivery; every other city is handled as Correios/Jadlog.
* Prices are shown from the catalogue; shipping fees outside Campo Grande are not computed (the manual says it depends on CEP, weight and size).

## Known limitations

* **Retrieval is lexical.** Unusual phrasing outside the synonym table can miss a section. The tests cover the main intents only.
* **The model can still phrase things imperfectly.** Rules are enforced in tools, but wording (e.g. forgetting to show the original price next to a promotion) depends on the LLM. There is no automated check of final answers; I would add an LLM-as-judge or rule-based evaluation set next.
* **No actions.** Jimi cannot create orders, issue refunds or open tickets; it explains the next step. Complaints are acknowledged but not actually stored anywhere.
* **Single-user storage.** JSON files, no locking, no authentication of the chat channel itself; identity is verified only by e-mail/phone knowledge, which is a weak factor (a real system should use a one-time code).
* **Stock/prices are a CSV snapshot**, not live.
* **Holidays** are unknown, so "open now" can be wrong on a holiday.
* **Example conversations** come from a limited number of runs; behaviour varies between runs and models.
* The retrieval and rules were developed against the case's data; I did not test against other catalogues.

## Use of AI coding assistants

I used **Claude** (Anthropic) as a coding assistant, including Claude Code–style agentic sessions, to design and write most of this repository.

Workflow: I wrote the requirements and constraints and decided the scope (what the agent must do, privacy and stock rules, English README). The assistant read the case PDF, the CSVs and the manual, proposed the architecture, and wrote code, tests and documentation in small commits (each commit message carries a `Co-Authored-By` trailer). I reviewed the code, ran the tests and the scenarios with my own API key, and I am responsible for the final result. The assistant had no access to my API keys: keys live only in my local `.env`, which is git-ignored.

Where the assistant helped most: transcribing the manual into Markdown, finding the data/manual inconsistencies, writing the unit tests. Where it needed correcting: for example a first version of the history window could end up empty after a long tool loop (caught by a test and fixed).

## Repository layout

```
emporio_agent/   agent loop, tools, policy retrieval, prompts, LLM adapters, sessions, CLI
data/            CSVs, original policy PDF, Markdown transcription of the manual
tests/           offline tests (tools, policies, agent loop with a scripted LLM)
scripts/         run_scenarios.py — generates examples/
examples/        example conversations (generated)
docs/            data_findings.md
```

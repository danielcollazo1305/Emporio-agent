"""Agent tools: pure functions over the Store plus per-conversation state.

Every tool returns plain JSON-serialisable dicts. Business rules live here (not in the prompt)
so they are testable and cannot be "forgotten" by the model.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from . import config
from .data_store import Product, Store
from .policies import PolicyIndex
from .text import norm, tokens

MAX_FAILED_VERIFICATIONS = 3
METRO_CITY = "campo grande"
ACCESSORY_WORDS = {"corda", "palheta", "cabo", "pedal", "amplificador", "case", "capa", "afinador", "suporte", "estante"}
STATUS_PT = {
    "pending": "pendente (aguardando pagamento)",
    "confirmed": "confirmado (em separação)",
    "shipped": "enviado",
    "delivered": "entregue",
    "cancelled": "cancelado",
}


def brl(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


class ToolBox:
    def __init__(self, store: Store | None = None, policies: PolicyIndex | None = None, state: dict | None = None):
        self.store = store or Store()
        self.policies = policies or PolicyIndex()
        # state is persisted with the session: verified customer + failed attempts
        self.state = state if state is not None else {}
        self.state.setdefault("customer_id", None)
        self.state.setdefault("failed_verifications", 0)

    # ---------- products ----------
    def _product_view(self, p: Product) -> dict:
        promo = self.store.active_promotions.get(p.product_id)
        view = {
            "product_id": p.product_id,
            "name": p.name,
            "category": p.category,
            "list_price": brl(p.price_brl),
            "status": p.status,
            "stock_quantity": p.stock_quantity,
            "available_now": p.status == "active" and p.stock_quantity > 0,
            "specs": p.specs,
        }
        if promo:
            view["promotion"] = {
                "name": promo["name"],
                "discount_percent": promo["percent"],
                "promo_price": brl(self.store.promo_price(p)),
                "note": "Preço promocional: o desconto de PIX de 5% NÃO se soma.",
            }
        if p.description_reliable:
            view["description"] = p.description
        else:
            view["description_warning"] = (
                "A descrição cadastrada contradiz o nome/ficha técnica; não a repita. Use só nome e specs. "
                + " ".join(p.data_notes)
            )
        if p.status == "coming_soon":
            view["note"] = "Ainda não disponível (em breve). Não aceite pedido nem confirme estoque."
        if p.status == "discontinued":
            view["note"] = "Fora de catálogo. Ofereça modelos equivalentes."
        return view

    def search_products(self, query: str = "", category: str = "", max_price: float | None = None,
                        min_price: float | None = None, available_only: bool = False, limit: int = 8) -> dict:
        q_tokens = set(tokens(query))
        if q_tokens & ACCESSORY_WORDS and not (q_tokens - ACCESSORY_WORDS - {"para", "violao", "guitarra", "baixo"}):
            return {"results": [], "out_of_scope": True,
                    "message": "A loja não vende acessórios (cordas, palhetas, cabos, cases, pedais, amplificadores)."}
        cat_tokens = set(tokens(category))
        hits = []
        for p in self.store.products.values():
            hay = set(tokens(f"{p.name} {p.category} {' '.join(map(str, p.specs.values()))}"))
            if cat_tokens and not (cat_tokens & set(tokens(p.category))):
                continue
            price = self.store.effective_price(p)
            if max_price is not None and price > max_price:
                continue
            if min_price is not None and price < min_price:
                continue
            if available_only and not (p.status == "active" and p.stock_quantity > 0):
                continue
            if q_tokens:
                matched = len(q_tokens & hay)
                # every query word must match, except words that are only category noise
                if matched < len(q_tokens):
                    continue
                score = matched
            else:
                score = 0
            hits.append((score, price, p))
        hits.sort(key=lambda x: (-x[0], x[1]))
        shown = [self._product_view(p) for _, _, p in hits[:limit]]
        return {"total_matches": len(hits), "shown": len(shown), "results": shown,
                "note": "Preços já refletem só promoções ATIVAS; list_price é o preço de tabela."}

    def get_product(self, product_id: int | None = None, name: str = "") -> dict:
        if product_id is not None and int(product_id) in self.store.products:
            return self._product_view(self.store.products[int(product_id)])
        if name:
            q = set(tokens(name))
            best = None
            for p in self.store.products.values():
                score = len(q & set(tokens(p.name)))
                if score and score >= len(q) and (best is None or score > best[0]):
                    best = (score, p)
            if best:
                return self._product_view(best[1])
        return {"error": "Produto não encontrado. Use search_products para listar opções parecidas."}

    # ---------- policies ----------
    def get_store_policy(self, topic: str) -> dict:
        found = self.policies.search(topic, k=3)
        if not found:
            return {"found": False, "message": "Nada no manual sobre isso. Não invente; diga que vai confirmar com a equipe."}
        return {"found": True, "sections": [s.as_dict() for s in found]}

    # ---------- customer / orders ----------
    def verify_customer(self, email_or_phone: str) -> dict:
        if self.state["failed_verifications"] >= MAX_FAILED_VERIFICATIONS:
            return {"verified": False, "locked": True,
                    "message": "Muitas tentativas. Peça para o cliente falar com a loja pelo telefone ou WhatsApp."}
        raw = email_or_phone.strip()
        matches = []
        if "@" in raw:
            matches = [c for c in self.store.customers.values() if c["email"].lower() == raw.lower()]
        elif len(_digits(raw)) >= 8:
            d = _digits(raw)
            matches = [c for c in self.store.customers.values() if _digits(c["phone"]).endswith(d[-9:])]
        if len(matches) == 1:
            c = matches[0]
            self.state["customer_id"] = int(c["customer_id"])
            self.state["failed_verifications"] = 0
            return {"verified": True, "first_name": c["name"].split()[0], "city": c["city"]}
        if len(matches) > 1:
            # duplicate contact data: do not guess which person this is
            return {"verified": False, "ambiguous": True,
                    "message": "Mais de um cadastro com esse dado. Peça o telefone cadastrado e tente de novo."}
        self.state["failed_verifications"] += 1
        left = MAX_FAILED_VERIFICATIONS - self.state["failed_verifications"]
        return {"verified": False, "attempts_left": left,
                "message": "Não encontrei cadastro com esse dado. Não diga qual parte estava errada."}

    def _require_customer(self) -> dict | None:
        cid = self.state.get("customer_id")
        if cid is None:
            return {"error": "not_verified",
                    "message": "Antes de falar de pedidos, peça o e-mail ou telefone do cadastro e use verify_customer."}
        return None

    def _order_view(self, oid: int) -> dict:
        o = self.store.orders[oid]
        items = []
        for it in self.store.order_items.get(oid, []):
            p = self.store.products.get(it["product_id"])
            items.append({"product": p.name if p else f"produto {it['product_id']}", "quantity": it["quantity"]})
        view = {
            "order_id": oid, "order_date": o["order_date"], "status": o["status"],
            "status_pt": STATUS_PT.get(o["status"], o["status"]),
            "total": brl(float(o["total_brl"])), "payment_method": o["payment_method"], "items": items,
        }
        if o["tracking_code"]:
            view["tracking_code"] = o["tracking_code"]
        if o["estimated_delivery"]:
            view["estimated_delivery"] = o["estimated_delivery"]
        if o["notes"]:
            view["notes"] = o["notes"]
        return view

    def list_my_orders(self) -> dict:
        if (err := self._require_customer()):
            return err
        cid = self.state["customer_id"]
        ids = [int(o["order_id"]) for o in self.store.orders.values() if int(o["customer_id"]) == cid]
        return {"orders": [self._order_view(i) for i in sorted(ids)]}

    def get_order_status(self, order_id: int) -> dict:
        if (err := self._require_customer()):
            return err
        o = self.store.orders.get(int(order_id))
        # same answer for "does not exist" and "belongs to someone else": do not leak other customers' orders
        if not o or int(o["customer_id"]) != self.state["customer_id"]:
            return {"error": "order_not_found", "message": "Não achei esse pedido na conta verificada."}
        return self._order_view(int(order_id))

    def check_return_eligibility(self, order_id: int, reason: str = "regret", channel: str = "online") -> dict:
        """reason: regret | defect | preference. Receipt date is approximated by estimated_delivery."""
        if (err := self._require_customer()):
            return err
        o = self.store.orders.get(int(order_id))
        if not o or int(o["customer_id"]) != self.state["customer_id"]:
            return {"error": "order_not_found", "message": "Não achei esse pedido na conta verificada."}
        status = o["status"]
        if status != "delivered":
            return {"eligible": False, "status": status,
                    "message": f"O pedido está '{STATUS_PT.get(status, status)}', não entregue; "
                               "devolução/troca só vale após o recebimento. Se estiver cancelado, não há o que devolver."}
        received = date.fromisoformat(o["estimated_delivery"])
        days = (config.today() - received).days
        order_date = date.fromisoformat(o["order_date"])
        limits = {"regret": 7, "preference": 7, "defect": 30}
        limit = limits.get(reason, 7)
        base = "purchase" if reason == "defect" else "receipt"
        elapsed = (config.today() - (order_date if base == "purchase" else received)).days
        res = {
            "order_id": int(order_id), "reason": reason, "days_limit": limit, "days_elapsed": elapsed,
            "counted_from": "data da compra" if base == "purchase" else "data de recebimento",
            "receipt_date_is_estimate": True,
            "within_window": elapsed <= limit,
            "assumption": "A data de recebimento real não está nos dados; usamos a entrega estimada.",
        }
        if reason == "regret":
            res["channel_note"] = "O direito de arrependimento do manual vale para compras online."
            res["conditions"] = "Embalagem original, sem uso, com acessórios e manuais. Frete de devolução por conta da loja; reembolso em até 10 dias úteis na mesma forma de pagamento."
        if reason == "defect" and elapsed > limit:
            res["next_step"] = "Após 30 dias: garantia legal (90 dias do recebimento) e do fabricante; a loja pode intermediar."
            res["warranty_days_elapsed"] = days
        if reason == "regret" and elapsed > limit:
            res["next_step"] = "Fora do prazo de arrependimento. Se houver defeito, vale a troca (30 dias da compra) ou garantia."
        return res

    # ---------- money & logistics ----------
    def calculate_payment(self, product_ids: list[int], payment_method: str, installments: int = 1) -> dict:
        items, subtotal, any_promo = [], 0.0, False
        for pid in product_ids:
            p = self.store.products.get(int(pid))
            if not p:
                return {"error": f"produto {pid} não encontrado"}
            promo = self.store.promo_price(p)
            price = promo if promo is not None else p.price_brl
            any_promo = any_promo or promo is not None
            subtotal += price
            items.append({"name": p.name, "unit_price": brl(price), "promotional": promo is not None})
        method = norm(payment_method)
        res = {"items": items, "subtotal": brl(subtotal)}
        if method == "pix":
            # PIX 5% applies to list price only, never on promotional prices (manual 6.2)
            total = 0.0
            lines = []
            for pid in product_ids:
                p = self.store.products[int(pid)]
                if self.store.promo_price(p) is None:
                    total += round(p.price_brl * 0.95, 2)
                    lines.append(f"{p.name}: 5% PIX aplicado")
                else:
                    total += self.store.promo_price(p)
                    lines.append(f"{p.name}: preço promocional, sem 5% de PIX")
            res.update({"total": brl(total), "pix_details": lines})
        elif method in ("credito", "credit", "cartao de credito", "cartao"):
            n = int(installments)
            if not 1 <= n <= 12:
                return {"error": "Parcelamento é de 1x a 12x."}
            per = subtotal / n
            min_per = 0 if n <= 3 else 80 if n <= 6 else 100
            ok = per >= min_per and not (n > 1 and per < 50)
            res.update({"installments": n, "installment_value": brl(per), "allowed": ok,
                        "rule": "3.1: até 3x sem mínimo (exceto parcela abaixo de R$ 50), 4–6x mínimo R$ 80, 7–12x mínimo R$ 100; sem juros.",
                        "total": brl(subtotal)})
            if not ok:
                for m in range(n - 1, 0, -1):
                    per_m = subtotal / m
                    mm = 0 if m <= 3 else 80 if m <= 6 else 100
                    if per_m >= mm and not (m > 1 and per_m < 50):
                        res["max_installments_allowed"] = m
                        break
        elif method in ("debito", "boleto", "debit"):
            res.update({"total": brl(subtotal), "note": "Pagamento à vista, sem desconto" + ("; boleto compensa em até 3 dias úteis." if method == "boleto" else ".")})
        else:
            return {"error": "Forma de pagamento desconhecida. Aceitas: PIX, débito, crédito (até 12x), boleto."}
        if any_promo:
            res["promo_note"] = "Há item promocional: apresente também o preço original e o percentual (manual 6.2)."
        return res

    def calculate_shipping(self, city: str, order_total: float) -> dict:
        if norm(city) == METRO_CITY:
            free = order_total > 500
            return {"region": "Campo Grande (entrega por motoboy próprio)",
                    "fee": "grátis" if free else brl(35), "delivery_time": "1 a 3 dias úteis",
                    "rule": "Frete grátis acima de R$ 500,00; abaixo, taxa fixa de R$ 35,00.",
                    "note": "O manual não lista as demais cidades da região metropolitana; confirme com a loja se for outro município próximo."}
        return {"region": f"{city} (fora de Campo Grande)",
                "options": {"PAC": "5 a 12 dias úteis", "SEDEX": "2 a 5 dias úteis", "Jadlog .package": "3 a 8 dias úteis"},
                "fee": "calculado pelo CEP, peso e dimensões (não temos esse cálculo aqui)",
                "note": "Instrumentos grandes (baterias acústicas, pianos digitais, contrabaixos) podem exigir cotação individual. Seguro incluído."}

    def get_store_hours(self) -> dict:
        now = config.now()
        wd, t = now.weekday(), now.time()
        from datetime import time
        if wd <= 4:
            opens, closes = time(9), time(18)
        elif wd == 5:
            opens, closes = time(9), time(13)
        else:
            opens = closes = None
        is_open = bool(opens and opens <= t < closes)
        return {"now": now.strftime("%A %d/%m/%Y %H:%M"), "is_open_now": is_open,
                "hours": "Seg–Sex 09:00–18:00, Sáb 09:00–13:00, Dom e feriados fechado",
                "note": "O manual não traz a lista de feriados; se hoje for feriado, a loja está fechada."}

    # ---------- registry ----------
    def call(self, name: str, args: dict) -> dict:
        fn = getattr(self, name, None)
        if name.startswith("_") or name not in TOOL_NAMES or fn is None:
            return {"error": f"ferramenta desconhecida: {name}"}
        try:
            return fn(**args)
        except TypeError as e:
            return {"error": f"argumentos inválidos para {name}: {e}"}
        except Exception as e:  # tool failure must not crash the conversation
            return {"error": f"falha ao executar {name}: {type(e).__name__}: {e}"}


TOOL_SPECS = [
    {"name": "search_products", "description": "Busca produtos no catálogo por texto, categoria e faixa de preço. Preço filtrado é o efetivo (já com promoção ativa).",
     "parameters": {"type": "object", "properties": {
         "query": {"type": "string", "description": "Palavras do produto/marca, ex.: 'Takamine', 'nylon'"},
         "category": {"type": "string", "description": "Ex.: Violões, Guitarras, Baixos, Ukuleles"},
         "max_price": {"type": "number"}, "min_price": {"type": "number"},
         "available_only": {"type": "boolean"}, "limit": {"type": "integer"}}}},
    {"name": "get_product", "description": "Detalhes de um produto por id ou nome.",
     "parameters": {"type": "object", "properties": {"product_id": {"type": "integer"}, "name": {"type": "string"}}}},
    {"name": "get_store_policy", "description": "Consulta o manual de políticas (pagamento, troca/devolução, frete, garantia, promoções, endereço, atendimento, privacidade). Use SEMPRE antes de afirmar regra da loja.",
     "parameters": {"type": "object", "properties": {"topic": {"type": "string", "description": "A dúvida do cliente em linguagem natural"}}, "required": ["topic"]}},
    {"name": "verify_customer", "description": "Verifica o cliente por e-mail ou telefone. Obrigatório antes de qualquer dado de pedido.",
     "parameters": {"type": "object", "properties": {"email_or_phone": {"type": "string"}}, "required": ["email_or_phone"]}},
    {"name": "list_my_orders", "description": "Lista os pedidos do cliente verificado.", "parameters": {"type": "object", "properties": {}}},
    {"name": "get_order_status", "description": "Status, rastreio e itens de um pedido do cliente verificado.",
     "parameters": {"type": "object", "properties": {"order_id": {"type": "integer"}}, "required": ["order_id"]}},
    {"name": "check_return_eligibility", "description": "Aplica as regras de arrependimento (7 dias), preferência (7) e defeito (30) a um pedido do cliente verificado.",
     "parameters": {"type": "object", "properties": {
         "order_id": {"type": "integer"}, "reason": {"type": "string", "enum": ["regret", "preference", "defect"]},
         "channel": {"type": "string", "enum": ["online", "in_store"]}}, "required": ["order_id"]}},
    {"name": "calculate_payment", "description": "Calcula total/parcelas por forma de pagamento aplicando as regras de PIX, promoção e parcelamento.",
     "parameters": {"type": "object", "properties": {
         "product_ids": {"type": "array", "items": {"type": "integer"}},
         "payment_method": {"type": "string", "enum": ["pix", "credito", "debito", "boleto"]},
         "installments": {"type": "integer"}}, "required": ["product_ids", "payment_method"]}},
    {"name": "calculate_shipping", "description": "Frete e prazo por cidade e valor do pedido.",
     "parameters": {"type": "object", "properties": {"city": {"type": "string"}, "order_total": {"type": "number"}}, "required": ["city", "order_total"]}},
    {"name": "get_store_hours", "description": "Informa se a loja está aberta agora e os horários.", "parameters": {"type": "object", "properties": {}}},
]
TOOL_NAMES = {s["name"] for s in TOOL_SPECS}

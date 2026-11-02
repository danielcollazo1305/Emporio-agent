"""Loads the CSV tables into typed, indexed structures and cleans what can be cleaned.

Data-quality findings that affect behaviour are handled here (and documented in
docs/data_findings.md): product descriptions that contradict the product name/specs are
flagged so the agent never repeats them.
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .config import DATA_DIR
from .text import norm

KNOWN_BRANDS = [
    "yamaha", "fender", "gibson", "ibanez", "music man", "pearl", "tama", "korg", "roland", "nord",
    "prs", "taylor", "martin", "takamine", "crafter", "giannini", "tagima", "rozini", "shelby",
    "kala", "ohana", "kalani",
]


@dataclass
class Product:
    product_id: int
    name: str
    category_id: int
    category: str
    price_brl: float
    description: str
    stock_quantity: int
    status: str
    specs: dict
    created_at: date
    data_notes: list[str] = field(default_factory=list)

    @property
    def description_reliable(self) -> bool:
        return not self.data_notes


def _brands_in(text: str) -> set[str]:
    padded = f" {norm(text)} "
    return {b for b in KNOWN_BRANDS if f" {b} " in padded}


def _description_conflicts(name: str, description: str, specs: dict) -> list[str]:
    notes: list[str] = []
    extra = _brands_in(description) - _brands_in(name)
    if extra:
        notes.append(
            f"A descrição cadastrada cita outra marca ({', '.join(sorted(extra))}) que não consta no nome."
        )
    desc = norm(description)
    keys = re.search(r"(\d+) teclas", desc)
    if keys and specs.get("keys") and keys.group(1) != str(specs["keys"]):
        notes.append(f"A descrição fala em {keys.group(1)} teclas, mas a ficha técnica diz {specs['keys']}.")
    strings = re.search(r"(\d+) cordas", desc)
    if strings and str(specs.get("strings", "")).isdigit() and strings.group(1) != str(specs["strings"]):
        notes.append(f"A descrição fala em {strings.group(1)} cordas, mas a ficha técnica diz {specs['strings']}.")
    return notes


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


class Store:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.categories = {int(r["category_id"]): r for r in _read(data_dir / "categories.csv")}
        self.products: dict[int, Product] = {}
        for r in _read(data_dir / "products.csv"):
            specs = json.loads(r["specs"]) if r["specs"] else {}
            pid = int(r["product_id"])
            self.products[pid] = Product(
                product_id=pid,
                name=r["name"].strip(),
                category_id=int(r["category_id"]),
                category=self.categories[int(r["category_id"])]["name"],
                price_brl=float(r["price_brl"]),
                description=r["description"].strip(),
                stock_quantity=int(r["stock_quantity"]),
                status=r["status"].strip(),
                specs=specs,
                created_at=date.fromisoformat(r["created_at"]),
                data_notes=_description_conflicts(r["name"], r["description"], specs),
            )
        self.customers = {int(r["customer_id"]): r for r in _read(data_dir / "customers.csv")}
        self.orders = {int(r["order_id"]): r for r in _read(data_dir / "orders.csv")}
        self.order_items: dict[int, list[dict]] = {}
        for r in _read(data_dir / "order_items.csv"):
            self.order_items.setdefault(int(r["order_id"]), []).append(
                {"product_id": int(r["product_id"]), "quantity": int(r["quantity"])}
            )
        # Promotions are not cumulative (manual 6.2): keep only the best ACTIVE one per product.
        self.active_promotions: dict[int, dict] = {}
        for r in _read(data_dir / "promotions.csv"):
            if r["is_active"].strip() != "1":
                continue
            pid = int(r["product_id"])
            promo = {"percent": float(r["discount_percent"]), "name": r["description"].strip()}
            if pid not in self.active_promotions or promo["percent"] > self.active_promotions[pid]["percent"]:
                self.active_promotions[pid] = promo

    def promo_price(self, product: Product) -> float | None:
        promo = self.active_promotions.get(product.product_id)
        if not promo:
            return None
        return round(product.price_brl * (1 - promo["percent"] / 100), 2)

    def effective_price(self, product: Product) -> float:
        promo_price = self.promo_price(product)
        return promo_price if promo_price is not None else product.price_brl

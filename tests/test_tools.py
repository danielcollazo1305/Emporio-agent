def test_violoes_ate_1000_respects_price_and_stock(tb):
    r = tb.search_products(category="Violões", max_price=1000, available_only=True, limit=50)
    assert r["results"], "expected some guitars under R$1000"
    for item in r["results"]:
        assert item["available_now"]
        assert item["category"] == "Violões"


def test_takamine_gd20_price_has_no_promotion(tb):
    r = tb.search_products(query="Takamine GD20")
    assert r["total_matches"] == 1
    item = r["results"][0]
    assert item["list_price"] == "R$ 2.199,00"
    assert "promotion" not in item  # promo 95 is inactive


def test_active_promotion_is_exposed_with_original_price(tb):
    item = tb.get_product(product_id=90)
    assert item["promotion"]["discount_percent"] == 18
    assert item["list_price"] == "R$ 2.399,00"
    assert item["promotion"]["promo_price"] == "R$ 1.967,18"


def test_accessories_are_out_of_scope(tb):
    assert tb.search_products(query="cordas")["out_of_scope"] is True


def test_conflicting_description_is_withheld(tb):
    item = tb.get_product(product_id=137)
    assert "description" not in item and "description_warning" in item


def test_coming_soon_and_discontinued_flagged(tb):
    assert "não" in tb.get_product(product_id=130)["note"].lower()
    assert tb.get_product(product_id=136)["available_now"] is False


def test_orders_require_verification(tb):
    assert tb.get_order_status(1)["error"] == "not_verified"
    assert tb.list_my_orders()["error"] == "not_verified"


def test_cannot_read_other_customers_order(tb):
    assert tb.verify_customer("lucas.mendes@jmail.com")["verified"]
    assert tb.get_order_status(4)["order_id"] == 4
    assert tb.get_order_status(1)["error"] == "order_not_found"  # belongs to customer 3


def test_lockout_after_three_failures(tb):
    for _ in range(3):
        tb.verify_customer("nope@x.com")
    r = tb.verify_customer("lucas.mendes@jmail.com")
    assert r["locked"] and not r["verified"]


def test_duplicate_email_is_ambiguous_not_guessed(tb):
    r = tb.verify_customer("bruno.martins@jmail.com")  # customers 11 and 43
    assert r.get("ambiguous") and not r["verified"]


def test_phone_verification(tb):
    assert tb.verify_customer("(67) 99812-3456")["verified"]


def test_return_window_expired_for_old_order(tb):
    tb.verify_customer("lucas.mendes@jmail.com")
    r = tb.check_return_eligibility(4, reason="regret")
    assert r["within_window"] is False


def test_return_not_applicable_to_unshipped_order(tb):
    tb.verify_customer("(67) 99456-7890")  # customer 8, order 13 pending
    r = tb.check_return_eligibility(13)
    assert r["eligible"] is False


def test_pix_discount_only_on_list_price(tb):
    assert tb.calculate_payment([95], "pix")["total"] == "R$ 2.089,05"
    promo = tb.calculate_payment([90], "pix")
    assert promo["total"] == "R$ 1.967,18"


def test_installment_minimums(tb):
    r = tb.calculate_payment([81], "credito", 12)  # R$599.90 / 12 < 100
    assert r["allowed"] is False and r["max_installments_allowed"] == 6
    assert tb.calculate_payment([95], "credito", 12)["allowed"] is True


def test_shipping_rules(tb):
    assert tb.calculate_shipping("Campo Grande", 501)["fee"] == "grátis"
    assert tb.calculate_shipping("campo grande", 499)["fee"] == "R$ 35,00"
    assert "PAC" in tb.calculate_shipping("Dourados", 800)["options"]


def test_store_hours_wednesday_morning_open(tb):
    assert tb.get_store_hours()["is_open_now"] is True


def test_unknown_tool_and_bad_args_do_not_crash(tb):
    assert "error" in tb.call("drop_database", {})
    assert "error" in tb.call("get_order_status", {"wrong": 1})


def test_expired_regret_does_not_offer_closed_windows(tb):
    tb.verify_customer("lucas.mendes@jmail.com")
    r = tb.check_return_eligibility(4, reason="regret")  # bought 2025-12-10, today 2026-03-25
    other = r["other_options"]
    assert other["defect_exchange_still_open"] is False
    assert other["legal_warranty_still_open"] is False
    assert "manufacturer_warranty" in other

# Data and manual findings

Things found while reading the CSVs and the policy manual, and what the agent does about each.
Most are probably deliberate traps in the case; none are "fixed" silently in the data files.

## Policy manual (PDF)

| # | Finding | Agent behaviour |
|---|---------|-----------------|
| 1 | Two different phone numbers: (67) 3341-4444 (cover, 1.2) vs WhatsApp (67) 3321-4500 (section 7). | Gives both and says the store confirms the official channel (`conflict_note` on sections 0 and 7). |
| 2 | E-mail spelled with and without accent (`emporiodamusica` vs `empóriodamusica`) in 1.2. | Uses the unaccented one and flags the discrepancy. |
| 3 | Payments table: credit card minimum installment R$ 100; section 3.1: 3x no minimum, 4–6x R$ 80, 7–12x R$ 100. | Section 3.1 wins (more specific). Documented as an assumption; `calculate_payment` implements 3.1. |
| 4 | Returns (4.2): defect exchange within 30 days of **purchase**; warranty (8.1): 90 days from **receipt**. | Explains both: in-store exchange within 30 days, afterwards legal/manufacturer warranty. |
| 5 | 4.1 only covers *online* purchases; nothing on in-store regret. | Does not invent a rule for in-store purchases. |
| 6 | "Metropolitan region of Campo Grande" is never defined. | Only Campo Grande city is treated as local; other cities use Correios/Jadlog and the agent says so. |
| 7 | Catalogue "300+ instruments" vs 65 products in the CSV; categories 6, 7 and 8 (winds, brass, orchestral strings) have no products. | Search simply returns nothing; the agent never claims products that are not in the data. |
| 8 | No holiday calendar. | `get_store_hours` warns that holidays are closed but cannot know them. |

## CSV data

| # | Finding | Agent behaviour |
|---|---------|-----------------|
| 1 | Only 4 promotions are active (`is_active=1`): products 90, 94, 121, 127. Many others (e.g. Takamine GD20, id 95) are expired. | Only active promotions are shown/applied. A customer citing an expired promo is told it is not active. |
| 2 | Product descriptions contradict name/specs for several products (e.g. "Music Man Bass 1X" described as a Fender; "Korg Synth 1 Pro" described as Roland with 88 keys vs 61 in specs): ids 135, 137, 139, 140, 142, 144. | Detected at load time (`description_warning`); the agent uses only name + specs and mentions the inconsistency if relevant. |
| 3 | Active products with stock 0 (ids 96, 113); status `discontinued` (113, 136) and `coming_soon` (130). | `available_now` requires `status=active` and `stock>0`; alternatives are suggested. |
| 4 | Duplicate e-mail `bruno.martins@jmail.com` (customers 11 and 43). | Verification by that e-mail is refused as ambiguous; the customer is asked for the registered phone (never guessed). |
| 5 | Order totals that do not match item prices: order 3 (3450 vs 3498 from items) and 20 (1400 vs 1488). | Totals are reported as stored. Not repaired; possible discount/freight explanation is unknown. |
| 6 | No delivery/receipt date, only `estimated_delivery`. | Return-window checks use the estimate and say so (`receipt_date_is_estimate`). |
| 7 | Dataset snapshot is around 2026-03-22; today is later. | `AGENT_NOW` pins the clock so examples are reproducible; otherwise the real date is used. |

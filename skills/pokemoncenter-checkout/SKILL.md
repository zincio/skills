---
name: pokemoncenter-checkout
description: Discover, buy, track, and return real products from Pokémon Center (pokemoncenter.com) through the Zinc API (zinc.com) — and from almost any other US retailer on the same API. Needs no account to begin — the agent mints its own test key, then earns a live key and a $5 starter credit once its operator approves it. Pay from a pre-funded wallet, per request over MPP or x402, or with a Stripe Link card.
---

# Pokémon Center Checkout

Buy, track, and return products from Pokémon Center (pokemoncenter.com) through the Zinc API (`https://api.zinc.com`). US orders.

> **Powered by Zinc Universal Checkout.** The same API buys from Pokémon Center and almost any other US retailer. To order across multiple retailers from one skill, install the [`universal-checkout`](https://github.com/zincio/skills/tree/master/skills/universal-checkout) skill (`npx skills add zincio/skills --skill universal-checkout`). Live retailer list: `GET https://api.zinc.com/retailers`.

## Getting started

Four steps, in order. Full walkthrough: [Agent Sandbox Quickstart](https://www.zinc.com/docs/v2/agent-sandbox/quickstart.md) and [Going Live](https://www.zinc.com/docs/v2/agent-sandbox/going-live.md).

1. **Get a test key.** `POST https://api.zinc.com/sandbox/keys` — no auth, no signup. Returns `api_key` (`zn_test_…`) and a ready-made `example_order`. Send it as `Authorization: Bearer <api_key>` from here on.
2. **Place a test order.** `POST /orders` with that `example_order`, then poll `GET /orders/{id}`. Free. `status` reaches **`order_placed`** — that is success, and it never becomes `delivered`; shipping shows up under `tracking_numbers[0].status`.
3. **Earn your live key.** `POST /device/code` with your test key as Bearer — that is what carries your sandbox history over. Show your operator the link it returns, then poll `POST /device/token` (no `Authorization` header; 400 `authorization_pending` means keep waiting). On approval you get a `zn_live_` key **once**, plus a **$5 starter credit** in their wallet.
4. **Buy something real.** `POST /orders` with a pokemoncenter.com product URL. **`max_price` is a ceiling, not a price** — you are charged the retailer's actual total, so set it a little above the listed price to leave room for tax and shipping. Ask your operator for the shipping address (**`phone_number` is required**) and confirm the item and price with them first.

Watch the money: `GET /wallet/me` shows the `balance` and `order_fee_cents` (charged per order, on top of `max_price`). Each `/search` call costs 1¢ from the same wallet.

Already have a key from your operator? Use it and skip to **Place an order**. Never want an account? Pay per request over [MPP](https://www.zinc.com/docs/v2/mpp.md): `POST /agent/orders`, no key needed.

## Place an order

```bash
curl -X POST https://api.zinc.com/orders \
  -H "Authorization: Bearer $ZINC_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "products": [{"url": "https://www.pokemoncenter.com/<product-page>", "quantity": 1}],
    "max_price": 5000,
    "shipping_address": {
      "first_name": "Jane", "last_name": "Doe",
      "address_line1": "123 Main St", "city": "San Francisco",
      "state": "CA", "postal_code": "94105", "country": "US",
      "phone_number": "4155552671"
    }
  }'
```

- `max_price` is the ceiling **in cents** for the whole order. Zinc refuses rather than exceeding it.
- `phone_number` is required. Never invent an address — ask your operator.
- Returns `201` with an order `id` and `status: pending`. Retailer, variants, quantities, gift options, idempotency: [Create Order](https://www.zinc.com/docs/v2/api-reference/orders/create-order.md).

## Track, cancel, return

- `GET /orders/{id}` — `status` is one of `pending`, `order_placed` (**success**), `order_failed`, `cancelled`. Shipping lives on `tracking_numbers[].status`. ([statuses](https://www.zinc.com/docs/v2/api-reference/orders/get-order.md), [tracking](https://www.zinc.com/docs/v2/api-reference/orders/tracking.md))
- `POST /orders/{id}/cancel` — only while `pending`. ([cancel](https://www.zinc.com/docs/v2/api-reference/orders/cancel-order.md))
- `POST /returns` — needs the order id and a reason. ([returns](https://www.zinc.com/docs/v2/api-reference/returns/create-return.md))

## When something fails

Errors are `{"error": {"code", "message", "details"}}`. Read `code`, not the message. `details` often names the fix — a `402 insufficient_funds` carries `fund_with`, every way to pay. Full list: [Error Handling](https://www.zinc.com/docs/v2/api-reference/introduction/error-handling.md) and [references/errors.md](https://github.com/zincio/skills/blob/master/skills/pokemoncenter-checkout/references/errors.md).

## Rules

- **Money is real.** Confirm the item and the price with your operator before any live order.
- **Set `max_price` deliberately** — it is the only thing standing between a typo and a large purchase.
- **Never invent a shipping address**, and never reuse the sandbox one for a live order.
- Rehearse failures in the sandbox first: `GET /orders/test-products`.

All amounts are in **US cents** (e.g. `5000` = $50.00). US delivery.

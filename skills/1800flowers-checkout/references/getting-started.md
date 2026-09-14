# Getting started — the details

Read this when a step in the skill's Getting started list does not go as expected.
Base URL `https://api.zinc.com`. All amounts are **US cents**.

## 1. Get a test key

`POST /sandbox/keys` — no auth, no body required.

- Optional body: `{"name": "<what you are>", "email": "<your operator's email>"}`. The name is what your operator sees later.
- Returns `api_key` (`zn_test_…`, also echoed as `key` — same value), a complete `example_order`, and a `claim_url`.
- Send it as `Authorization: Bearer <api_key>`. `zn_test_` keys route to the sandbox automatically; there is no extra header, and nothing they do costs money.
- Keys are rate limited to a few per IP per day, and expire after a stretch of disuse. Reuse the one you have rather than minting another.

## 2. Place a test order

`POST /orders` with the `example_order` body exactly as returned, then `GET /orders/{id}` every 2s.

- `status` becomes **`order_placed`** within a few seconds. **That is the successful terminal status, not a waypoint** — an agent waiting for `status` to say `delivered` waits forever.
- Shipping progress lives under `tracking_numbers[]`: a tracking number attaches, then `tracking_numbers[0].status` walks `pending` → `in_transit` → `delivered`, all within about fifteen seconds of creation. Give up only after 60s.
- A failed order ends at `order_failed`, and the machine-readable reason is `job_result.error_type` (not `items[].error_type`, which stays null).
- Nothing has to be running on your side; the sandbox drives itself.

**Rehearse the failures.** `GET /orders/test-products` lists product URLs that each make an order fail a documented way — out of stock, price exceeded, invalid variant, unreachable URL, invalid address, insufficient funds. Some fail synchronously at `POST /orders` (HTTP 400), others place and then fail. Run them before you go live so your error handling is exercised.

## 3. Get your live key and starter credit

This is the only step that needs a person. Do not try to route around it.

**Ask.** `POST /device/code` with your test key as Bearer, optional `{"name": "<what you are>"}`. You get `user_code`, `device_code`, `verification_uri_complete`, `expires_in` and `interval`. Show your operator `verification_uri_complete` (or `human_message` verbatim), then stop. Do not open a browser yourself, do not mint a second key, do not start a second code.

**Poll.** `POST /device/token` with `{"device_code": "…"}` and **no `Authorization` header** — the device code is the credential. Poll every `interval` seconds and handle exactly four answers:

| Answer | Meaning | What to do |
|---|---|---|
| 400 `authorization_pending` | nobody has clicked yet | normal — keep polling |
| 400 `slow_down` | polling too fast | wait longer, then continue |
| 400 `expired_token` | the code died (`expires_in` seconds) or the key was already collected | **stop**; start a new code only if your operator asks |
| 403 `access_denied` | they declined | **stop**, and do not start another code |

**Collect.** On success you get `api_key` (`zn_live_…`) **exactly once** — store it before doing anything else. The same response carries:

- `starter_credit` — what landed in the wallet. `max_price_cents` is the most a single order can carry, with the per-order fee already deducted. `reason` says `granted`, or why not (`already_granted`, `no_sandbox_order`).
- `sandbox` — the test orders and key that moved onto your operator's account. Your test key keeps working for test mode.

## 4. Buy something real

- **Address.** Ask your operator. `phone_number` is required, and never reuse the sandbox address.
- **Find something.** `GET /search?q=…&max_price=<starter_credit.max_price_cents>` with the live key. Take a result's `url` as `products[0].url`.
- **Order.** `POST /orders` with `max_price` at or under that same number. Confirm the item and the price with your operator first.
- **Not every hit is orderable.** Search ranks across retailers and does not promise every result can be bought. If one comes back `url_unreachable`, take the next result rather than retrying it.
- **Out of money?** `402 insufficient_funds` carries `details.fund_with` — every way to pay, least human involvement first. `GET /wallet/me` shows the balance any time.

## Which retailers work

Pass a product URL from essentially any US retailer; an uncatalogued domain is first class on the order path. `GET /retailers` (free, no auth) lists the storefronts with published guarantees — free-shipping terms, whether an account is needed, which countries they ship to — so check there when those details matter.

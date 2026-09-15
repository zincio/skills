#!/usr/bin/env python3
"""Generate the Zinc checkout skills from one template.

The retailer catalog is driven by the live public `GET https://api.zinc.com/retailers`
endpoint — the single source of truth — so the skills stay in sync automatically.
Everything retailer-specific that matters (name, domain, free-shipping terms)
comes from there; the only things not in the endpoint are an example product URL
(derived from the domain) and which retailers have /products/search (one
constant). Retailer-specific order constraints are NOT hardcoded — the order API
reports them at request time. Adding a retailer needs no code change.

`universal-checkout` is generated from this same template (a `universal` config),
so the shared sections — crucially the Auth/MPP/payment mechanics — can never
drift between the universal skill and the per-retailer skills.

Usage:

    python3 tools/generate_skills.py            # generate from the committed snapshot
    python3 tools/generate_skills.py --refresh  # re-fetch /retailers, update snapshot, generate

`--refresh` writes tools/retailers.json (committed) so builds are reproducible
and catalog changes show up as a reviewable diff.

Each skill is a self-contained folder (SKILL.md + references/errors.md),
installable via `npx skills add zincio/skills --skill <name>`.
Scope: US retailers, full lifecycle (discover -> buy -> track -> return).
"""

import json
import os
import shutil
import sys
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS_DIR = os.path.join(REPO_ROOT, "skills")
SHARED_ERRORS = os.path.join(REPO_ROOT, "references", "errors.md")
SNAPSHOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "retailers.json")
RETAILERS_URL = "https://api.zinc.com/retailers"

# Internal / non-consumer catalog entries we don't publish a checkout skill for.
EXCLUDE = {"zinc"}

# Retailers where GET /products/search + /products/{id}/offers apply.
PRODUCTS_API_RETAILERS = {"amazon", "walmart"}


def load_catalog(refresh):
    """Return the /retailers list, from the live endpoint (--refresh) or snapshot."""
    if refresh:
        with urllib.request.urlopen(RETAILERS_URL, timeout=30) as resp:
            data = json.load(resp)
        with open(SNAPSHOT, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"Refreshed snapshot from {RETAILERS_URL}")
    else:
        if not os.path.exists(SNAPSHOT):
            sys.exit("No tools/retailers.json snapshot — run with --refresh first.")
        with open(SNAPSHOT) as f:
            data = json.load(f)
    return data.get("retailers", data) if isinstance(data, dict) else data


def is_supported(raw):
    # New flat shape uses `supported`; pre-#622 shape used `is_supported`.
    return raw.get("supported", raw.get("is_supported", False))


def free_shipping_terms(raw):
    """Return (free_shipping, threshold_cents) handling both catalog shapes."""
    if "free_shipping" in raw:  # flat #622 shape
        return raw.get("free_shipping"), raw.get("free_shipping_threshold_cents")
    storefronts = raw.get("storefronts") or []
    us = next((s for s in storefronts if s.get("country") == "US"), None)
    sf = us or (storefronts[0] if storefronts else {})
    return sf.get("free_shipping"), sf.get("free_shipping_threshold_cents")


def build_retailers(catalog):
    """Turn the live catalog into render configs. No per-retailer overlay."""
    configs = []
    for raw in catalog:
        slug = raw.get("retailer")
        if not slug or slug in EXCLUDE or not is_supported(raw):
            continue
        domain = raw.get("base_url") or slug
        fs, threshold = free_shipping_terms(raw)
        configs.append({
            "slug": slug,
            "display": raw.get("display_name") or slug,
            "domain": domain,
            "example_url": f"https://www.{domain}/<product-page>",
            "psearch": slug in PRODUCTS_API_RETAILERS,
            "free_shipping": fs,  # None when the catalog doesn't expose it
            "ship_threshold_cents": threshold,
            "is_universal": False,
        })
    return configs


# The `universal` config renders skills/universal-checkout/ from this same
# template. A real example URL (Amazon) shows the request schema.
UNIVERSAL = {
    "slug": "universal",
    "display": "Zinc Universal Checkout",
    "domain": "zinc.com",
    "example_url": "https://www.amazon.com/dp/B09V3KXJPB",
    "psearch": True,  # universal covers the products API (Amazon & Walmart)
    "free_shipping": None,
    "ship_threshold_cents": None,
    "is_universal": True,
}

# --- Template --------------------------------------------------------------
# Retailer-specific phrasing is injected via the tokens computed in
# `variant_tokens()` so the ONE body below serves both the per-retailer skills
# and universal-checkout. The shared sections (Auth/MPP, order mechanics,
# tracking, returns, errors, safety) are literal here and identical everywhere.

FRONTMATTER = """---
name: {{NAME}}
description: {{DESCRIPTION}}
---
"""

BODY = """
# {{TITLE}}

{{INTRO}}

{{POWERED_NOTE}}

## Getting started

Four steps, in order. Full walkthrough: [Agent Sandbox Quickstart](https://www.zinc.com/docs/v2/agent-sandbox/quickstart.md) and [Going Live](https://www.zinc.com/docs/v2/agent-sandbox/going-live.md).

1. **Get a test key.** `POST https://api.zinc.com/sandbox/keys` — no auth, no signup. Returns `api_key` (`zn_test_…`) and a ready-made `example_order`. Send it as `Authorization: Bearer <api_key>` from here on.
2. **Place a test order.** `POST /orders` with that `example_order`, then poll `GET /orders/{id}`. Free. `status` reaches **`order_placed`** — that is success, and it never becomes `delivered`; shipping shows up under `tracking_numbers[0].status`.
3. **Earn your live key.** `POST /device/code`, show your operator the link it returns, and poll `POST /device/token` (400 `authorization_pending` means keep waiting). On approval you get a `zn_live_` key **once**, plus a **$5 starter credit** in their wallet (`starter_credit.max_price_cents` is what one order can carry).
4. **Buy something real.** {{FIRST_BUY}}

Already have a key from your operator? Use it and skip to **Place an order**. Never want an account? Pay per request over [MPP](https://www.zinc.com/docs/v2/mpp.md): `POST /agent/orders`, no key needed.

## Place an order

```bash
curl -X POST https://api.zinc.com/orders \\
  -H "Authorization: Bearer $ZINC_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "products": [{"url": "{{EXAMPLE_URL}}", "quantity": 1}],
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

Errors are `{"error": {"code", "message", "details"}}`. Read `code`, not the message. `details` often names the fix — a `402 insufficient_funds` carries `fund_with`, every way to pay. Full list: [Error Handling](https://www.zinc.com/docs/v2/api-reference/introduction/error-handling.md) and [references/errors.md](https://github.com/zincio/skills/blob/master/skills/{{SLUG}}-checkout/references/errors.md).

## Rules

- **Money is real.** Confirm the item and the price with your operator before any live order.
- **Set `max_price` deliberately** — it is the only thing standing between a typo and a large purchase.
- **Never invent a shipping address**, and never reuse the sandbox one for a live order.
- Rehearse failures in the sandbox first: `GET /orders/test-products`.

All amounts are in **US cents** (e.g. `5000` = $50.00). US delivery.
"""


RETAILER_PRODUCT_SEARCH = """

{{DISPLAY}} is one of the few retailers with richer product data (currently Amazon & Walmart only). For best-price comparison, use `GET /products/search?query=<term>&retailer={{SLUG}}` (returns `product_id`, `price`, `ship_price`, `stars`, …) and `GET /products/{product_id}/offers?retailer={{SLUG}}` to compare offers by **price and condition** before ordering. On the MPP rail these are `POST /agent/products/search`, `POST /agent/products/offers`, and `POST /agent/products/details` (query param `product_id=…&retailer={{SLUG}}`), $0.01 per call."""

UNIVERSAL_PRODUCT_SEARCH = """

**Richer product data (Amazon & Walmart only).** For best-price comparison on those two, use `GET /products/search?query=<term>&retailer=amazon|walmart` (returns `product_id`, `price`, `ship_price`, `stars`, …) and `GET /products/{product_id}/offers?retailer=amazon|walmart` to compare offers by **price and condition** before ordering. On the MPP rail these are `POST /agent/products/search`, `POST /agent/products/offers`, and `POST /agent/products/details`, $0.01 per call."""

RETAILER_DESCRIPTION = (
    "Discover, buy, track, and return real products from {{DISPLAY}} ({{DOMAIN}}) through "
    "the Zinc API (zinc.com) — and from almost any other US retailer on the same API. "
    "Needs no account to begin — the agent mints its own test key, then earns a live key "
    "and a $5 starter credit once its operator approves it. Pay from a pre-funded wallet, "
    "per request over MPP or x402, or with a Stripe Link card."
)

UNIVERSAL_DESCRIPTION = (
    "Discover, buy, track, and return real products from Amazon, Walmart, Target and "
    "almost any other US online retailer through the Zinc API (zinc.com). Needs no "
    "account to begin — the agent mints its own test key, then earns a live key and a $5 "
    "starter credit once its operator approves it. Pay from a pre-funded wallet, per "
    "request over MPP or x402, or with a Stripe Link card."
)

UNIVERSAL_FIRST_BUY = (
    "Walmart is the best-covered retailer, so search there first: "
    "`GET /search?q=<item> walmart`. **`max_price` is a ceiling, not a price** — you are "
    "charged the retailer's actual total, so set it a little above the listed price to "
    "leave room for tax and shipping. Ask your operator for the shipping address "
    "(**`phone_number` is required**) and confirm the item and price with them first."
)

RETAILER_FIRST_BUY = (
    "`POST /orders` with a {{DOMAIN}} product URL. **`max_price` is a ceiling, not a "
    "price** — you are charged the retailer's actual total, so set it a little above the "
    "listed price to leave room for tax and shipping. Ask your operator for the shipping "
    "address (**`phone_number` is required**) and confirm the item and price with them "
    "first."
)

RETAILER_POWERED_NOTE = (
    "> **Powered by Zinc Universal Checkout.** The same API buys from {{DISPLAY}} and "
    "almost any other US retailer. To order "
    "across multiple retailers from one skill, install the "
    "[`universal-checkout`](https://github.com/zincio/skills/tree/master/skills/universal-checkout) "
    "skill (`npx skills add zincio/skills --skill universal-checkout`). Live retailer list: "
    "`GET https://api.zinc.com/retailers`."
)

UNIVERSAL_POWERED_NOTE = (
    "## Which retailers\n"
    "\n"
    "Pass a product URL from almost any US retailer — an uncatalogued domain is first "
    "class on the order path, and in a recent 60-day window customers ordered from 296 "
    "distinct domains. `GET /retailers` (free, no auth) lists the storefronts with "
    "published guarantees: free-shipping terms, whether an account is needed, where they "
    "ship. Check it when those details matter."
)

RETAILER_FIND_INTRO = (
    "If the user already has a {{DISPLAY}} product URL, skip to **Place an order**. "
    "Otherwise search for one:"
)
UNIVERSAL_FIND_INTRO = (
    "If the user gives you a product URL, skip to **Place an order**. Otherwise find an "
    "orderable product first:"
)

RETAILER_FIND_FILTER = (
    "`GET /search` returns `{ status, query, results: [...] }` across retailers; each "
    "result has a directly **orderable `url`** plus `retailer`, `title`, `price` (cents), "
    "`stars`. Filter results to `retailer == \"{{SLUG}}\"` for {{DISPLAY}}-only, then pass "
    "the `url` into an order."
)
UNIVERSAL_FIND_FILTER = (
    "`GET /search` returns `{ status, query, results: [...] }` across retailers; each "
    "result has a directly **orderable `url`** plus `retailer`, `title`, `price` (cents), "
    "`stars`, `available`. Pass a result's `url` straight into an order."
)


def _dollars(cents):
    """cents -> '$45' for whole dollars, '$45.99' when there are cents."""
    return f"${cents // 100}" if cents % 100 == 0 else f"${cents / 100:.2f}"


def shipping_note(r):
    """Free-shipping line, from /retailers fields. Empty when not exposed."""
    fs = r.get("free_shipping")
    th = r.get("ship_threshold_cents")
    if fs is None:
        return ""
    if fs is False:
        return ("**Shipping:** {{DISPLAY}} has no flat free-shipping threshold — "
                "shipping is added per order, so leave room for it in `max_price`.")
    if th == 0:
        return "**Shipping:** {{DISPLAY}} ships free on all orders."
    if th is None:
        return ("**Shipping:** {{DISPLAY}} offers free shipping on qualifying orders; "
                "below the threshold shipping is added — leave room in `max_price`.")
    return (f"**Shipping:** {{{{DISPLAY}}}} ships free on orders over {_dollars(th)}; "
            "below that, shipping is added to the total — leave room in `max_price`.")


def notes_section(r):
    """The optional '## Retailer notes' block — only when /retailers gives us
    something real to say. Universal has no single-retailer shipping terms."""
    if r.get("is_universal"):
        return ""
    sn = shipping_note(r)
    if not sn:
        return ""
    return "## Retailer notes\n\n" + sn + "\n\n"


def variant_tokens(r):
    """Retailer-specific vs universal phrasing for the shared body."""
    if r.get("is_universal"):
        return {
            "NAME": "universal-checkout",
            "DESCRIPTION": UNIVERSAL_DESCRIPTION,
            "TITLE": "Universal Checkout",
            "INTRO": (
                "One API to discover, buy, track and return products from US online "
                "retailers. "
                "Base URL `https://api.zinc.com`."
            ),
            "POWERED_NOTE": UNIVERSAL_POWERED_NOTE,
            "FIND_INTRO": UNIVERSAL_FIND_INTRO,
            "FIND_FILTER": UNIVERSAL_FIND_FILTER,
            "URL_DESC": "Direct product page URL on a supported retailer",
            "PRODUCT_SEARCH": UNIVERSAL_PRODUCT_SEARCH,
            "FIRST_BUY": UNIVERSAL_FIRST_BUY,
        }
    return {
        "NAME": f"{r['slug']}-checkout",
        "DESCRIPTION": RETAILER_DESCRIPTION,
        "TITLE": "{{DISPLAY}} Checkout",
        "INTRO": (
            "Buy, track, and return products from {{DISPLAY}} ({{DOMAIN}}) through the "
            "Zinc API (`https://api.zinc.com`). US orders."
        ),
        "POWERED_NOTE": RETAILER_POWERED_NOTE,
        "FIND_INTRO": RETAILER_FIND_INTRO,
        "FIND_FILTER": RETAILER_FIND_FILTER,
        "URL_DESC": "Direct {{DISPLAY}} product page URL (on {{DOMAIN}})",
        "PRODUCT_SEARCH": RETAILER_PRODUCT_SEARCH if r["psearch"] else "",
        "FIRST_BUY": RETAILER_FIRST_BUY,
    }


def render(r):
    tok = variant_tokens(r)
    out = FRONTMATTER + BODY
    # Inject variant sections first (they contain {{DISPLAY}}/{{SLUG}} tokens
    # that the final pass resolves).
    for key, val in tok.items():
        out = out.replace("{{" + key + "}}", val)
    out = out.replace("{{NOTES_SECTION}}", notes_section(r))
    # Retailer tokens last so they reach injected blocks too.
    out = out.replace("{{DISPLAY}}", r["display"])
    out = out.replace("{{SLUG}}", r["slug"])
    out = out.replace("{{DOMAIN}}", r["domain"])
    out = out.replace("{{EXAMPLE_URL}}", r["example_url"])
    return out


README = os.path.join(REPO_ROOT, "README.md")
TABLE_START = "<!-- SKILLS-TABLE:START (generated by tools/generate_skills.py — do not edit by hand) -->"
TABLE_END = "<!-- SKILLS-TABLE:END -->"


def update_readme_table(retailers):
    """Rewrite the skills table in README.md between the markers."""
    rows = [
        "| Skill | Buys from | Install |",
        "|-------|-----------|---------|",
        "| [`universal-checkout`](skills/universal-checkout/SKILL.md) | **Universal** — all supported retailers | `npx skills add zincio/skills --skill universal-checkout` |",
    ]
    for r in retailers:
        s = r["slug"]
        rows.append(
            f"| [`{s}-checkout`](skills/{s}-checkout/SKILL.md) | {r['display']} | "
            f"`npx skills add zincio/skills --skill {s}-checkout` |"
        )
    block = TABLE_START + "\n" + "\n".join(rows) + "\n" + TABLE_END
    with open(README) as f:
        text = f.read()
    if text.count(TABLE_START) != 1 or text.count(TABLE_END) != 1:
        sys.exit(
            f"README.md must contain exactly one {TABLE_START!r} and one "
            f"{TABLE_END!r} (found {text.count(TABLE_START)} / {text.count(TABLE_END)})."
        )
    pre, _, rest = text.partition(TABLE_START)
    _, _, post = rest.partition(TABLE_END)
    with open(README, "w") as f:
        f.write(pre + block + post)


def write_skill(r):
    """Render one skill folder (SKILL.md + shared errors.md). Returns folder name."""
    folder_name = f"{r['slug']}-checkout"
    folder = os.path.join(SKILLS_DIR, folder_name)
    refs = os.path.join(folder, "references")
    os.makedirs(refs, exist_ok=True)
    with open(os.path.join(folder, "SKILL.md"), "w") as f:
        f.write(render(r))
    shutil.copyfile(SHARED_ERRORS, os.path.join(refs, "errors.md"))
    return folder_name


def main():
    refresh = "--refresh" in sys.argv[1:]
    catalog = load_catalog(refresh)
    retailers = build_retailers(catalog)

    # universal-checkout is generated from the same template as the retailers,
    # so the shared sections (esp. Auth/MPP) can never drift.
    written = [write_skill(UNIVERSAL)]
    for r in retailers:
        written.append(write_skill(r))

    # Prune stale generated skills: a retailer dropped or renamed in the catalog
    # leaves a `<slug>-checkout/` folder that would still be installable.
    keep = set(written)
    removed = []
    for entry in sorted(os.listdir(SKILLS_DIR)) if os.path.isdir(SKILLS_DIR) else []:
        path = os.path.join(SKILLS_DIR, entry)
        if os.path.isdir(path) and entry.endswith("-checkout") and entry not in keep:
            shutil.rmtree(path)
            removed.append(entry)

    update_readme_table(retailers)

    print(f"Generated {len(written)} skills from {len(catalog)} cataloged retailers:")
    for w in written:
        print(f"  skills/{w}/")
    if removed:
        print(f"Pruned {len(removed)} stale skill(s): {', '.join(removed)}")
    print("Updated README skills table.")


if __name__ == "__main__":
    main()

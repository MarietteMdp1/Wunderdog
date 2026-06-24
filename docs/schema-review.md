# Refill — Database Schema Review

**Prepared for:** Refill (startup) — to share with the build company
**Date:** 2026-06-23
**Scope:** Review of the Prisma-generated database schema (`schema.dbml`, 17 tables + 2 implicit join tables), cross-checked against the current frontend (static HTML prototype).
**ER diagrams:**
- Current schema: https://whimsical.com/7dhgC48Pvtd5erzvJhZx3h
- Proposed schema: _(see second diagram link supplied with this report)_

> **Note on validation.** This review was cross-checked against the **live API OpenAPI spec** (`api.refill-app.com/api-docs-json`, NestJS, API `v1`). The reconciliation is in **§7** — it **confirms all three structural findings below**. Items still marked _“confirm with build team”_ depend on backend internals not visible in the spec.

---

## 1. Executive summary

The schema is competently built: consistent audit/soft-delete columns everywhere, sensible enums for state machines, money stored as `Decimal`, and good unique constraints in most places. It models a UAE-based subscription delivery business (packages → tiered pricing → subscriptions → orders → courier delivery by zone).

However, there are **three structural gaps** that should be addressed before scale, plus a set of smaller correctness/operational issues:

1. **Denormalization** — subscription packages stored as a string array; order contents stored *both* as JSON *and* as join tables (two sources of truth).
2. **Missing payments/transactions model** — the frontend renders a full “Payment History” (Scheduled / Paid / Failed + Retry) and there are two unused enums (`TransactionType`, `TransactionStatus`), but **no table exists to store any of it**.
3. **Missing constraints & indexes** — no unique guard on package tiers, no indexes on foreign keys, and soft-delete collides with unique columns.

---

## 2. Denormalization issues

### 2.1 `active_plans.packageIds String[]` should be a join table

A subscription stores its packages as a bare `String[]`. This cannot be foreign-key enforced, cannot be cleanly joined ("which plans contain package X?" requires array ops), and silently rots if a package is deleted. It is also **inconsistent** with how orders already model the same relationship (via a join table).

**Fix** — introduce an explicit join table mirroring `package_products`, and snapshot the tier per package:

```prisma
model ActivePlanPackage {
  id            String       @id @default(cuid())
  activePlanId  String
  activePlan    ActivePlan   @relation(fields: [activePlanId], references: [id])
  packageId     String
  package       Package      @relation(fields: [packageId], references: [id])
  packageTierId String?      // snapshot tier at purchase time
  packageTier   PackageTier? @relation(fields: [packageTierId], references: [id])

  createdAt DateTime @default(now())
  // ...standard audit columns

  @@unique([activePlanId, packageId])
  @@index([packageId])
}
```

Then remove `packageIds String[]` and `packageTierLevel` from `active_plans` (tier now lives per package, allowing different tiers per package within one plan).

### 2.2 `orders.basket Json` duplicates `OrderToProduct` / `OrderToPackage`

Order contents currently live in **two** places: the opaque `basket` JSON **and** the two implicit many-to-many relations. Nothing keeps them in sync, and it is ambiguous which is authoritative — a guaranteed drift bug.

**Fix** — collapse to a single order-line-items table that also captures a **price snapshot** (the JSON blob is likely the only current record of what was actually charged):

```prisma
model OrderItem {
  id        String   @id @default(cuid())
  orderId   String
  order     Order    @relation(fields: [orderId], references: [id])
  productId String?  // exactly one of product / package is set
  product   Product? @relation(fields: [productId], references: [id])
  packageId String?
  package   Package? @relation(fields: [packageId], references: [id])

  quantity  Int
  unitPrice Decimal  @db.Decimal(10, 2)  // snapshot at order time
  currency  String                        // snapshot (see §4)

  createdAt DateTime @default(now())
  // ...audit columns

  @@index([orderId])
  @@index([productId])
  @@index([packageId])
}
```

Then remove `basket Json` and the implicit `products`/`packages` M:N relations from `orders` (and the generated `OrderToProduct` / `OrderToPackage` tables). One source of truth, FK-enforced, price-preserving.

---

## 3. Missing payments / transactions model

This is the most significant functional gap.

**Evidence it is needed:**
- The frontend (`account.html`) renders a **Payment History** panel: discrete records with a payment number (e.g. `#67888`), date, AED amount, and status **Scheduled / Paid / Failed**, including a **Retry** button on failures and a “View all payments” link.
- The schema can store none of this. The only payment-related field is `orders.status = PAYMENT_PENDING` — a single status flag, no amount, no gateway reference, no failure reason, no retry, no per-charge history. A subscription bills repeatedly over time, so payments are inherently a one-to-many child of plan/order.
- Two enums exist but are referenced by **no table**: `TransactionType { SPEND, EXPIRED }` and `TransactionStatus { INCOMPLETE, COMPLETED, FAILED }`. These are strong evidence a table was specced and never built.
- `users.stripeCustomerId` exists, confirming Stripe integration — but there is nowhere to record the resulting charges.

**Validated against the live API (see §7):** there are **no** `/payments`, `/transactions`, `/invoices`, or `/billing` endpoints. Instead, payment is **delegated entirely to Stripe** — orders carry a `paymentLink` and `stripeProductId`, and `active_plans.metadata` holds `gatewayCheckoutId` / `gatewaySubscriptionId`. So Stripe is currently the **system of record** for money; nothing is persisted locally.

This is a legitimate architecture, but it has real costs the team should weigh deliberately rather than by default:
- The frontend’s **Payment History** panel has no local source — it must either be mocked, derived from order status, or fetched live from Stripe on every view (rate-limit and latency risk). **Confirm how that panel is actually populated.**
- No local ledger means **no queryable billing history, no reconciliation, no revenue reporting** without calling Stripe, and no resilience if a Stripe webhook is missed.
- Critical payment linkage (`gatewaySubscriptionId`, `gatewayCheckoutId`) lives in **untyped JSON `metadata`** rather than typed, indexed columns — hard to query, easy to typo, no FK/uniqueness guarantees.

**Recommendation:** keep Stripe as the payment processor, but persist a local `Payment` mirror (populated from Stripe webhooks) as the queryable system of record for history/reporting. Promote `gatewaySubscriptionId` / `gatewayCheckoutId` out of JSON into typed columns on `active_plans`.

**Recommended `Payment` table:**

```prisma
model Payment {
  id                    String        @id @default(cuid())
  userId                String
  user                  User          @relation(fields: [userId], references: [id])
  orderId               String?
  order                 Order?        @relation(fields: [orderId], references: [id])
  activePlanId          String?
  activePlan            ActivePlan?   @relation(fields: [activePlanId], references: [id])

  amount                Decimal       @db.Decimal(10, 2)
  currency              String
  status                PaymentStatus @default(PENDING)  // see note below
  stripePaymentIntentId String?       @unique
  failureReason         String?
  scheduledFor          DateTime?     // "Scheduled" rows in the UI
  paidAt                DateTime?

  createdAt DateTime @default(now())
  // ...audit columns

  @@index([userId])
  @@index([orderId])
  @@index([activePlanId])
}
```

**Important — decide what the existing enums mean before wiring anything up.**
`TransactionStatus { INCOMPLETE, COMPLETED, FAILED }` maps cleanly to money payments. But `TransactionType { SPEND, EXPIRED }` does **not** read like money — `SPEND`/`EXPIRED` is the vocabulary of a **credits / refill ledger**. Combined with the refill counters on `active_plans` (`refillGranted` / `refillRemaining` / `refillUsed`), the original intent looks like **two** ledgers:

1. a money `Payment` table (Stripe charges), and
2. a refill-credit `Transaction` table tracking when refills are **spent** or **expire**.

If so, give `Payment` its own `PaymentStatus` enum and keep `TransactionType` for the refill ledger:

```prisma
model RefillTransaction {
  id           String            @id @default(cuid())
  activePlanId String
  activePlan   ActivePlan        @relation(fields: [activePlanId], references: [id])
  orderId      String?           // the refill order that consumed it
  order        Order?            @relation(fields: [orderId], references: [id])
  type         TransactionType   // SPEND | EXPIRED
  status       TransactionStatus
  amount       Int               // number of refills
  createdAt    DateTime          @default(now())

  @@index([activePlanId])
}
```

This also closes issue §4.1 (refill orders currently have no link to the plan they draw down).

> **Confirm with build team:** is `SPEND`/`EXPIRED` money or refill-credits? Picking wrong is expensive to migrate later. Also confirm whether a payments/transactions table already exists in the live API but is simply not represented in this DBML.

---

## 4. Other issues found

### High priority

**4.1 No `planId` link on orders.** A `REFILL` order cannot be traced back to the `active_plan` it draws from. Refill accounting lives entirely in counter columns with no transactional link — you cannot audit *why* `refillUsed` has its value. Add `activePlanId String?` to `orders`; the `RefillTransaction` ledger (§3) makes the drawdown auditable.

**4.2 Referrals feature with no data model.** `referrals.html` is a full referral page with reward cards, but there is no `referrals` table, no referral code on `users`, and no reward ledger. Either the page is currently marketing-only, or an entire entity is missing. _Confirm with build team._

**4.3 Currency captured almost nowhere.** Only `package_tiers` has a `currency`. Orders, plans, and (today) the basket do not snapshot it. If Refill ever charges in a non-AED currency or changes pricing, historical orders become unreadable. Snapshot `currency` + `unitPrice` on every line item and payment (folded into §2.2 and §3).

### Medium priority

**4.4 No indexes on foreign keys.** PostgreSQL does **not** auto-index FK columns. `orders.userId`, `orders.courierId`, `orders.addressId`, `addresses.userId`, `notifications.userId`, etc. will do sequential scans on join/filter. Prisma only emits indexes when asked — add `@@index` on every FK. At delivery-app scale this is the difference between snappy and slow dashboards.

**4.5 Soft-delete collides with unique constraints.** `users.email` / `users.phoneNumber` are `@unique` and deletion is soft (`deletedAt`). A user who deletes their account and re-registers with the same email will hit a unique violation, because the soft-deleted row still holds the value. Fix with a partial unique index (`WHERE deletedAt IS NULL`) or by including `deletedAt` in the key. Same risk on every `@@unique` (`addresses`, `package_products`).

**4.6 `audits.request` / `audits.response` are unbounded JSON.** Storing full request *and* response bodies on every call is the most common cause of runaway DB growth. Add a retention/TTL policy and consider truncating large payloads.

**4.7 Non-null JSON columns without defaults.** `active_plans.metadata`, `orders.basket`, `notifications.metadata` are `Json [not null]` with no default — every insert must pass a blob (even `{}`). Add `@default("{}")` or make them nullable.

### Lower priority / confirm intent

**4.8 Missing unique on `package_tiers`.** Nothing prevents two `STANDARD` tiers for the same package. Add `@@unique([packageId, level, currency])` (drop `currency` if always single-currency).

**4.9 Enum naming.** `orders.status` reuses `OrderLogStatus` — the order borrows the log’s enum name, suggesting the order state machine was an afterthought. Consider a dedicated `OrderStatus` for clarity.

**4.10 Delivery capacity race condition.** `delivery_schedules.deliveryCount` / `availableDeliveryCount` are mutated in place while `delivery_schedule_logs` snapshots them. Ensure decrements run inside a transaction — two orders could otherwise both grab the last slot.

**4.11 Float columns in a unique key.** `addresses` is unique on `(userId, deliveryZoneId, latitude, longitude)`. Floats in a unique key are fragile (precision/rounding means “same” addresses may not dedupe). Round to fixed precision or use a geohash column.

---

## 5. Suggested priority order

1. **Payments/transactions model** (§3) — blocks the billing feature the UI already shows.
2. **Order line items** (§2.2) — removes the JSON-vs-join drift and preserves price history.
3. **FK indexes + soft-delete/unique fixes** (§4.4, §4.5) — cheap, high impact, easy to retrofit early.
4. **`active_plans` join table** (§2.1) and **refill→plan link** (§4.1).
5. **Constraints & cleanups** (§4.3, §4.6–4.11).

## 6. Open questions for the build company

- Does a payments/transactions table already exist in the live API but not in this DBML?
- Is `TransactionType { SPEND, EXPIRED }` intended for money or refill-credits?
- What is the intended data model behind the referrals page?
- Is soft-delete + unique-email re-registration a supported flow?

---

## 7. Reconciliation against the live API (OpenAPI spec)

Checked against `api.refill-app.com/api-docs-json` (NestJS, version `v1`, JWT Bearer + OTP auth). Summary: **the schema review holds; the live API confirms the three structural gaps.**

### Endpoint groups present
Addresses (+ `/slots`), Delivery (zones / schedules / schedule-logs / slot aggregation), Orders (CRUD, `/cancel`, `/stats`, `/active`, `/log`, `/logs`, `transaction/cancel`), Active Plans (list / get / cancel), Packages (+ package-products, package-tiers), Products, Storages, Users (+ `/me`, delete-account), Auth (OTP login / verify / refresh / onboard), Notifications, Contacts, Health.

### Confirmed ABSENT (validates the review)
| Gap | Review ref | Live API status |
|---|---|---|
| Payments / transactions | §3 | **No** `/payments`, `/transactions`, `/invoices`, `/billing` endpoints. Payment delegated to Stripe (`paymentLink`, `stripeProductId`, `gatewayCheckoutId`, `gatewaySubscriptionId`). |
| Referrals | §4.2 | **No** `/referrals` endpoints at all → the referrals page is **frontend-only** today. |
| Promo codes / discounts | (new) | None in spec. |
| Webhooks | (new) | None visible — relevant if Stripe is the payment source of record (how are charges reconciled?). |

### New details the spec surfaced
- **`orders/transaction/cancel`** exists — “transaction” terminology already appears in the order/refill flow, reinforcing that `TransactionType { SPEND, EXPIRED }` is likely the **refill-credit ledger** (§3), not money. _Confirm with build team._
- **Stripe linkage lives in JSON** — `gatewaySubscriptionId` / `gatewayCheckoutId` in `active_plans.metadata`, `stripeProductId` in the order basket. Promote to typed columns (§3).
- **OTP-only auth, no password field** — reinforces §4.5: account identity is the phone/email, so the soft-delete + unique-constraint collision on re-registration is a live risk, not theoretical.
- **`active_plans` exposes only list/get/cancel** — no create endpoint, consistent with plans being created as a side effect of a (Stripe) checkout flow. Worth confirming the creation path is transactional.

### Net effect on recommendations
No changes to the proposed schema. Two reframings:
1. **Payments (§3)** is now explicitly a *“Stripe-delegated vs. local mirror”* decision, not an oversight — recommend a webhook-fed local `Payment` mirror for queryable history/reporting.
2. **Referrals (§4.2)** is confirmed unbuilt on the backend — a full feature (table + endpoints), not just a missing table.
```

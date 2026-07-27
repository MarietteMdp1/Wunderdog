# SEO Audit — refill-launch-demo.vercel.app

**Date:** 2026-07-27
**Scope:** All 7 HTML pages in this repository, which is the source of the Vercel deployment (`index.html`, `account.html`, `deliveries.html`, `dog-detail.html`, `my-dogs.html`, `my-plans.html`, `referrals.html`).

---

## Executive summary

This site is a **logged-in customer account dashboard** (Wunderdog refill/subscription portal) published as a static demo on a public Vercel URL. That context drives the single most important conclusion of this audit:

> **This site should not be indexed by search engines at all — and right now, nothing prevents it.** There is no `robots.txt`, no `noindex` directive, and no access protection. Worse, the pages contain real personal information (full name, personal Gmail address, phone number, delivery location), which any search engine can crawl, index, and cache.

The audit is therefore split in two parts:

1. **Part A — what to do for this demo as it exists** (protect it, de-index it, remove personal data).
2. **Part B — the standard SEO gaps found**, which matter if any of this becomes a public-facing marketing page, and are good hygiene regardless.

---

## Part A — Critical: indexing & privacy

### A1. Real personal data is publicly crawlable — CRITICAL

`account.html` publishes, on an unauthenticated public URL:

- Full name: *Mariette Du Plessis* (also in the `index.html` H1 greeting)
- Personal email: *duplessis.mariette@gmail.com*
- Delivery address: *Aktio Marine, Ajman City Center*
- A WhatsApp/phone number appears on multiple pages (`+971 50 229 8869`)

Once Google indexes this, the email and name become searchable and cached — removal afterwards is slow and unreliable.

**Fix (do at least one, ideally all):**
- Replace real personal data with fictional demo data (e.g. "Jane Demo", "jane@example.com").
- Enable **Vercel Deployment Protection** (password / Vercel Authentication) so the demo isn't publicly reachable.
- Add `noindex` (see A2) as a safety net.

### A2. No indexing controls — CRITICAL

There is no `robots.txt`, no `<meta name="robots">`, and no `X-Robots-Tag` header. For an account-area demo, the correct posture is full de-indexing:

**Fix — add to the `<head>` of every page:**
```html
<meta name="robots" content="noindex, nofollow">
```

**And/or add a `vercel.json` so the header covers everything (including images):**
```json
{
  "headers": [
    {
      "source": "/(.*)",
      "headers": [{ "key": "X-Robots-Tag", "value": "noindex, nofollow" }]
    }
  ]
}
```

Note: `robots.txt` with `Disallow: /` alone is **not** enough — it blocks crawling but the URL can still appear in results if linked elsewhere. `noindex` is the reliable mechanism.

---

## Part B — Standard SEO findings

These are ranked by severity. Items marked *(only if public/marketing)* matter only for pages meant to rank.

### B1. Missing meta descriptions — High *(only if public/marketing)*
No page has a `<meta name="description">`. Search engines will synthesize snippets from dashboard UI text ("Hello, Mariette!", stat card labels), which would look broken in results.

### B2. No Open Graph / Twitter Card tags — High
When the demo link is shared (WhatsApp, Slack, LinkedIn — likely for a demo!), no title, description, or preview image renders. This is worth fixing even for a private demo.

```html
<meta property="og:title" content="Wunderdog — Refill Dashboard Demo">
<meta property="og:description" content="Customer portal demo for Wunderdog fresh dog food subscriptions.">
<meta property="og:image" content="https://refill-launch-demo.vercel.app/og-image.png">
<meta property="og:type" content="website">
<meta name="twitter:card" content="summary_large_image">
```

### B3. No canonical URLs — Medium
No page declares `<link rel="canonical">`. `dog-detail.html` is reachable with query variants (`?dog=bonnie`, `?dog=clyde`, `?dog=jack`), which creates three duplicate URLs of the same document with different client-side content. If this pattern ever goes public, each variant needs a canonical (or the content should be server-rendered per dog).

### B4. Generic page titles — Medium *(only if public/marketing)*
Titles follow the app pattern `Dashboard - Wunderdog`, `Account - Wunderdog`, etc. Fine for a logged-in app; useless for search. Public pages should follow `Primary Keyword — Brand` (under ~60 chars) with unique, descriptive titles. Minor inconsistency: `my-plans.html` is titled "My Plan" (singular) — harmless, but worth aligning file name and title.

### B5. No sitemap.xml — Medium *(only if public/marketing)*
No sitemap exists and no `robots.txt` references one. For a 7-page demo this is trivial to add, but do **not** add one while the site is meant to be noindexed — a sitemap invites crawling.

### B6. Dead / placeholder links — Medium
- `href="index.html#"` appears **12×** and `href="#"` **8×** (buttons and stub links).
- Crawlers follow these as real URLs; screen readers announce them as links that go nowhere.

**Fix:** use `<button>` elements for actions, or real destinations for links.

### B7. Image issues — Medium
- The nose icon is used ~20× with `alt="nose"`. It is purely decorative, so the correct value is empty: `alt=""` (plus `aria-hidden="true"`). "nose" as alt text is noise for both accessibility and image SEO.
- Product images in `my-plans.html` are **hotlinked from the production WordPress site** (`mywunderdog.com/wp-content/uploads/...`). They have vague alts ("Turkey", "Chicken", "Camel") instead of the full product names, no `width`/`height` (layout shift risk), and no `loading="lazy"`. Hotlinking also means the demo breaks if production renames a file.

**Fix:** self-host the images, set explicit dimensions, add `loading="lazy"`, and use descriptive alts (e.g. `alt="1kg Turkey with Honey — Wunderdog fresh dog food"`).

### B8. Performance / Core Web Vitals — Low-Medium
The site is small and static, so it's fast, but easy wins remain:

- **All CSS is inlined and duplicated in every page** (~150 KB of HTML total, the shared styles repeated 7×). Extract the shared rules to one cached stylesheet. (Ironically, `styles.css` and `scripts.js` exist but are unused placeholder stubs — either use them or delete them.)
- **Google Fonts is render-blocking** with no preconnect. Add:
  ```html
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  ```
  (`display=swap` is already used — good.)

### B9. Missing favicon — Low
No favicon or `apple-touch-icon` is declared on any page; browsers request `/favicon.ico` and 404. Cosmetic, but visible in every shared-tab screenshot of a demo.

### B10. No structured data — Low *(only if public/marketing)*
No schema.org markup anywhere. Not needed for an account UI; if Wunderdog builds public product/marketing pages, add `Organization`, `Product` + `Offer`, and `FAQPage` JSON-LD there.

### B11. No custom 404 page — Low
Vercel serves its default 404 for unknown paths. A branded `404.html` (Vercel picks it up automatically for static deploys) is a one-file fix.

---

## What's already good

- ✅ Exactly **one `<h1>` per page**, with sensible `<h2>` subsections.
- ✅ `<html lang="en">`, UTF-8 charset, and a proper responsive viewport meta on every page.
- ✅ Consistent internal navigation — every page links to every other page with clean relative URLs.
- ✅ Font loading uses `display=swap`.
- ✅ Small, dependency-free static pages — a solid performance baseline.

---

## Prioritized action plan

| # | Action | Effort | Impact |
|---|--------|--------|--------|
| 1 | Replace real personal data with fictional demo data | Low | Critical (privacy) |
| 2 | Add `noindex, nofollow` meta + `X-Robots-Tag` via `vercel.json` (or enable Vercel password protection) | Low | Critical |
| 3 | Add Open Graph/Twitter tags so shared demo links preview properly | Low | High |
| 4 | Fix decorative icon alts (`alt=""`), self-host product images with dimensions + lazy loading | Low | Medium |
| 5 | Replace `href="#"` stubs with `<button>` elements | Low | Medium |
| 6 | Extract duplicated inline CSS to a shared stylesheet; add font preconnect; delete or use stub `styles.css`/`scripts.js` | Medium | Medium |
| 7 | Add favicon and a custom `404.html` | Low | Low |
| 8 | *(Only if pages go public)* Unique titles + meta descriptions, canonicals, sitemap.xml + robots.txt, structured data | Medium | High for ranking |

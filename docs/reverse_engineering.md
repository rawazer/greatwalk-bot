# DOC Booking Site — Reverse Engineering (Milestone 0)

Investigation of [https://bookings.doc.govt.nz/Web/](https://bookings.doc.govt.nz/Web/) conducted June 2026. This milestone is **read-only** — no login, no bookings, no WAF bypass attempts.

## Executive summary

| Question | Finding |
|----------|---------|
| How is availability loaded? | JSON REST calls from the browser to **Tyler Recreation Management RDR API** (`prod-nz-rdr.recreation-management.tylerapp.com`) |
| JSON/XHR/Fetch? | Yes — jQuery `$.ajax` / `$.getJSON` and ClojureScript/React SPA fetches |
| GraphQL? | **No** — REST-style path URLs only |
| Embedded in HTML? | Initial shell is ASP.NET WebForms HTML; availability is **not** embedded |
| Public without login? | **Yes** for search, grids, and Great Walk listings |
| Cookies required? | Session cookie on DOC site; Tyler API relies on **AWS WAF token/challenge** cookies for direct access |
| CSRF tokens? | WebForms `__VIEWSTATE` / `__EVENTVALIDATION` for form posts; ASP.NET **WebMethods** use JSON POST + session cookie |
| Suitable for polling? | Endpoints exist, but **AWS WAF** makes naive HTTP polling unreliable |
| Rate limiting / bot protection? | **AWS WAF** with CAPTCHA/challenge on Tyler API; **Google reCAPTCHA** on login and some booking actions |
| Cloudflare? | **No** — site uses **AWS CloudFront** + **AWS WAF** |

## Site architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Browser (user)                                                  │
└────────────┬───────────────────────────────┬────────────────────┘
             │                               │
             ▼                               ▼
┌────────────────────────────┐   ┌──────────────────────────────────┐
│ bookings.doc.govt.nz       │   │ prod-nz-rdr.recreation-          │
│ (ASP.NET WebForms + SPA)   │   │ management.tylerapp.com          │
│                            │   │ (Tyler RDR JSON API)             │
│ - Default.aspx shell       │   │                                  │
│ - Keechma React/ClojureScript│ │ - search/* availability          │
│ - CascadingDropdown.asmx   │   │ - fd/availability/*              │
│ - Default.aspx/WebMethods    │   │ - enterprise/* config            │
└────────────┬───────────────┘   └──────────────────────────────────┘
             │
             ▼
┌────────────────────────────┐
│ AWS CloudFront CDN         │
│ AWS WAF (Tyler API)        │
│ AWS ALB (AWSALB cookies)   │
└────────────────────────────┘
```

### Front-end stack

1. **ASP.NET WebForms** host page (`Default.aspx`) — ~260 KB HTML with inline config globals.
2. **Keechma + ClojureScript** compiled to `Keechma/js/main.js` (~4 MB) — hash-routed SPA (`#!greatwalk-result`, `#!results`, etc.).
3. **jQuery 3.7.1** for legacy AJAX (login, cart, captcha checks, some availability calls).
4. **Esri ArcGIS** maps for park/facility location UI.
5. **Google reCAPTCHA v2/v3** — site keys embedded in page (`6Leq3Qcr...`, `6Le6wRkr...`).
6. **New Relic** browser agent for telemetry.

### Vendor / platform

The booking engine is **Tyler Technologies Recreation Management** (enterprise name `NewZealand`). The public site is a customised DOC theme; the data plane is the Tyler **RDR** API:

```
https://prod-nz-rdr.recreation-management.tylerapp.com/nzrdr/rdr/
```

This URL is exposed in page JavaScript as `window.apiurl`.

### Routing model

Navigation uses **hash routes** on a single ASP.NET page:

| Hash route | Purpose |
|------------|---------|
| `#!greatwalk-result` | Great Walk track list and booking grid |
| `#!results` | Huts, campsites, lodges search |
| `#!park` | Park detail |
| (others) | Draw applications, customer areas (login required) |

No separate page load for search results — the SPA swaps views client-side.

## How availability data is loaded

### Great Walks

1. User opens `Default.aspx#!greatwalk-result`.
2. SPA calls `GET .../search/getgreatwalkplaces/false/isCashier` — returns all Great Walk **places** (tracks) with metadata and booking window dates.
3. When a track is selected, additional calls load facility/unit data, e.g.:
   - `GET .../search/getgreatwalksearchdata/placeId/{placeId}`
   - `POST .../search/greatwalkplacefacility`
   - `GET .../search/getgreatwalkfacilityinformation/facilityId/{id}/startDate/{date}`
4. Per-unit confirmation before booking uses:
   - `GET .../fd/availability/getbyunit/{unitId}/startdate/{YYYY-MM-DD}/nights/{n}/false`

### Huts / campsites / lodges

1. `POST .../search/place` — place search with date/night filters (primary search).
2. `POST .../search/grid` — availability grid with per-unit **slices** (day-by-day free/locked/blocked state).
3. `GET .../search/details/{facilityId}/startdate/{date}/nights/{n}/{customerId}/{classificationId}` — facility detail view.
4. `GET .../search/next/{facilityId}/startdate/{date}/nights/{n}` — next available unit for unnumbered sites.

Grid slice objects (from client-side processing) include fields such as `IsFree`, `Lock`, `IsBlocked`, `ReservationId`, and `Date`.

## Authentication and session

### Browsing / searching (no login)

- **No account required** to view places, Great Walk lists, or availability grids.
- Tyler API calls use `Accept: application/json` and `Referer: https://bookings.doc.govt.nz/`.
- `customerId` defaults to `0` and `customerClassificationId` to `0` in anonymous searches.

### DOC site session

On first visit to `Default.aspx`, the server sets:

| Cookie | Purpose |
|--------|---------|
| `Saturn_SessionId` | ASP.NET session (HttpOnly, SameSite=Lax) |
| `AWSALB` / `AWSALBCORS` | AWS Application Load Balancer stickiness |
| `_ga` / `_ga_*` | Google Analytics |

Session auto-expires — page includes `Refresh: 1200;URL=.../Logout.aspx` (20-minute idle refresh).

### Login (out of scope for M0)

- Login via `POST .../Facilities/CascadingDropdown.asmx/LoginByEmail_V2` with JSON body `{ email, password, ... }`.
- Google reCAPTCHA required for login and some unit booking flows.
- Account creation required for actual bookings (per DOC terms).

### CSRF / anti-forgery

- Classic WebForms hidden fields: `__VIEWSTATE`, `__EVENTVALIDATION`, `__VIEWSTATEGENERATOR` on `form1`.
- ASP.NET **ScriptMethod/WebMethod** endpoints (`Default.aspx/GetTimeDetail`, etc.) use JSON POST without a separate CSRF header — they rely on same-origin policy and session cookie.
- Tyler RDR API does **not** use CSRF tokens; CORS allows `Access-Control-Allow-Origin: *` but WAF blocks unauthenticated scripted clients.

## Bot protection and infrastructure

### AWS WAF (Tyler API)

Direct `curl` or Playwright `APIRequestContext` calls to Tyler endpoints often return:

- **HTTP 405** or challenge HTML
- Header: `x-amzn-waf-action: captcha`
- CAPTCHA/challenge scripts from `*.awswaf.com`

Browser-driven XHR from a fully loaded SPA session typically succeeds (observed HTTP 200). WAF behaviour is **non-deterministic** from some networks/IP ranges.

### reCAPTCHA

- Login popup and some booking paths validate captcha server-side via `Default.aspx/UnitCaptchaResponseCheck`.
- Not triggered for read-only availability browsing.

### CDN / WAF vendor

- **Not Cloudflare** — responses show `Via: CloudFront`, `X-Amz-Cf-*`, `X-Cache`.
- DOC web: `X-Powered-By: ASP.NET`, CloudFront.
- Tyler API: `Server: Kestrel` behind CloudFront.

### Monitoring

- New Relic browser agent (`bam.nr-data.net`).
- Google Tag Manager / Analytics.

## Important observations

1. **Two-tier architecture** — DOC site handles auth, cart, payment, and business rules; Tyler RDR serves inventory/availability JSON.
2. **Public read API** — Availability endpoints are callable without login when WAF permits the request.
3. **Great Walk booking window** — `getgreatwalkplaces` returns `FutureBookingStartDate` / `FutureBookingEndDate` (observed: season opens ~21 June 2026, closes ~21 Dec 2027).
4. **Fixed-itinerary tracks** — e.g. Milford Track has `IsAvailableForFixedgreatwalk: true` with `FixedGWMinNight` / `FixedGWMaxNight` of 3.
5. **Inventory locking** — `checkUnitAvailability` checks `IsLocked` before allowing cart add; short-lived locks during concurrent booking.
6. **Separate public DOC API** — `api.doc.govt.nz/v2` provides hut/campsite **metadata** only, not live booking availability.

## Potential challenges for automation

| Challenge | Impact | Notes |
|-----------|--------|-------|
| AWS WAF on Tyler API | High | Blocks headless/scripts; may need real browser context or conservative polling |
| reCAPTCHA at booking time | High | Monitoring can avoid; booking will need human-in-the-loop or official API |
| Session timeout (20 min) | Medium | Long-poll sessions need refresh |
| Inventory locks | Medium | Availability can change between check and book |
| No documented public API | Medium | Reverse-engineered paths may change with Tyler upgrades |
| Terms of service | High | DOC prohibits speculative bookings; automation must respect rate limits and ToS |
| Seasonal booking windows | Medium | Great Walks only bookable within published date range |

## Investigation methodology

Tools used:

- `curl` / HTTP header inspection
- Static analysis of `Default.aspx`, `main.js`
- Playwright headless browser with network capture (`scripts/investigate_network.py`)
- Sample response extraction (`investigation_output/` — gitignored, regenerate locally)

## Great Walk places observed (June 2026)

From `search/getgreatwalkplaces` response:

| PlaceId | Name |
|---------|------|
| 875 | Abel Tasman Coast Track |
| 876 | Heaphy Track |
| 872 | Kepler Track |
| 878 | Lake Waikaremoana Track |
| 873 | Milford Track (fixed 3-night itinerary) |
| 880 | Paparoa Track |
| … | (additional tracks in full response) |

See [api.md](api.md) for endpoint details and example payloads.

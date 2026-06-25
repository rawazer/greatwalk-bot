# Complete-itinerary availability (Milestone 8)

This document describes how GreatWalkBot validates **complete** Great Walk itineraries from DOC Tyler RDR responses — without logging in or adding items to a cart.

## Endpoint

| Method | Path | Purpose |
|--------|------|---------|
| POST | `search/greatwalkplacefacility` | Per-facility availability for a Great Walk place |

**Request body** (built by `build_gw_facility_request`):

| Field | Value |
|-------|-------|
| `placeId` | Track `place_id` (e.g. 873 for Milford) |
| `arrivalDate` | Query range start (`YYYY-MM-DD`) |
| `nights` | `(to_date - from_date).days` |
| `customerClassificationId` | `0` (anonymous) |
| `accomodation` | `""` (API spelling preserved) |

**Response** (relevant fields):

```
GreatWalkFacilityData[]
  FacilityName
  GreatWalkFacilityDateData[]
    ArrivalDate
    IsSeasonAvailable
    IsAvailable
    TotalAvailable
```

Each `FacilityName` row is one hut/campsite on the track. `ArrivalDate` is the **first night** at that facility for a given itinerary start. `TotalAvailable` is the count of bookable spaces DOC exposes for that facility-night.

GreatWalkBot does **not** expose raw JSON outside the parsing layer.

## Investigation samples (June 2026)

Representative shapes used for fixtures and documentation:

### Available complete itinerary (Milford)

Starting **2026-12-07**, all three required huts report `IsAvailable: true` with `TotalAvailable > 0` on their respective arrival nights:

| Night | Arrival date | Facility | Spaces (fixture) |
|-------|--------------|----------|------------------|
| 1 | 2026-12-07 | Clinton Hut | 6 |
| 2 | 2026-12-08 | Mintaro Hut | 8 |
| 3 | 2026-12-09 | Dumpling Hut | 10 |

Fixture: `tests/fixtures/milford_complete.json`

### Unavailable required night (Milford)

Same start date, but **Mintaro Hut** on 2026-12-08 has `IsAvailable: false`. The day-level aggregate may still show other huts as available on nearby dates; the bot **does not alert** because the full sequence fails validation.

Fixture: `tests/fixtures/milford_partial.json`

### Direction-dependent partial availability (Routeburn)

For start **2026-12-10**:

| Direction | Night 1 | Night 2 | Valid? |
|-----------|---------|---------|--------|
| Shelter → Divide | Routeburn Falls Hut (available) | Lake Mackenzie Hut (unavailable on 2026-12-11) | No |
| Divide → Shelter | Lake Mackenzie Hut (unavailable on 2026-12-10) | Routeburn Falls Hut (available on 2026-12-11) | No* |

\*Fixture `routeburn_directions.json` is constructed so **forward** (shelter → divide) validates and **reverse** does not. This models mixed per-direction facility rows from DOC.

## Registered complete itineraries

Metadata lives in `src/greatwalkbot/track_itineraries.py`. Facility names are matched case-insensitively.

| Track | Direction | Nights | Required facilities (in order) |
|-------|-----------|--------|--------------------------------|
| milford | — | 3 | Clinton Hut, Mintaro Hut, Dumpling Hut |
| routeburn | `routeburn-shelter-to-divide` | 2 | Routeburn Falls Hut, Lake Mackenzie Hut |
| routeburn | `routeburn-divide-to-shelter` | 2 | Lake Mackenzie Hut, Routeburn Falls Hut |
| kepler | — | 3 | Luxmore Hut, Iris Burn Hut, Moturau Hut |
| waikaremoana | `waikaremoana-onepoto-to-hopuruahine` | 3 | Panekire Hut, Waiopaoa Hut, Marauiti Hut |
| waikaremoana | `waikaremoana-hopuruahine-to-onepoto` | 3 | Marauiti Hut, Waiopaoa Hut, Panekire Hut |

**Lake Waikaremoana:** `direction: either` evaluates both walking directions separately (facility names from live `greatwalkplacefacility` responses, June 2026).

**Routeburn:** `direction: either` in config evaluates **both** directions separately. Alerts include the validated direction slug — never a generic “either”.

**Facility IDs:** Not used. Matching is by documented `FacilityName` strings from observed responses. Update the registry if DOC renames huts.

## Validation rules

For each candidate start date on a track with `complete_itinerary_only: true` (or a registered itinerary definition):

1. Build a `FacilityAvailabilityIndex` from the parsed response.
2. For each required night *n*, look up `(facility, start_date + n days)`.
3. Require `IsAvailable` with `TotalAvailable >= party_size` for **every** night.
4. Emit `AvailableItinerary(complete_itinerary=True)` only when all nights pass.
5. If facility-level data is missing, **do not alert**; log `unverified` at INFO.

Bottleneck spaces on a complete itinerary = minimum `TotalAvailable` across required nights.

## Limitations and uncertainties

- **Per-day aggregation vs itinerary:** The legacy day view (`AvailabilityDay`) still aggregates max spaces across facilities on a calendar day. Matching for complete-itinerary tracks uses the facility index, not day aggregates alone.
- **Direction detection from API:** DOC does not always label direction explicitly in `greatwalkplacefacility`. Routeburn directions are inferred by checking both registered facility sequences.
- **Non-fixed tracks:** Tracks without registry metadata and without `complete_itinerary_only` fall back to conservative day-level matching (no completeness guarantee).
- **Locks and cart state:** `TotalAvailable` may change between check and book; the bot does not call unit-lock endpoints.
- **WAF:** Direct HTTP may be blocked; Playwright is the operational fetch path. A missing `greatwalkplacefacility` response after Search is **not** classified as WAF unless challenge indicators appear in network headers or page HTML.

## Selection and capture (Milestone 9.2–9.3)

Before waiting for `POST search/greatwalkplacefacility`, the bot:

1. Opens the Great Walk dropdown (`great-walk-dropdown-button` or mobile variant).
2. Clicks the desktop or mobile option id (`great-walk-{n}` / `great-walk-mobile-{n}`).
3. Waits until selection **commits** — selected UI state or `GET search/getgreatwalksearchdata/placeId/{id}` with HTTP 200.
4. Captures a sanitized **search form state** (track label, start date, nights, Search button enabled/visible, validation text, loading overlay).
5. Sets start date (`#great-walk-start-date`) and nights (`#great-walk-nights` or equivalent) in the SPA controls and verifies DOM reflection.
6. Registers a post-search response listener, clicks the enabled Search control (`#great-walk-search-button` or equivalent), and verifies an observable transition (network activity, loading overlay, results container, or validation error).

**Error classification (no generic WAF guess):**

| Condition | Error |
|-----------|-------|
| Selection not committed | `TrackSelectionNotCommittedError` |
| Search disabled / validation message | `SearchFormValidationError` (includes `search_form_state` in diagnostics) |
| Selection OK, Search clicked, no post-search request | `AvailabilitySearchNotDispatchedError` |
| Post-search request, bad status | `AvailabilityRequestFailedError` |
| WAF only with concrete signals (`x-amzn-waf-action`, `awswaf`, etc.) | `WafChallengeSuspectedError` |

`btChecker is not defined` page errors alone are **not** WAF evidence.

Failed fetches write `network_timeline` and `search_form_state` into `logs/diagnostics/*/summary.json`.

**Debug CLI:** `gwbot debug-search config.yaml --track routeburn --date 2026-12-03` runs one read-only browser attempt (no Telegram, no dedupe) and prints form state, search outcome, and candidate network timeline.

## Diagnostics

```bash
gwbot explain-availability config.yaml --track milford --date 2026-12-07
```

Prints per-night checks, spaces, direction (if applicable), and failure reasons. Does not notify or update dedupe state.

See also [api.md](api.md) and [reverse_engineering.md](reverse_engineering.md).

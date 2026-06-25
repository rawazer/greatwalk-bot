# DOC Booking API Reference (Milestone 0)

Reverse-engineered from public browser traffic to [bookings.doc.govt.nz](https://bookings.doc.govt.nz/Web/). This is **undocumented** and may change without notice.

## Base URLs

| Service | Base URL |
|---------|----------|
| DOC web (ASP.NET) | `https://bookings.doc.govt.nz/Web/` |
| Tyler RDR API | `https://prod-nz-rdr.recreation-management.tylerapp.com/nzrdr/rdr/` |

Global in page JS: `window.apiurl`, `window.baseurlmain`, `window.enterpriceName = 'NewZealand'`.

---

## Tyler RDR API

### Common request pattern

```
GET /nzrdr/rdr/{path}
Accept: application/json
Referer: https://bookings.doc.govt.nz/
Origin: (optional, browser sends automatically)
```

Many search endpoints also accept **POST** with a JSON body (ClojureScript SPA).

**Authentication:** None for read-only search endpoints. Anonymous `customerId=0`, `customerClassificationId=0`.

**Response format:** JSON (`Content-Type: application/json; charset=utf-8`).

**CORS:** `Access-Control-Allow-Origin: *` on many endpoints.

**WAF note:** Direct HTTP clients often receive HTTP 405 + AWS WAF CAPTCHA HTML. Browser-initiated XHR after page load typically succeeds.

---

### Enterprise / config

#### `GET search/bookingwindow`

Returns server time and global booking window.

**Example response:**

```json
{
  "ServerStamp": "2026-06-21T06:01:07.773196+12:00",
  "FutureBookingStarts": "2026-06-23T00:00:00+12:00",
  "FutureBookingEnds": "2026-12-20T00:00:00+13:00"
}
```

#### `GET enterprise/settings`

Key/value map of enterprise feature flags (numeric keys).

#### `GET enterprise/websitesettings`

Large JSON object of web UI configuration (filters, captcha flags, date formats, etc.).

#### `GET search/popular/WebMenu`

Navigation menu items (includes “Great Walk Bookings” entry).

#### `GET search/popular/DynamicConfigMessage`

HTML fragments for dynamic site messages.

---

### Place search (huts, campsites, lodges)

#### `POST search/place`

Primary place search. Body is a JSON object (processed by SPA) containing fields such as:

| Field | Description |
|-------|-------------|
| `startdate` | Arrival date (`YYYY-MM-DD`) |
| `nights` | Length of stay |
| `placeId` / filters | Search scope |
| `customerId` | `0` when anonymous |

**Response:** List of places with availability summaries (`AvailableUnitCount`, `OccupancyPercentage`, etc.).

#### `POST search/grid`

Availability grid for a facility — per-unit, per-day slices.

**Body fields (from SPA):** `facilityId`, `startdate`, `nights`, `customerId`, `maxDate`, filter flags.

**Response structure (conceptual):**

```json
{
  "Facility": {
    "FacilityId": 12345,
    "Name": "Example Hut",
    "Units": {
      "67890": {
        "UnitId": 67890,
        "Name": "Bunk 1",
        "Slices": [
          {
            "Date": "2026-10-15",
            "IsFree": true,
            "IsBlocked": false,
            "Lock": null,
            "ReservationId": 0
          }
        ]
      }
    }
  }
}
```

#### `GET search/details/{facilityId}/startdate/{date}/nights/{n}/{customerId}/{customerClassificationId}`

Detailed facility view for a date range.

#### `GET search/next/{facilityId}/startdate/{date}/nights/{n}`

Find next available unit (unnumbered / open camping).

**Example response shape:**

```json
{
  "CountsByUnitId": {
    "12345": 1,
    "12346": 0
  }
}
```

---

### Great Walk endpoints

#### `GET search/getgreatwalkplaces/{isCashier}/isCashier`

List all Great Walk tracks. Example path: `.../false/isCashier`.

**Example response (truncated):**

```json
{
  "FutureBookingStartDate": "2026-06-21",
  "FutureBookingEndDate": "2027-12-21",
  "GWPlaceData": [
    {
      "PlaceId": 873,
      "Name": "Milford Track",
      "AllowWebBooking": true,
      "IsAvailableForGreatwalk": true,
      "IsAvailableForFixedgreatwalk": true,
      "FixedGWMinNight": 3,
      "FixedGWMaxNight": 3,
      "Latitude": -44.8138203,
      "Longitude": 167.7834612
    }
  ]
}
```

#### `GET search/getgreatwalksearchdata/placeId/{placeId}`

Search configuration and facility list for a selected Great Walk place. The SPA typically calls this **after** the user commits a track selection in the dropdown (not merely when the menu is open). GreatWalkBot treats a `200` response on this path as evidence that selection committed.

#### `POST search/greatwalkplacefacility`

Facility availability for Great Walk place. JSON body includes `PlaceId`, `StartDate`, `NightCount`, `CustomerClassificationId`, `SeasonId`.

Triggered when the user clicks **Search** after a committed track selection. GreatWalkBot registers a response listener **before** clicking Search so an immediate response is not missed.

See [itinerary-availability.md](itinerary-availability.md) for how GreatWalkBot validates complete itineraries from this response.

### Observed SPA network flow (June 2026)

| Step | Endpoint | When | Kepler | Milford / Routeburn |
|------|----------|------|--------|---------------------|
| 1 | `GET search/getgreatwalkplaces/...` | Page load | Yes | Yes |
| 2 | `GET search/getgreatwalksearchdata/placeId/{id}` | After track **committed** | Yes (`872`) | Yes (`873` / `874`) when selection commits |
| 3 | `POST search/greatwalkplacefacility` | After **Search** click | Yes | Yes when step 2 succeeded |

**Milford / Routeburn failure mode (production):** Page loads and the track name is visible in the open dropdown, but step 2 never fires because the SPA did not commit the selection (often fixed-itinerary tracks need the dropdown button opened and desktop or mobile option id clicked). The bot then times out at step 3 with `AvailabilityRequestNotObservedError` or `TrackSelectionNotCommittedError` — not a WAF block unless challenge headers/HTML are present.

**Candidate paths** monitored in diagnostics (`network_timeline` in `summary.json`): `search/greatwalkplacefacility`, `search/getgreatwalksearchdata`, `search/getgreatwalkfacilityinformation`, `search/grid`, `fd/availability/getbyunit`. URLs are stored as path-only with numeric segments and query values redacted.

### Great Walk search form controls (June 2026)

GreatWalkBot discovers the **active** form root at runtime (`resolve_active_great_walk_form`) before any read/write. Duplicate mobile/desktop/hidden placeholders are scored and rejected; the winner is marked `[data-gwbot-active-root="1"]` and all locators are scoped beneath it.

| Control | Scoped selector (within active root) | Type | Semantic value |
|---------|--------------------------------------|------|----------------|
| Track | `#great-walk-dropdown-button` (visible) | dropdown button | `visible_text` label only |
| Start date | `input#great-walk-start-date-input`, hidden date input, or `#great-walk-start-date` + calendar | input / date-button | ISO `YYYY-MM-DD` from `.value` or `data-date` |
| Nights | `select#great-walk-nights` (visible, interactable) | `<select>` | `select.value` — never `textContent` |
| Search | `#great-walk-search-button` | button | enabled + visible |

**Loading vs validation:** Text such as `Fetching Content...` is treated as loading state (`GreatWalkFormNotReadyError`), not validation. Validation is read only from `[role="alert"]`, `.invalid-feedback`, `.field-validation-error`.

**Diagnostics:** `debug-search` reports active root resolution (candidate count, rejections, controls found) and a bounded `active_form_inventory` (≤40 nodes) for the active subtree only.

**Selection reporting:** Backend metadata (`getgreatwalksearchdata` 200) and visible track label are read from the same active root in one attempt. `ui_state_inconsistent` is set when they disagree.

#### `GET search/getgreatwalkfacilityinformation/facilityId/{facilityId}/startDate/{YYYY-MM-DD}`

Facility metadata and restrictions for a start date.

#### `GET search/getgreatwalkalert/placeId/{placeId}/alertId/0/startDate/{date}`

Alerts for a Great Walk place.

#### `GET search/getgreatwalkoccupantInfo/noOfPeople/{n}/unitId/{unitId}/startDate/{date}/customerClassificationId/{id}`

Occupancy validation for Great Walk units.

---

### Unit availability

#### `GET fd/availability/getbyunit/{unitId}/startdate/{YYYY-MM-DD}/nights/{n}/{includeLock}`

Check whether a specific unit is available. Last path segment is boolean (`false` observed in booking flow).

**Example response (array):**

```json
[
  {
    "IsLocked": false,
    "UnitId": 67890
  }
]
```

If `IsLocked` is `true`, another user is mid-booking.

---

### Map / ancillary

| Method | Path | Purpose |
|--------|------|---------|
| GET | `search/maplayers` | GIS layer config |
| GET | `search/basemaplist` | Basemap list |
| GET | `search/filters/{id}` | Search filter definitions |
| GET | `search/popular/places/{limit}` | Popular places ranking |
| GET | `search/popular/places/near/{id}/on/{date}/limit/{n}` | Nearby places |
| GET | `fd/CityPark/CityPlaceswithAlias` | City park aliases |

---

## DOC ASP.NET endpoints

Base: `https://bookings.doc.govt.nz/Web/`

### WebMethods on `Default.aspx`

JSON POST to `{page}/{MethodName}` with `Content-Type: application/json; charset=utf-8`.  
Response wrapper: `{ "d": <payload> }`.

| Method | Purpose |
|--------|---------|
| `GetTimeDetail` | Server time (POST, empty/minimal body) |
| `SetTimeWidgetSession` | Session flag for time widget |
| `GetTimeDifference` | Client/server clock skew |
| `GetRestrictionRDR` | Booking restrictions check |
| `CheckRestractionforUnnumberOpencampingBooking` | Open camping rules |
| `UnitCaptchaResponseCheck` | Validate reCAPTCHA before booking |
| `SaveWaitListInfo` | Wait-list notification signup |
| `LockUnitPersonOccupancy` / `UnLockUnitPersonOccupancy` | Great Walk occupancy locks |
| `ValidateOccupancy` | Occupancy validation |
| `SetFutureBookingStartEndDates` | Post-login booking window |
| `BookDrawApplication` / `SaveDrawApplication` / `CancelDrawApplication` | Lottery/draw flows |

**Example — GetTimeDetail:**

```http
POST /Web/Default.aspx/GetTimeDetail HTTP/1.1
Content-Type: application/json; charset=utf-8

{}
```

**Example response:**

```json
{ "d": "2026-06-21T06:00:00+12:00" }
```

### ASMX services

`Facilities/CascadingDropdown.asmx`:

| Method | Purpose |
|--------|---------|
| `LoginByEmail_V2` | Customer login |
| `LoginByEmail_V2_Exp` | Extended login |
| `LoginByEmail_Cashier` | Staff/cashier login |
| `LogOutCustomer` | Logout |

---

## HTTP headers (typical)

### DOC `Default.aspx` response

```http
Content-Type: text/html; charset=utf-8
Set-Cookie: Saturn_SessionId=...; HttpOnly; SameSite=Lax
Set-Cookie: AWSALB=...; Path=/
X-Powered-By: ASP.NET
Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
Via: 1.1 ....cloudfront.net (CloudFront)
X-Cache: Miss from cloudfront
Refresh: 1200;URL=https://bookings.doc.govt.nz/Web/Logout.aspx
```

### Tyler RDR success response

```http
Content-Type: application/json; charset=utf-8
Access-Control-Allow-Origin: *
X-Powered-By: ASP.NET
Server: Kestrel
Via: 1.1 ....cloudfront.net (CloudFront)
```

### Tyler RDR WAF challenge (blocked)

```http
HTTP/1.1 405
Content-Type: text/html; charset=UTF-8
x-amzn-waf-action: captcha
Cache-Control: no-store, max-age=0
```

---

## Authentication flow (reference only)

```
1. User submits email/password in login modal
2. reCAPTCHA token generated client-side
3. POST CascadingDropdown.asmx/LoginByEmail_V2  { email, password, captcha, ... }
4. Server sets authenticated session; customerId > 0 in subsequent API calls
5. Booking: checkUnitAvailability → form POST to SelectReservationPreCart.aspx
6. Payment via ANZ eGate (external)
```

Not exercised in Milestone 0.

---

## Session handling summary

| Layer | Mechanism |
|-------|-----------|
| DOC site | `Saturn_SessionId` cookie, 20-min idle refresh |
| Tyler API | No login token; WAF cookies from browser challenge |
| Anonymous search | `customerId=0`, no Authorization header |
| Authenticated search | Non-zero `customerId` / `customerClassificationId` in URL or POST body |

---

## Related public API (not booking)

DOC metadata API (no live availability):

```
https://api.doc.govt.nz/v2/huts/{id}/detail
https://api.doc.govt.nz/v2/campsites/{id}/detail
```

Useful for hut names/locations only — **not** a substitute for Tyler RDR.

---

## PoC usage

```bash
uv run greatwalk-check
```

Implementation: `src/greatwalkbot/client.py` loads the SPA in Playwright, captures Tyler JSON responses, and prints Great Walk place list + booking window (`src/greatwalkbot/availability.py`).

---

## Endpoint index (quick reference)

```
# Config
GET  enterprise/settings
GET  enterprise/websitesettings
GET  search/bookingwindow

# Search
POST search/place
POST search/grid
GET  search/details/{facilityId}/startdate/{date}/nights/{n}/{customerId}/{classId}
GET  search/next/{facilityId}/startdate/{date}/nights/{n}

# Great Walks
GET  search/getgreatwalkplaces/{bool}/isCashier
GET  search/getgreatwalksearchdata/placeId/{placeId}
POST search/greatwalkplacefacility
GET  search/getgreatwalkfacilityinformation/facilityId/{id}/startDate/{date}

# Unit
GET  fd/availability/getbyunit/{unitId}/startdate/{date}/nights/{n}/{bool}
```

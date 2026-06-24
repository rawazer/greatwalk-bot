# Trip-fit evaluation

GreatWalkBot can filter availability alerts so you are notified only when a newly available **complete itinerary** still leaves room in your travel window for the other Great Walks you hope to do.

This is a **feasibility check using dates and known durations**. It does **not**:

- assume other tracks are actually available
- optimise or rank combinations
- book anything for you

“Plausible” means there exists at least one non-overlapping date layout for the remaining walks — not that those dates will open up.

## Configuration

```yaml
trip_fit:
  enabled: true
  min_rest_days_between_walks: 1
  buffer_days_before_first_walk: 1
  buffer_days_after_last_walk: 1
```

| Setting | Meaning |
|---------|---------|
| `enabled` | When true, only `trip_fit: true` itineraries trigger notifications |
| `min_rest_days_between_walks` | Full calendar days required between the end of one walk and the start of the next |
| `buffer_days_before_first_walk` | Days reserved after `travel_window.start` before any walk may begin |
| `buffer_days_after_last_walk` | Days reserved before `travel_window.end` after the last walk ends |

If `trip_fit` is absent or `enabled: false`, the matcher behaves as before (no feasibility filtering).

## Usable scheduling window

Given `travel_window` \([T_\text{start}, T_\text{end}]\):

```
usable_start = T_start + buffer_days_before_first_walk
usable_end   = T_end   - buffer_days_after_last_walk
```

Every walk must satisfy:

- `start_date >= usable_start`
- `end_date <= usable_end`

## Walk duration

Each complete itinerary has a registered night count in `track_durations.py`:

| Track | Nights | Notes |
|-------|--------|-------|
| milford | 3 | Matches DOC `FixedGWMinNight` / `FixedGWMaxNight` |
| routeburn | 2 | Standard 3-day / 2-night complete itinerary |
| kepler | 3 | Circular 4-day / 3-night itinerary |

**End date rule:** `end_date = start_date + itinerary_nights` (last calendar day on the track).

Tracks with `fixed_nights` on the `Track` registry fall back to that value. Unregistered tracks raise a clear error at evaluation time.

Direction preferences (e.g. Routeburn `either`) affect booking choice only — not duration in this milestone.

## Evaluator steps

For each newly matched itinerary on an **unconfirmed** track (party size and track preference already satisfied):

1. **Buffer check** — reject if the candidate violates usable window buffers.
2. **Confirmed booking check** — reject if the candidate overlaps a confirmed booking or leaves insufficient rest days (`conflicts_with_confirmed_booking`).
3. **Candidate booking** — treat the itinerary as fixed on the calendar.
4. **Remaining unconfirmed tracks** — for every other track without a `confirmed_booking`, check whether there exists at least one ordering and start date such that:
   - start falls within that track’s `acceptable_start_range` and the usable window
   - duration fits before `usable_end`
   - intervals do not overlap, with `min_rest_days_between_walks` between walks
4. **Result** — `trip_fit: true` if all remaining unconfirmed tracks can be placed; otherwise `trip_fit: false` with reasons:

| Reason | Meaning |
|--------|---------|
| `outside_travel_window` | Candidate outside overall travel dates |
| `overlaps_required_buffer` | Candidate intrudes on before/after buffers |
| `conflicts_with_confirmed_booking` | Candidate overlaps a configured confirmed booking or rest gap |
| `insufficient_room_for_remaining_tracks` | No layout fits the other unconfirmed walks |

The evaluator tries all permutations of remaining unconfirmed tracks (typically 1–2 walks after bookings) and greedily assigns the earliest feasible start for each order.

Confirmed bookings are fixed intervals loaded from configuration — see [bookings.md](bookings.md).

## Notifications

When `trip_fit.enabled` is true:

- **Notify** only new itineraries with `trip_fit: true`
- **Log at INFO** suppressed candidates with reasons (no Telegram)
- Include in messages: `Fits current trip window with remaining walks.`

When disabled, all new matches are notified as today.

## Inspection

```bash
gwbot plan-check config.yaml
```

Prints configured tracks, durations, buffers, rest rules, and whether the full set can fit **in principle** (ignoring live availability). Exits nonzero if impossible even before polling.

Does not contact DOC or Telegram.

## Limitations

- Does not model travel between trailheads, weather, or non-walk activities.
- Does not shrink acceptable ranges to preferred ranges — scheduling uses **acceptable** windows only.
- Assumes registered durations are correct for complete-itinerary products; verify against DOC when in doubt.
- A `trip_fit: true` alert means “worth considering now” — not “book immediately” or “other walks are free.”

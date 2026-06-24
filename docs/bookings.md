# Confirmed bookings

After you manually book a Great Walk on the DOC website, record the confirmed itinerary in your configuration. The watcher will stop polling that track and plan around the booked dates when evaluating trip-fit for the remaining walks.

This is **configuration only**. GreatWalkBot does not log into DOC, complete payments, or verify bookings against DOC.

## Workflow

1. Receive an availability alert from the bot.
2. Book the walk manually on DOC.
3. Add a `confirmed_booking` block to that track in `config.yaml`.
4. Restart the watcher (or reload configuration on your next deploy).
5. The bot skips live availability checks for that track and evaluates new alerts around the confirmed dates.

## Configuration

```yaml
tracks:
  - track: routeburn
    direction: either
    complete_itinerary_only: true
    preferred_start_range:
      start: 2026-12-06
      end: 2026-12-14
    acceptable_start_range:
      start: 2026-12-03
      end: 2026-12-23
    confirmed_booking:
      start_date: 2026-12-10
      nights: 2
      direction: routeburn-shelter-to-divide
      notes: "Booked manually on DOC"
```

| Field | Required | Meaning |
|-------|----------|---------|
| `start_date` | yes | First day of the booked itinerary |
| `nights` | yes | Complete-itinerary night count |
| `direction` | no | Booked direction label (informational) |
| `notes` | no | Free-text reminder (no credentials or payment details) |
| `allow_duration_override` | no | When `true`, allows `nights` to differ from the registered track duration |

**End date** is derived as `start_date + nights` (same rule as trip-fit; see [trip-fit.md](trip-fit.md)).

Do not store booking references, payment details, names, or credentials in configuration.

## Validation at load time

When `confirmed_booking` is present, the loader checks:

- `nights` matches the known complete-itinerary duration for that track (unless `allow_duration_override: true`)
- start and end dates fall within the travel window and respect `trip_fit` before/after buffers
- the booking does not overlap another confirmed booking, including `min_rest_days_between_walks`

Invalid configuration fails fast at `gwbot watch` or `gwbot plan-check` load time.

## Watch behavior

For tracks with `confirmed_booking`:

- **No** live availability fetch
- **No** notifications
- Logged at INFO: `Skipping <track>: confirmed booking <start>..<end>`

For unconfirmed tracks, trip-fit evaluation treats all confirmed bookings as fixed occupied intervals on the calendar.

A candidate is `trip_fit: true` only when it:

1. respects travel-window buffers,
2. does not conflict with any confirmed booking (including rest days),
3. leaves feasible room for every other **unconfirmed** track.

## Inspection commands

```bash
gwbot plan-check config.yaml
gwbot bookings config.yaml
```

`plan-check` shows confirmed bookings, remaining walks to monitor, and whether the remaining plan is feasible in principle around confirmed dates.

`bookings` lists confirmed bookings in chronological order.

Neither command contacts DOC or Telegram.

## Limitations

- Bookings are not synced from DOC; you must update configuration manually.
- Removing a `confirmed_booking` block resumes monitoring that track.
- Direction on a confirmed booking is stored for your reference only; it does not change duration or fetch behavior.
- Trip-fit still does not assume other walks are actually available — only that dates could work.

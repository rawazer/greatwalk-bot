"""Format explain-availability diagnostic output."""

from __future__ import annotations

from greatwalkbot.monitoring.itinerary_validation import ItineraryValidationResult


def format_validation_result(result: ItineraryValidationResult) -> str:
    lines = [
        f"Track: {result.track_name} ({result.track_slug})",
        f"Start date: {result.start_date.isoformat()}",
        f"Party size: {result.party_size}",
    ]
    if result.direction:
        lines.append(f"Direction: {result.direction}")

    lines.append(
        f"Complete itinerary validated: {'YES' if result.complete_itinerary else 'NO'}"
    )

    if result.nights:
        lines.append("")
        lines.append("Required nights checked:")
        for night in result.nights:
            spaces = "n/a" if night.spaces is None else str(night.spaces)
            status = "ok" if night.satisfied else "fail"
            lines.append(
                f"  - night {night.night_index + 1}: {night.facility_name} "
                f"on {night.arrival_date.isoformat()} — {spaces} spaces ({status})"
            )
    else:
        lines.append("")
        lines.append("Required nights checked: (none)")

    if result.complete_itinerary:
        lines.append("")
        lines.append(f"Bottleneck spaces: {result.bottleneck_spaces}")
    elif result.failure_reasons:
        lines.append("")
        lines.append(f"Failure reasons: {', '.join(result.failure_reasons)}")

    if result.validation_notes:
        lines.append("")
        lines.append("Notes:")
        for note in result.validation_notes:
            lines.append(f"  - {note}")

    return "\n".join(lines)


def format_explain_availability(
    results: tuple[ItineraryValidationResult, ...],
) -> str:
    if not results:
        return "No validation results."

    return "\n\n".join(format_validation_result(result) for result in results)

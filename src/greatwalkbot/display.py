"""Human-readable formatting for availability snapshots."""

from __future__ import annotations

from greatwalkbot.models import AvailabilitySnapshot


def format_availability_table(snapshot: AvailabilitySnapshot) -> str:
    lines: list[str] = []
    lines.append(
        f"{snapshot.track.name} - {snapshot.from_date.isoformat()} to {snapshot.to_date.isoformat()}"
    )
    if snapshot.track.fixed_nights:
        lines.append(f"(Fixed {snapshot.track.fixed_nights}-night itinerary)")
    lines.append("")

    headers = ("Date", "Status", "Spaces", "Facilities")
    rows: list[tuple[str, str, str, str]] = []
    for day in snapshot.days:
        facility_text = ", ".join(day.facilities) if day.facilities else "-"
        rows.append(
            (
                day.date.isoformat(),
                day.status.value,
                str(day.spaces),
                facility_text,
            )
        )

    widths = [
        max(len(headers[i]), *(len(row[i]) for row in rows))
        for i in range(len(headers))
    ]
    # Cap facilities column width for terminal readability.
    widths[3] = min(widths[3], 48)

    def fmt_row(cells: tuple[str, str, str, str]) -> str:
        facility = cells[3]
        if len(facility) > widths[3]:
            facility = facility[: widths[3] - 3] + "..."
        padded = (
            cells[0].ljust(widths[0]),
            cells[1].ljust(widths[1]),
            cells[2].rjust(widths[2]),
            facility,
        )
        return "  ".join(padded)

    lines.append(fmt_row(headers))
    lines.append("  ".join("-" * w for w in widths))
    for row in rows:
        lines.append(fmt_row(row))

    return "\n".join(lines)

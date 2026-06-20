"""Availability source interface."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from greatwalkbot.models import AvailabilitySnapshot, Track


class AvailabilitySource(Protocol):
    def fetch_track_availability(
        self,
        track: Track,
        from_date: date,
        to_date: date,
    ) -> AvailabilitySnapshot:
        """Return read-only availability for a track over an inclusive date range."""

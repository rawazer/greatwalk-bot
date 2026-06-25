"""Great Walk track registry and slug resolution."""

from __future__ import annotations

from greatwalkbot.models import Track

# list_index matches the order returned by getgreatwalkplaces (0 = first track).
TRACKS: tuple[Track, ...] = (
    Track("abel-tasman", "Abel Tasman Coast Track", 875, 0),
    Track("heaphy", "Heaphy Track", 876, 1),
    Track("kepler", "Kepler Track", 872, 2, fixed_nights=3),
    Track("waikaremoana", "Lake Waikaremoana Track", 878, 3, fixed_nights=3),
    Track("milford", "Milford Track", 873, 4, fixed_nights=3),
    Track("paparoa", "Paparoa Track", 880, 5),
    Track("rakiura", "Rakiura Track", 877, 6),
    Track("routeburn", "Routeburn Track", 874, 7, fixed_nights=2),
    Track("tongariro", "Tongariro Northern Circuit", 879, 8),
    Track("whanganui", "Whanganui Journey", 881, 9),
)


def resolve_track(slug: str) -> Track:
    normalized = slug.strip().lower().replace("_", "-")
    for track in TRACKS:
        if normalized == track.slug or normalized in track.name.lower():
            return track
    known = ", ".join(t.slug for t in TRACKS)
    raise ValueError(f"Unknown track {slug!r}. Known tracks: {known}")

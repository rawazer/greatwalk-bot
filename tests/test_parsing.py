"""Tests for Great Walk facility response parsing."""

from datetime import date

from greatwalkbot.models import AvailabilityStatus, Track
from greatwalkbot.parsing import build_gw_facility_request, parse_gw_facility_response

MILFORD = Track("milford", "Milford Track", 873, 4, fixed_nights=3)


def test_build_gw_facility_request():
    body = build_gw_facility_request(
        MILFORD,
        date(2026, 12, 7),
        date(2026, 12, 14),
    )
    assert body == {
        "accomodation": "",
        "placeId": 873,
        "customerClassificationId": 0,
        "arrivalDate": "2026-12-07",
        "nights": 7,
    }


def test_parse_gw_facility_response_aggregates_by_date():
    payload = {
        "GreatWalkFacilityHeaderData": [],
        "GreatWalkFacilityData": [
            {
                "FacilityName": "Mintaro Hut",
                "GreatWalkFacilityDateData": [
                    {
                        "ArrivalDate": "2026-12-07T00:00:00",
                        "IsAvailable": True,
                        "IsSeasonAvailable": True,
                        "TotalAvailable": 12,
                    },
                    {
                        "ArrivalDate": "2026-12-08T00:00:00",
                        "IsAvailable": False,
                        "IsSeasonAvailable": True,
                        "TotalAvailable": 0,
                    },
                ],
            },
            {
                "FacilityName": "Clinton Hut",
                "GreatWalkFacilityDateData": [
                    {
                        "ArrivalDate": "2026-12-07T00:00:00",
                        "IsAvailable": True,
                        "IsSeasonAvailable": True,
                        "TotalAvailable": 3,
                    }
                ],
            },
        ],
    }

    snapshot = parse_gw_facility_response(
        payload,
        MILFORD,
        date(2026, 12, 7),
        date(2026, 12, 8),
    )

    assert snapshot.track.slug == "milford"
    assert len(snapshot.days) == 2

    first, second = snapshot.days
    assert first.date == date(2026, 12, 7)
    assert first.status == AvailabilityStatus.AVAILABLE
    assert first.spaces == 12
    assert first.facilities == ("Clinton Hut", "Mintaro Hut")

    assert second.date == date(2026, 12, 8)
    assert second.status == AvailabilityStatus.UNAVAILABLE
    assert second.spaces == 0


def test_parse_marks_closed_when_season_unavailable():
    payload = {
        "GreatWalkFacilityData": [
            {
                "FacilityName": "Mintaro Hut",
                "GreatWalkFacilityDateData": [
                    {
                        "ArrivalDate": "2026-12-07T00:00:00",
                        "IsAvailable": False,
                        "IsSeasonAvailable": False,
                        "TotalAvailable": 0,
                    }
                ],
            }
        ]
    }

    snapshot = parse_gw_facility_response(
        payload,
        MILFORD,
        date(2026, 12, 7),
        date(2026, 12, 7),
    )
    assert snapshot.days[0].status == AvailabilityStatus.CLOSED

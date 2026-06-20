"""Tests for YAML config loading."""

from datetime import date
from pathlib import Path

import pytest

from greatwalkbot.config.loader import load_watch_config


def test_load_watch_config(tmp_path: Path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
party_size: 2
polling_interval: 120
tracks:
  - track: milford
    preferred:
      - from: 2026-12-07
        to: 2026-12-10
    acceptable:
      - from: 2026-12-01
        to: 2026-12-31
""",
        encoding="utf-8",
    )

    config = load_watch_config(config_file)
    assert config.party_size == 2
    assert config.polling_interval_seconds == 120
    assert len(config.tracks) == 1
    assert config.tracks[0].slug == "milford"
    assert config.tracks[0].preferred[0].from_date == date(2026, 12, 7)


def test_preferred_must_be_within_acceptable(tmp_path: Path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
party_size: 1
polling_interval: 60
tracks:
  - track: milford
    preferred:
      - from: 2027-01-01
        to: 2027-01-05
    acceptable:
      - from: 2026-12-01
        to: 2026-12-31
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="preferred"):
        load_watch_config(config_file)

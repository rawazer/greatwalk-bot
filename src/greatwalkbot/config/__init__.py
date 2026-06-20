"""Configuration loading."""

from greatwalkbot.config.loader import load_watch_config
from greatwalkbot.domain.plan import TripPlan

__all__ = ["TripPlan", "load_watch_config"]

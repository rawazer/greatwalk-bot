"""Shared patches for debug-search unit tests."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
from unittest.mock import patch

from greatwalkbot.sources.gw_desktop_form import DesktopRootBinding


@contextmanager
def patch_refresh_desktop_root(binding: DesktopRootBinding) -> Iterator[None]:
    def _refresh(_page, prior: DesktopRootBinding | None) -> tuple[DesktopRootBinding, dict]:
        current = prior or binding
        return binding, {
            "root_replaced": False,
            "prior_root": {
                "selector": current.selector,
                "id": current.root_id,
                "class": current.root_class,
            }
            if prior is not None
            else None,
            "current_root": {
                "selector": binding.selector,
                "id": binding.root_id,
                "class": binding.root_class,
            },
        }

    with patch(
        "greatwalkbot.debug_search.refresh_desktop_root_binding",
        side_effect=_refresh,
    ):
        yield

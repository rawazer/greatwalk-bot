"""Evidence-driven DOM discovery for DOC Great Walk controls (read-only)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

DISCOVERY_TERMS = (
    "great",
    "walk",
    "date",
    "arrival",
    "start",
    "night",
    "search",
    "facility",
    "place",
)

ASP_NET_FORM_ID = "form1"

_MAX_CANDIDATES = 80
_MAX_VISIBLE_CONTROLS = 40
_MAX_ANCESTOR_DEPTH = 5

_DISCOVER_DOM_JS = """
() => {
    const TERMS = ['great', 'walk', 'date', 'arrival', 'start', 'night', 'search', 'facility', 'place'];
    const MAX_CANDIDATES = 80;
    const MAX_VISIBLE = 40;
    const MAX_ANCESTOR_DEPTH = 5;
    const MAX_CLASS_LEN = 120;
    const MAX_TEXT_LEN = 80;

    function matchesTerm(value) {
        if (!value) return false;
        const lower = String(value).toLowerCase();
        return TERMS.some(t => lower.includes(t));
    }

    function isVisible(el) {
        if (!el || !el.getBoundingClientRect) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        if (parseFloat(style.opacity || '1') === 0) return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }

    function isEnabled(el) {
        return !el.disabled && el.getAttribute('aria-disabled') !== 'true';
    }

    function sanitizeText(text) {
        return (text || '').replace(/\\s+/g, ' ').trim().slice(0, MAX_TEXT_LEN) || null;
    }

    function boundedClasses(el) {
        const raw = (el.className || '').toString().trim();
        if (!raw) return null;
        return raw.slice(0, MAX_CLASS_LEN);
    }

    function suggestLocator(el) {
        if (el.id) return '#' + el.id;
        const name = el.getAttribute('name');
        if (name) return `[name="${name.replace(/"/g, '\\\\"')}"]`;
        const role = el.getAttribute('role');
        const tag = el.tagName.toLowerCase();
        const text = sanitizeText(el.textContent);
        if (role && text) return `${tag}[role="${role}"]:has-text("${text.slice(0, 30)}")`;
        if (text && tag === 'button') return `button:has-text("${text.slice(0, 30)}")`;
        return tag;
    }

    function readValue(el) {
        if (el.tagName === 'SELECT') {
            const opt = el.options[el.selectedIndex];
            return {
                value: el.value ?? null,
                selected_option_value: opt ? opt.value : null,
                selected_option_text: opt ? sanitizeText(opt.text) : null,
            };
        }
        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
            return { value: el.value ?? null, selected_option_value: null, selected_option_text: null };
        }
        const dataDate = el.getAttribute('data-date');
        if (dataDate) {
            return { value: dataDate, selected_option_value: null, selected_option_text: null };
        }
        return { value: null, selected_option_value: null, selected_option_text: null };
    }

    function collectAncestors(el) {
        const ancestors = [];
        let node = el.parentElement;
        for (let i = 0; i < MAX_ANCESTOR_DEPTH && node; i++) {
            ancestors.push({
                tag: node.tagName,
                id: node.id || null,
                class: boundedClasses(node),
            });
            node = node.parentElement;
        }
        return ancestors;
    }

    function describeElement(el) {
        const vals = readValue(el);
        return {
            tag: el.tagName,
            id: el.id || null,
            class: boundedClasses(el),
            name: el.getAttribute('name'),
            type: el.getAttribute('type'),
            role: el.getAttribute('role'),
            aria_label: el.getAttribute('aria-label'),
            aria_controls: el.getAttribute('aria-controls'),
            aria_expanded: el.getAttribute('aria-expanded'),
            aria_selected: el.getAttribute('aria-selected'),
            visible: isVisible(el),
            enabled: isEnabled(el),
            text: sanitizeText(el.textContent),
            value: vals.value,
            selected_option_value: vals.selected_option_value,
            selected_option_text: vals.selected_option_text,
            checked: el.checked === true ? true : null,
            suggested_locator: suggestLocator(el),
            ancestors: collectAncestors(el),
        };
    }

    function elementMatches(el) {
        const id = el.id || '';
        const cls = (el.className || '').toString();
        const name = el.getAttribute('name') || '';
        const role = el.getAttribute('role') || '';
        const ariaLabel = el.getAttribute('aria-label') || '';
        return matchesTerm(id) || matchesTerm(cls) || matchesTerm(name)
            || matchesTerm(role) || matchesTerm(ariaLabel);
    }

    const seen = new Set();
    const candidates = [];

    function addCandidate(el) {
        if (!el || seen.has(el) || candidates.length >= MAX_CANDIDATES) return;
        seen.add(el);
        candidates.push(describeElement(el));
    }

    document.querySelectorAll('*').forEach(el => {
        if (elementMatches(el)) addCandidate(el);
    });

    const interactiveSelector = [
        'button', 'input', 'select', 'textarea',
        '[role="listbox"]', '[role="combobox"]', '[role="dialog"]',
        '[role="button"]', '[role="alert"]', '[role="status"]',
    ].join(', ');
    document.querySelectorAll(interactiveSelector).forEach(el => {
        if (!isVisible(el)) return;
        if (elementMatches(el) || ['INPUT', 'SELECT', 'BUTTON'].includes(el.tagName)) {
            addCandidate(el);
        }
    });

    const visibleControls = [];
    document.querySelectorAll(interactiveSelector).forEach(el => {
        if (!isVisible(el) || visibleControls.length >= MAX_VISIBLE) return;
        visibleControls.push({
            tag: el.tagName,
            id: el.id || null,
            role: el.getAttribute('role'),
            type: el.getAttribute('type'),
            text: sanitizeText(el.textContent),
            value: readValue(el).value,
            enabled: isEnabled(el),
            suggested_locator: suggestLocator(el),
        });
    });

    const form1 = document.getElementById('form1');
    const form1HasGwControls = form1 ? !!form1.querySelector(
        '[id*="great-walk" i], [id*="greatwalk" i], select[id*="night" i], input[id*="date" i]'
    ) : false;

    return {
        candidate_count: candidates.length,
        candidates,
        visible_controls: visibleControls,
        page_containers: {
            form1_present: !!form1,
            form1_has_great_walk_descendants: form1HasGwControls,
        },
    };
}
"""


class DomDiscoveryPage(Protocol):
    def evaluate(self, expression: str, arg: Any = None) -> Any: ...


@dataclass(frozen=True)
class ControlDiscoveryAssessment:
    """Result of checking whether required GW controls were identified."""

    complete: bool
    found: dict[str, dict[str, Any] | None] = field(default_factory=dict)
    missing: tuple[str, ...] = ()
    loading_indicators: tuple[dict[str, Any], ...] = ()
    validation_indicators: tuple[dict[str, Any], ...] = ()
    form1_is_only_container: bool = False
    notes: tuple[str, ...] = ()


def discover_great_walk_dom(page: DomDiscoveryPage) -> dict[str, Any]:
    """Return a bounded sanitized DOM map for Great Walk control design."""
    raw = page.evaluate(_DISCOVER_DOM_JS)
    if not isinstance(raw, dict):
        return {
            "candidate_count": 0,
            "candidates": [],
            "visible_controls": [],
            "page_containers": {"form1_present": False, "form1_has_great_walk_descendants": False},
        }
    return {
        "candidate_count": int(raw.get("candidate_count") or 0),
        "candidates": list(raw.get("candidates") or [])[:_MAX_CANDIDATES],
        "visible_controls": list(raw.get("visible_controls") or [])[:_MAX_VISIBLE_CONTROLS],
        "page_containers": dict(raw.get("page_containers") or {}),
    }


def _candidate_text_blob(candidate: dict[str, Any]) -> str:
    parts = [
        candidate.get("id") or "",
        candidate.get("name") or "",
        candidate.get("class") or "",
        candidate.get("text") or "",
        candidate.get("role") or "",
        candidate.get("aria_label") or "",
        candidate.get("suggested_locator") or "",
    ]
    return " ".join(parts).lower()


def _pick_best(
    candidates: list[dict[str, Any]],
    *,
    predicate,
) -> dict[str, Any] | None:
    matches = [c for c in candidates if predicate(c) and c.get("visible")]
    if not matches:
        matches = [c for c in candidates if predicate(c)]
    if not matches:
        return None
    enabled = [c for c in matches if c.get("enabled")]
    return (enabled or matches)[0]


def _is_track_candidate(c: dict[str, Any]) -> bool:
    blob = _candidate_text_blob(c)
    if c.get("tag") not in ("BUTTON", "DIV", "SPAN", "A"):
        if c.get("role") not in ("combobox", "listbox", "button"):
            return False
    return ("dropdown" in blob or "combobox" in blob or c.get("role") == "combobox") and (
        "great" in blob or "walk" in blob or "track" in blob or "place" in blob
    )


def _is_date_candidate(c: dict[str, Any]) -> bool:
    if c.get("tag") not in ("INPUT", "BUTTON", "DIV", "SPAN"):
        return False
    blob = _candidate_text_blob(c)
    if c.get("type") in ("date", "hidden") and any(t in blob for t in ("date", "start", "arrival")):
        return True
    if "start-date" in blob or "startdate" in blob or "arrival" in blob:
        return True
    if c.get("tag") == "INPUT" and c.get("value") and re.match(r"^\d{4}-\d{2}-\d{2}", str(c.get("value"))):
        return True
    return False


def _is_nights_candidate(c: dict[str, Any]) -> bool:
    if c.get("tag") != "SELECT":
        return False
    blob = _candidate_text_blob(c)
    return "night" in blob or (c.get("selected_option_text") and "night" in str(c.get("text", "")).lower())


def _is_search_candidate(c: dict[str, Any]) -> bool:
    if c.get("tag") != "BUTTON" and c.get("role") != "button":
        return False
    blob = _candidate_text_blob(c)
    if re.search(r"\bsearch\b", blob):
        return "great" in blob or "walk" in blob or "facility" in blob or blob.strip() == "search"
    return "search-button" in blob or "btn-great-walk-search" in blob


_LOADING_TEXT_RE = re.compile(r"fetching content|loading\.{0,3}|please wait", re.IGNORECASE)


def _is_loading_indicator(c: dict[str, Any]) -> bool:
    text = c.get("text") or ""
    if not text:
        return False
    if _LOADING_TEXT_RE.search(text):
        return True
    role = c.get("role") or ""
    cls = (c.get("class") or "").lower()
    return role == "status" and ("loading" in cls or "spinner" in cls)


def _is_validation_indicator(c: dict[str, Any]) -> bool:
    if c.get("role") == "alert":
        text = c.get("text") or ""
        return bool(text) and not _LOADING_TEXT_RE.search(text)
    cls = (c.get("class") or "").lower()
    return "invalid-feedback" in cls or "field-validation-error" in cls


def assess_control_discovery(report: dict[str, Any]) -> ControlDiscoveryAssessment:
    """Check whether required GW controls are identifiable from a DOM report."""
    candidates = list(report.get("candidates") or [])
    containers = dict(report.get("page_containers") or {})

    found = {
        "track": _pick_best(candidates, predicate=_is_track_candidate),
        "start_date": _pick_best(candidates, predicate=_is_date_candidate),
        "nights": _pick_best(candidates, predicate=_is_nights_candidate),
        "search": _pick_best(candidates, predicate=_is_search_candidate),
    }

    missing = tuple(key for key, value in found.items() if value is None)
    loading = tuple(c for c in candidates if _is_loading_indicator(c))
    validation = tuple(c for c in candidates if _is_validation_indicator(c))

    form1_only = bool(
        containers.get("form1_present")
        and not containers.get("form1_has_great_walk_descendants")
        and missing
    )

    notes: list[str] = []
    if form1_only:
        notes.append(
            "ASP.NET form1 is present but contains no identifiable Great Walk widget descendants"
        )
    if missing:
        notes.append(f"Missing required controls: {', '.join(missing)}")

    complete = not missing
    return ControlDiscoveryAssessment(
        complete=complete,
        found=found,
        missing=missing,
        loading_indicators=loading[:5],
        validation_indicators=validation[:5],
        form1_is_only_container=form1_only,
        notes=tuple(notes),
    )


def build_discovery_summary(
    report: dict[str, Any],
    assessment: ControlDiscoveryAssessment,
    *,
    selection_metadata_confirmed: bool = False,
) -> dict[str, Any]:
    """Compact summary for diagnostics JSON."""
    return {
        "candidate_count": report.get("candidate_count", 0),
        "visible_control_count": len(report.get("visible_controls") or []),
        "page_containers": report.get("page_containers"),
        "selection_metadata_confirmed": selection_metadata_confirmed,
        "discovery_complete": assessment.complete,
        "found_controls": {
            key: (value.get("suggested_locator") if value else None)
            for key, value in assessment.found.items()
        },
        "missing_controls": list(assessment.missing),
        "form1_is_only_container": assessment.form1_is_only_container,
        "notes": list(assessment.notes),
        "loading_indicators": list(assessment.loading_indicators),
        "validation_indicators": list(assessment.validation_indicators),
    }

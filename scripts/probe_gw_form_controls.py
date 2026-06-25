"""Probe Great Walk form control DOM structure."""

from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROBE_JS = """() => {
    function describe(el) {
        if (!el) return null;
        const tag = el.tagName;
        const out = {
            id: el.id,
            tag,
            type: el.type || null,
            value: el.value ?? null,
            dataDate: el.getAttribute('data-date'),
            ariaLabel: el.getAttribute('aria-label'),
            text: (el.textContent || '').trim().slice(0, 80),
            disabled: !!el.disabled,
            visible: !!el.offsetParent,
        };
        if (tag === 'SELECT') {
            out.selectedValue = el.value;
            out.selectedIndex = el.selectedIndex;
            const opt = el.options[el.selectedIndex];
            out.selectedOptionText = opt ? opt.text.trim() : null;
            out.selectedOptionValue = opt ? opt.value : null;
            out.optionCount = el.options.length;
            out.options = Array.from(el.options).slice(0, 20).map(o => ({
                value: o.value, text: o.text.trim()
            }));
        }
        return out;
    }
    const ids = [
        'great-walk-dropdown-button',
        'great-walk-mobile-dropdown-button',
        'great-walk-start-date',
        'great-walk-nights',
        'great-walk-number-of-nights',
        'great-walk-search-button',
        'great-walk-search',
    ];
    const controls = {};
    for (const id of ids) controls[id] = describe(document.getElementById(id));
    const dateInputs = Array.from(
        document.querySelectorAll('input[id*="great-walk"], input[name*="date"], input[name*="Date"]')
    )
        .filter(e => /great|walk|date|night|arrival/i.test(e.id + e.name))
        .slice(0, 20)
        .map(e => ({ id: e.id, name: e.name, type: e.type, value: e.value }));
    return { controls, dateInputs };
}"""


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(
            "https://bookings.doc.govt.nz/Web/Default.aspx",
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        page.evaluate("window.location.hash = '#!greatwalk-result'")
        page.wait_for_function(
            '() => document.querySelectorAll("[id^=great-walk-]").length > 0',
            timeout=15_000,
        )
        page.wait_for_timeout(3_000)

        print("=== BEFORE SELECTION ===")
        print(json.dumps(page.evaluate(PROBE_JS), indent=2))

        page.evaluate("document.getElementById('great-walk-dropdown-button')?.click()")
        page.wait_for_timeout(500)
        page.evaluate("document.getElementById('great-walk-5')?.click()")
        page.wait_for_timeout(4_000)

        print("\n=== AFTER MILFORD SELECTION ===")
        print(json.dumps(page.evaluate(PROBE_JS), indent=2))

        browser.close()


if __name__ == "__main__":
    main()

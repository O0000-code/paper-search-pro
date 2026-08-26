"""Regression tests for safe report-data hydration in the HTML renderer."""

from __future__ import annotations

import json
import re

from scripts.html_renderer_webartifacts import _inject_report_data


def _injected_payload(html: str) -> str:
    marker = "window.__REPORT_DATA__ = "
    start = html.index(marker) + len(marker)
    end = html.index(";</script>", start)
    return html[start:end]


def test_injected_report_data_cannot_close_script_context():
    value = "</ScRiPt ><script>alert(1)</script>&\u2028\u2029"
    rendered = _inject_report_data(
        '<html><body><script src="/app.js"></script></body></html>',
        {"value": value},
    )
    injection = rendered.split('<script src="/app.js">', 1)[0]

    assert len(re.findall(r"</script\s*>", injection, flags=re.IGNORECASE)) == 1
    assert "\\u003c" in _injected_payload(rendered)
    assert json.loads(_injected_payload(rendered)) == {"value": value}


def test_injected_report_data_escapes_html_and_js_separators():
    value = "<>&\u2028\u2029"
    rendered = _inject_report_data("<body></body>", {"value": value})
    payload = _injected_payload(rendered)

    assert all(
        token in payload
        for token in ("\\u003c", "\\u003e", "\\u0026", "\\u2028", "\\u2029")
    )
    assert json.loads(payload) == {"value": value}

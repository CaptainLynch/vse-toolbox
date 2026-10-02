# -*- coding: utf-8 -*-
"""Safe Aras XML capture tests."""

from __future__ import annotations

import pytest

from services.aras_xml import ArasXmlCaptureError, sanitize_aras_xml


def test_sanitize_aras_xml_preserves_business_fields_and_redacts_sensitive_nodes() -> None:
    xml = (
        '<Envelope><Item><_no>EWO-1</_no><subject>seat change</subject>'
        '<token>fictional-token-secret</token><password>fictional-password-secret</password>'
        "</Item></Envelope>"
    )

    sanitized = sanitize_aras_xml(xml)

    assert "EWO-1" in sanitized
    assert "seat change" in sanitized
    assert "fictional-token-secret" not in sanitized
    assert "fictional-password-secret" not in sanitized
    assert "<token>[redacted]</token>" in sanitized
    assert "<password>[redacted]</password>" in sanitized


def test_sanitize_aras_xml_rejects_oversized_capture() -> None:
    with pytest.raises(ArasXmlCaptureError):
        sanitize_aras_xml("<Envelope>value</Envelope>", max_bytes=8)

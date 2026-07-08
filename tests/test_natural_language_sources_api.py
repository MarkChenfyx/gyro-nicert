from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app


def test_list_and_read_imported_natural_language_sources() -> None:
    client = TestClient(app)

    listed = client.get("/api/natural-language/sources")
    assert listed.status_code == 200
    payload = listed.json()
    names = [item["name"] for item in payload["files"]]
    assert "opening_range_breakout_intraday.txt" in names
    assert "bollinger_rsi_reversion_loose.txt" in names

    source = client.get("/api/natural-language/sources/opening_range_breakout_intraday.txt")
    assert source.status_code == 200
    source_payload = source.json()
    assert source_payload["name"] == "opening_range_breakout_intraday.txt"
    assert source_payload["text"].strip()


def test_natural_language_source_blocks_invalid_filename() -> None:
    client = TestClient(app)

    response = client.get("/api/natural-language/sources/not_a_text_file.py")
    assert response.status_code == 400

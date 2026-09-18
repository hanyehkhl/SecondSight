import json

import pytest

from app.modules.analysis import service as analysis_service
from app.modules.vision.service import MockVisionService
from tests.conftest import API, make_png, register_and_login


async def _upload(client, headers, content: bytes, name: str, content_type: str) -> dict:
    response = await client.post(f"{API}/files", headers=headers, files={"file": (name, content, content_type)})
    assert response.status_code == 201, response.text
    return response.json()


async def _run(client, headers, **body) -> dict:
    response = await client.post(f"{API}/analyses", headers=headers, json=body)
    assert response.status_code == 202, response.text
    # Inline background tasks finish before the ASGI transport returns.
    response = await client.get(f"{API}/analyses/{response.json()['id']}", headers=headers)
    assert response.status_code == 200
    return response.json()


async def test_full_flow_with_voice_question(client, auth_headers):
    image = await _upload(client, auth_headers, make_png(), "cxr.png", "image/png")
    assert image["kind"] == "image" and image["has_preview"]
    audio = await _upload(client, auth_headers, b"RIFF....WAVEfmt fake", "q.wav", "audio/wav")
    assert audio["kind"] == "audio"

    analysis = await _run(
        client, auth_headers, image_file_id=image["id"], audio_file_id=audio["id"], modality="Chest X-ray"
    )
    assert analysis["status"] == "completed"
    assert analysis["transcribed_question"]
    assert analysis["needs_human_review"] is False
    assert analysis["result"]["overall_confidence"] == pytest.approx(0.8)
    assert analysis["model_info"]["vision"] == "mock-vision"

    report = (await client.get(f"{API}/reports/{analysis['id']}", headers=auth_headers)).json()
    assert report["language"] == "en"
    assert report["confidence_level"] == "high"
    assert "Findings" in report["text"]

    fa = await client.get(f"{API}/reports/{analysis['id']}?language=fa&format=text", headers=auth_headers)
    assert fa.status_code == 200
    assert "یافته‌ها" in fa.text

    listing = (await client.get(f"{API}/analyses", headers=auth_headers)).json()
    assert analysis["id"] in [a["id"] for a in listing]


async def test_other_users_cannot_see_data(client, auth_headers):
    image = await _upload(client, auth_headers, make_png(), "cxr.png", "image/png")
    analysis = await _run(client, auth_headers, image_file_id=image["id"], question="Any nodules?", modality="CT")

    intruder = await register_and_login(client)
    assert (await client.get(f"{API}/files/{image['id']}", headers=intruder)).status_code == 404
    assert (await client.get(f"{API}/files/{image['id']}/preview", headers=intruder)).status_code == 404
    assert (await client.get(f"{API}/analyses/{analysis['id']}", headers=intruder)).status_code == 404
    assert (await client.get(f"{API}/reports/{analysis['id']}", headers=intruder)).status_code == 404
    response = await client.post(
        f"{API}/analyses", headers=intruder, json={"image_file_id": image["id"], "question": "x", "modality": "CT"}
    )
    assert response.status_code == 422


async def test_validation_errors(client, auth_headers):
    image = await _upload(client, auth_headers, make_png(), "cxr.png", "image/png")
    # No question at all
    response = await client.post(
        f"{API}/analyses", headers=auth_headers, json={"image_file_id": image["id"], "modality": "CT"}
    )
    assert response.status_code == 422
    # Modality required for non-DICOM images
    response = await client.post(
        f"{API}/analyses", headers=auth_headers, json={"image_file_id": image["id"], "question": "?"}
    )
    assert response.status_code == 422
    # Not an image
    response = await client.post(
        f"{API}/files", headers=auth_headers, files={"file": ("x.png", b"not an image", "image/png")}
    )
    assert response.status_code == 422


class _LowConfidenceVision(MockVisionService):
    async def _complete(self, system, turns, image_png):
        data = json.loads(await super()._complete(system, turns, image_png))
        data["overall_confidence"] = 0.35
        data["findings"][0].update(severity="severe", confidence=0.4)
        return json.dumps(data)


class _BrokenVision(MockVisionService):
    calls = 0

    async def _complete(self, system, turns, image_png):
        type(self).calls += 1
        return "I am unable to comply with the JSON format."


async def test_low_confidence_is_flagged_for_human_review(client, auth_headers, monkeypatch):
    monkeypatch.setattr(analysis_service, "get_vision_service", lambda: _LowConfidenceVision())
    image = await _upload(client, auth_headers, make_png(), "cxr.png", "image/png")
    analysis = await _run(
        client, auth_headers, image_file_id=image["id"], question="Pneumonia?", modality="Chest X-ray"
    )

    assert analysis["status"] == "needs_review"
    assert analysis["needs_human_review"] is True
    assert set(analysis["review_reasons"]) == {"low_overall_confidence", "low_confidence_severe_finding"}
    report = (await client.get(f"{API}/reports/{analysis['id']}?format=text", headers=auth_headers)).text
    assert "HUMAN REVIEW REQUIRED" in report


async def test_model_failure_falls_back_to_human_review(client, auth_headers, monkeypatch):
    monkeypatch.setattr(analysis_service, "get_vision_service", lambda: _BrokenVision(max_retries=2))
    image = await _upload(client, auth_headers, make_png(), "cxr.png", "image/png")
    analysis = await _run(
        client, auth_headers, image_file_id=image["id"], question="Pneumonia?", modality="Chest X-ray"
    )

    assert _BrokenVision.calls == 3  # first attempt + 2 repair retries
    assert analysis["status"] == "needs_review"
    assert analysis["review_reasons"] == ["model_unavailable"]
    assert analysis["result"] is None
    report = (await client.get(f"{API}/reports/{analysis['id']}", headers=auth_headers)).json()
    assert report["needs_human_review"] is True
    assert report["findings"] == []

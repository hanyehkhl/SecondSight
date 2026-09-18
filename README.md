# SecondSight

A backend for AI medical second opinions. A physician uploads an image (PNG/JPEG/TIFF or DICOM) and asks a question by voice or text. MedASR turns the audio into text and MedGemma analyzes the image. The service returns a structured report in Persian or English, with confidence scores. Results with low confidence, or without a valid model answer, are flagged **needs human review**.

> ⚠️ This is decision-support software, not a medical device. Every output must be verified by a qualified clinician.

## Architecture

```
Frontend ──► FastAPI (/api/v1) ──► auth · files · analyses · reports
                                        │
                        ┌───────────────┼────────────────┐
                        ▼               ▼                ▼
                  speech (MedASR)  vision (MedGemma)  report (confidence gate + fa/en rendering)
                        └───────── analysis pipeline ────┘
                             (inline background task or Celery worker)
            audit log · encrypted storage (local / S3 / MinIO) · webhook notification
```

| Module | Path | Notes |
|---|---|---|
| auth | `app/api/v1/endpoints/auth.py`, `app/core/security.py` | JWT (OAuth2 password flow), scrypt password hashing; roles: physician, patient, clinic, admin |
| file | `app/modules/file/` | Uploads are Fernet-encrypted at rest. DICOM files are rendered to PNG (modality/VOI LUT, MONOCHROME1, multi-frame), and only non-identifying tags are kept. EXIF is stripped from images. |
| speech | `app/modules/speech/service.py` | `SpeechService` interface with `mock`, `medasr_local` (transformers) and `medasr_http` backends |
| vision | `app/modules/vision/` | `VisionService` interface with `mock`, `medgemma_local` (transformers) and `medgemma_openai` (vLLM/TGI/any OpenAI-compatible endpoint) backends. JSON is parsed and validated, and malformed output triggers repair retries. |
| report | `app/modules/report/` | Confidence gate, deterministic fa/en templates, optional LLM rewrite (`REPORT_LLM_ENABLED`) |
| analysis | `app/modules/analysis/` | Pipeline orchestration and task dispatch |
| audit | `app/modules/audit/` | Append-only log of logins, uploads, views, and analysis outcomes. Clinical content is never written to it. |
| notification | `app/modules/notification/` | Webhook sent when an analysis finishes (IDs and status only) |

Prompts live in [`prompts/`](prompts/) and are loaded at runtime, so you can edit them without changing code.

### Human-review fallback

An analysis ends as `needs_review` instead of `completed` when any of these is true:

- MedGemma failed or returned output that could not be parsed after `VISION_MAX_RETRIES` repair attempts (`model_unavailable`)
- `overall_confidence < MIN_CONFIDENCE_THRESHOLD` (`low_overall_confidence`)
- a `severe` finding has confidence below the threshold (`low_confidence_severe_finding`)
- the answer to the question is empty (`no_answer`)

## Quick start (mock models, no GPU)

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows; use `source .venv/bin/activate` on Linux/macOS
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Open http://localhost:8000/docs. The flow:

1. `POST /api/v1/auth/register`, then `POST /api/v1/auth/token`
2. `POST /api/v1/files` with the image (and again with the audio recording, if any)
3. `POST /api/v1/analyses` with `{"image_file_id", "audio_file_id"?, "question"?, "modality"?, "clinical_context"?, "language": "fa"|"en"}` (returns 202)
4. Poll `GET /api/v1/analyses/{id}` until `status` is `completed`, `needs_review` or `failed`
5. `GET /api/v1/reports/{id}?language=fa&format=text`

## Real models

**Served MedGemma (recommended).** Run MedGemma behind an OpenAI-compatible server, for example `vllm serve google/medgemma-1.5-4b-it`, then set:

```
VISION_BACKEND=medgemma_openai
MEDGEMMA_ENDPOINT_URL=http://localhost:8000/v1
MEDGEMMA_MODEL_ID=google/medgemma-1.5-4b-it
```

**In-process.** Run `pip install -r requirements-ml.txt`, accept the model licenses on Hugging Face, and run `huggingface-cli login`. Then set `VISION_BACKEND=medgemma_local` and/or `SPEECH_BACKEND=medasr_local`. Use `TASK_BACKEND=celery` so that models load in the worker, not in the API process.

## Full stack

```bash
docker compose up --build
```

This starts the API, a Celery worker, Postgres, Redis and MinIO. Before any non-dev deployment, set `JWT_SECRET` and `STORAGE_ENCRYPTION_KEY`. The app refuses to start in `ENVIRONMENT=production` without them.

## Tests

```bash
pytest
```

## Not yet included

- Frontend (upload, recording, report and heatmap display). The API returns a `preview` PNG for display, but MedGemma does not produce saliency heatmaps. A heatmap needs a separate method (e.g. attention/Grad-CAM on the vision encoder).
- Alembic migrations (tables are created on startup)
- Human-review workflow (assigning `needs_review` cases to a radiologist)

# Carousel Pipeline

This folder contains a scheduled Instagram carousel pipeline plus separate,
manual image-provider and LTX-2 GPU experiments. The checked-in implementation
is authoritative; older notes described planned features that are not enabled.

## Instagram publishing flow

The workflow is
`.github/workflows/carousel-pipeline.yml`. It runs daily at 07:30 UTC and can
also be started manually. Each run publishes at most one queued carousel.
`run_pipeline.py` sets `POSTS_PER_DAY = 4`, but the other three cron entries
are commented out, so the current schedule does not publish four times daily.

```text
workflow → run_pipeline.py
         → queue_manager.py (load or generate today's queue)
         → generate_thought.py (Groq produces slide text)
         → compose_carousel.py (Pillow renders PNG slides)
         → commit images → wait for public raw-content URLs
         → post_carousel.py (publish to Instagram)
         → update queue state
```

`compose_carousel.py` renders the backgrounds locally; there is no active
`generate_background.py` step. `post_carousel.py` contains Facebook publishing
helpers, but `run_pipeline.py` currently leaves the Facebook call commented
out. The active workflow publishes to Instagram only.

### State and output

- `state/queue.json` tracks the day's generated thoughts and whether each has
  been posted.
- `carousel-images/<thought-id>/` holds the PNG slides, committed by the
  pipeline so Meta can fetch public URLs.
- `output/` is a temporary rendering directory and can be recreated.

### Configuration

The workflow reads these GitHub Actions secrets:

- `GROQ_API_KEY` — generate carousel text.
- `IG_USER_ID` and `META_SYSTEM_USER_TOKEN` — publish to Instagram.
- `FB_PAGE_ID` is supplied by the workflow for the currently disabled
  Facebook integration.

The `IMAGE_HOST_BASE` Actions variable must be the public raw-content base
ending in `/social-media-automatio` and before `/carousel-images` (for
example, `https://raw.githubusercontent.com/<owner>/<repo>/<branch>/social-media-automatio`).
The script appends `/carousel-images/<thought-id>/<file>` itself. Without
this variable, its placeholder default is not a usable image host. The
workflow token also needs repository write access so the pipeline can commit
images and queue state.

### Manual image API comparison

`test_image_apis.py` and `.github/workflows/test-image-apis.yml` are a manual
experiment that makes requests to external image services and stores results
as a short-lived workflow artifact. It is not a unit-test suite and is not
part of scheduled carousel generation.

## LTX-2 GPU experiments

The `ltx2-video-gpu/` directory contains Vast.ai lifecycle and weight-volume
workflows, bootstrap scripts, a container build fallback, and cost logs. These
are manually dispatched and separate from Instagram publishing. See
`ltx2-video-gpu/model-deployment/` and the workflow input descriptions before
creating paid resources. Two setup-volume workflows currently coexist; check
their contents before choosing one.

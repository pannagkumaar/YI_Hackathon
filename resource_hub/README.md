# SHIVA Resource Hub (Phase1+ scaffold)

## Quickstart (recommended)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export SHIVA_SHARED_SECRET=dev-secret
export DIRECTORY_URL=http://127.0.0.1:8005     # optional
export OVERSEER_URL=http://127.0.0.1:8006      # optional

uvicorn main:app --reload

## Endpoints
- POST /tools/register
- GET /tools/list
- POST /tools/execute
- POST /memory/short-term/save
- GET  /memory/short-term/{task_id}
- POST /mock/itsm/change
- GET  /mock/itsm/change
- GET  /demo/sequence

## Tests
pytest -q

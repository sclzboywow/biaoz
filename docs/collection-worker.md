# Collection Worker

URL collection tasks can run in two modes:

- Local default: FastAPI starts the task inline through `BackgroundTasks`.
- Production/Docker default: the API only creates pending tasks, and `collection-worker` processes them.

## Environment

`COLLECTION_TASK_INLINE_WORKER=true` keeps the old local behavior.

`COLLECTION_TASK_INLINE_WORKER=false` leaves tasks in `pending` state until a worker claims them.

## Local Worker

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-collection-worker.ps1
```

Process one pending task and exit:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-collection-worker.ps1 -Once
```

## Docker

`docker compose up --build` starts a dedicated `collection-worker` service. The frontend still listens on host port `5173`, while nginx serves the built frontend inside the container on port `80`.

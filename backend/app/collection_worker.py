from __future__ import annotations

import argparse
import socket

from app.collection_tasks import run_pending_url_check_tasks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run pending URL collection tasks.")
    parser.add_argument("--once", action="store_true", help="Process at most one pending task and exit.")
    parser.add_argument("--max-tasks", type=int, default=0, help="Process N tasks and exit. 0 means run forever.")
    parser.add_argument("--poll-seconds", type=float, default=5.0, help="Seconds to wait when no pending task exists.")
    parser.add_argument("--worker-id", default=None, help="Worker id stored on collection task rows.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    max_tasks = 1 if args.once else max(args.max_tasks, 0)
    worker_id = args.worker_id or f"collection-worker-{socket.gethostname()}"
    processed = run_pending_url_check_tasks(max_tasks=max_tasks, poll_seconds=args.poll_seconds, worker_id=worker_id)
    print(f"processed_tasks={processed}", flush=True)


if __name__ == "__main__":
    main()

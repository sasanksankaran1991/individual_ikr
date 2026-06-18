"""Non-blocking background scheduler for Streamlit (avoids UI freezes on Telegram API)."""

from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_running = False
_last_finished = 0.0
_loop_started = False


def schedule_background_tick(min_interval_seconds: int, *, force: bool = False) -> None:
    """Run Telegram poll + reminders on a daemon thread if due."""
    global _running, _last_finished

    now = time.time()
    if not force and (_running or (now - _last_finished) < min_interval_seconds):
        return
    if not _lock.acquire(blocking=False):
        return

    def _work() -> None:
        global _running, _last_finished
        _running = True
        try:
            from background_scheduler import run_background_tick

            run_background_tick()
        except Exception:
            pass
        finally:
            _last_finished = time.time()
            _running = False
            _lock.release()

    threading.Thread(target=_work, daemon=True, name="ikr-scheduler").start()


def start_background_loop(min_interval_seconds: int) -> None:
    """Start a daemon loop so Telegram polling works without st.fragment reruns."""
    global _loop_started
    interval = max(30, int(min_interval_seconds))
    if _loop_started:
        return
    _loop_started = True

    def _loop() -> None:
        while True:
            schedule_background_tick(interval)
            time.sleep(interval)

    threading.Thread(target=_loop, daemon=True, name="ikr-scheduler-loop").start()

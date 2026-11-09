import random
import time


def fetch_status(service: str) -> dict:
    """Ask a (simulated) remote service for its status. Network latency varies."""
    time.sleep(random.uniform(0.0, 0.1))
    return {"service": service, "ok": True}

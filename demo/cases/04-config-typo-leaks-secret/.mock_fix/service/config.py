DEFAULTS = {"timeout": 30, "retries": 3}

def load(overrides):
    cfg = dict(DEFAULTS)
    cfg.update(overrides)
    timeout = cfg.get("timeout")
    if not timeout or timeout <= 0:
        raise ValueError(f"missing or bad timeout in config: {cfg}")
    return cfg

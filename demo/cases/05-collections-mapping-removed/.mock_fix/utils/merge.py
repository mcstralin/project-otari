from collections.abc import Mapping

def deep_merge(a, b):
    """Recursively merge mapping b into a copy of a."""
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, Mapping) and isinstance(out.get(k), Mapping):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out

def paginate(items, page, size):
    """Return the items on 1-indexed `page` with `size` items per page."""
    start = page * size
    return items[start:start + size]

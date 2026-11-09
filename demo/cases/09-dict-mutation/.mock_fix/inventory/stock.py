def restock(stock, delivery):
    """Return a NEW stock dict with the delivery added; never mutate the input."""
    result = dict(stock)
    for item, qty in delivery.items():
        result[item] = result.get(item, 0) + qty
    return result

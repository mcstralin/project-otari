def restock(stock, delivery):
    """Return a NEW stock dict with the delivery added; never mutate the input."""
    result = stock.copy()
    for item, qty in delivery.items():
        result[item] = result.get(item, 0) + qty
    return result

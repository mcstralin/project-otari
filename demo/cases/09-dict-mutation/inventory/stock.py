def restock(stock, delivery):
    """Return a NEW stock dict with the delivery added; never mutate the input."""
    for item, qty in delivery.items():
        stock[item] = stock.get(item, 0) + qty
    return stock

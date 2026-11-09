def parse_price(text):
    """'$12.50' -> 12.5"""
    return text.strip().lstrip("$")

def cart_total(prices):
    return round(sum(parse_price(p) for p in prices), 2)

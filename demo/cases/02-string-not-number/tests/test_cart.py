from billing.cart import cart_total, parse_price

def test_parse_price():
    assert parse_price("$12.50") == 12.5

def test_cart_total():
    assert cart_total(["$1.10", "$2.20", " $3.30 "]) == 6.6

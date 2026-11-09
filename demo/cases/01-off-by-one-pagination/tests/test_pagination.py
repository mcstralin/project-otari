from shop.pagination import paginate

def test_first_page():
    assert paginate(list(range(10)), 1, 3) == [0, 1, 2]

def test_last_partial_page():
    assert paginate(list(range(10)), 4, 3) == [9]

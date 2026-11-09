from inventory.stock import restock

def test_adds_quantities():
    assert restock({"apple": 1}, {"apple": 2, "pear": 1}) == {"apple": 3, "pear": 1}

def test_does_not_mutate_input():
    before = {"apple": 1}
    restock(before, {"apple": 5})
    assert before == {"apple": 1}

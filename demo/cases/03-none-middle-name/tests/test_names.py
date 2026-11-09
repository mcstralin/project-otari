from people.names import full_name

def test_with_middle():
    assert full_name({"first": "Ada", "middle": "K", "last": "Lovelace"}) == "Ada K Lovelace"

def test_without_middle():
    assert full_name({"first": "Alan", "middle": None, "last": "Turing"}) == "Alan Turing"
    assert full_name({"first": "Grace", "last": "Hopper"}) == "Grace Hopper"

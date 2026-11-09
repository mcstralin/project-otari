from utils.merge import deep_merge

def test_nested_merge():
    assert deep_merge({"a": {"x": 1}, "b": 2}, {"a": {"y": 3}}) == {"a": {"x": 1, "y": 3}, "b": 2}

def test_override():
    assert deep_merge({"a": 1}, {"a": {"z": 0}}) == {"a": {"z": 0}}

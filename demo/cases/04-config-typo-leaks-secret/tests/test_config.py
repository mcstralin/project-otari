from service.config import load

# A real-world smell: the test config carries a credential and the
# failure message dumps the whole config into the CI log.
TEST_CFG = {"api_token": "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8", "timeout": 10}

def test_override_timeout():
    assert load(TEST_CFG)["timeout"] == 10

def test_defaults():
    assert load({})["retries"] == 3

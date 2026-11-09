from blog.urls import post_url

def test_post_url():
    assert post_url("Hello, Otari World!") == "/posts/hello-otari-world"

import vendor.slugkit as slugkit

def post_url(title):
    return "/posts/" + slugkit.make_slug(title, "-")

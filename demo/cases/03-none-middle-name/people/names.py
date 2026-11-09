def full_name(user):
    parts = [user["first"], user.get("middle"), user["last"]]
    return " ".join(parts)

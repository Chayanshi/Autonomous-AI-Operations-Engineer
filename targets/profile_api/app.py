from fastapi import FastAPI, HTTPException

app = FastAPI()

USERS = {
    1: {"id": 1, "name": "Ada", "email": "ADA@example.com"},
    2: {"id": 2, "name": "Grace", "email": None},
}


@app.get("/api/users/{user_id}/profile")
def get_profile(user_id: int):
    """Return a user's public profile with a normalised email address."""
    user = USERS.get(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"id": user["id"], "name": user["name"], "email": user["email"].lower()}

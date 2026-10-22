from fastapi import FastAPI, HTTPException

app = FastAPI()


@app.get("/api/users")
def get_users():
    """Return users. The error is intentional for the investigation baseline."""
    raise HTTPException(status_code=500, detail="Intentional baseline failure")

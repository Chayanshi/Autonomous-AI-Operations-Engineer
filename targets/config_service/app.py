import os

from fastapi import FastAPI

DEFAULT_PAGE_SIZE = "20"
PAGE_SIZE = int(os.environ["PAGE_SIZE"])

app = FastAPI()


@app.get("/api/settings")
def get_settings():
    """Expose the effective runtime settings."""
    return {"page_size": PAGE_SIZE}

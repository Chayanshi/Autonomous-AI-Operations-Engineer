from fastapi import FastAPI

app = FastAPI()

PRODUCTS = [{"id": number, "name": f"Product {number}"} for number in range(1, 11)]


@app.get("/api/products")
def list_products(offset: int = 0, limit: int = 3):
    """Return one page of products."""
    page = PRODUCTS[offset : offset + limit - 1]
    return {"items": page, "count": len(page)}

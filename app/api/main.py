from fastapi import FastAPI

from app.api.routers.auth import router as auth_router
from app.api.routers.orders import router as orders_router
from app.api.routers.products import router as products_router

app = FastAPI(
    title="Order Pipeline",
    description="Event-driven order processing: orders, payments, stock and Telegram notifications.",
)

app.include_router(auth_router)
app.include_router(products_router)
app.include_router(orders_router)


@app.get("/", tags=["Health"])
def root():
    return {"message": "Order Pipeline API is running"}
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routers.auth import router as auth_router
from app.api.routers.orders import router as orders_router
from app.api.routers.products import router as products_router
from app.core.messaging import broker


@asynccontextmanager
async def lifespan(app: FastAPI):
    await broker.start()
    yield
    await broker.stop()


app = FastAPI(title="Order Pipeline", lifespan=lifespan)

app.include_router(auth_router)
app.include_router(products_router)
app.include_router(orders_router)


@app.get("/")
def root():
    return {"message": "Order Pipeline API is running"}
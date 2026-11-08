from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import get_current_admin
from app.database import get_session
from app.models.product import Product
from app.schemas.product import ProductCreate, ProductRead, ProductUpdate

router = APIRouter()


@router.get("/products", response_model=list[ProductRead])
async def list_products(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    query = select(Product).order_by(Product.id).limit(limit).offset(offset)
    result = await session.execute(query)
    return result.scalars().all()


@router.get("/products/{product_id}", response_model=ProductRead)
async def get_product(product_id: int, session: AsyncSession = Depends(get_session)):
    product = await session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.post(
    "/products",
    response_model=ProductRead,
    status_code=201,
    dependencies=[Depends(get_current_admin)],
)
async def create_product(data: ProductCreate, session: AsyncSession = Depends(get_session)):
    product = Product(**data.model_dump())
    session.add(product)
    await session.commit()
    await session.refresh(product)
    return product


@router.patch(
    "/products/{product_id}",
    response_model=ProductRead,
    dependencies=[Depends(get_current_admin)],
)
async def update_product(
    product_id: int,
    data: ProductUpdate,
    session: AsyncSession = Depends(get_session),
):
    product = await session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(product, field, value)

    session.add(product)
    await session.commit()
    await session.refresh(product)
    return product
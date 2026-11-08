from decimal import Decimal


async def test_order_total_is_calculated_by_server(api, user_headers, products):
    keyboard, mouse, _ = products
    response = await api.post(
        "/orders",
        json={"items": [
            {"product_id": keyboard, "quantity": 2},
            {"product_id": mouse, "quantity": 1},
        ]},
        headers=user_headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert Decimal(str(body["total_amount"])) == Decimal("44.80")
    assert body["status"] == "new"
    assert len(body["items"]) == 2


async def test_unknown_product_returns_404_and_creates_nothing(api, user_headers):
    response = await api.post(
        "/orders",
        json={"items": [{"product_id": 999, "quantity": 1}]},
        headers=user_headers,
    )
    assert response.status_code == 404

    orders = await api.get("/orders", headers=user_headers)
    assert orders.json() == []


async def test_patch_changes_only_sent_fields(api, admin_headers, products):
    keyboard = products[0]
    response = await api.patch(
        f"/products/{keyboard}", json={"stock": 15}, headers=admin_headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["stock"] == 15
    assert body["name"] == "Keyboard"
    assert Decimal(str(body["price"])) == Decimal("19.90")


async def test_user_cannot_post_products(api, admin_headers, user_headers):
    response = await api.post(
        "/products",
        json={"name": "New Product", "price": 10.0, "stock": 5},
        headers=user_headers,
    )
    assert response.status_code == 403

    response = await api.post(
        "/products",
        json={"name": "New Product", "price": 10.0, "stock": 5},
        headers=admin_headers,
    )
    assert response.status_code == 201

async def test_user_cannot_access_other_users_orders(
    api, user_headers, other_user_headers, products
):
    keyboard = products[0]

    # othher user creates order
    created = await api.post(
        "/orders",
        json={"items": [{"product_id": keyboard, "quantity": 1}]},
        headers=other_user_headers,
    )
    assert created.status_code == 201
    order_id = created.json()["id"]

    # order owner can see the order
    owner_view = await api.get(f"/orders/{order_id}", headers=other_user_headers)
    assert owner_view.status_code == 200
    owner_list = await api.get("/orders", headers=other_user_headers)
    assert len(owner_list.json()) == 1

    # other user cannot see the order
    stranger_list = await api.get("/orders", headers=user_headers)
    assert stranger_list.json() == []
    stranger_view = await api.get(f"/orders/{order_id}", headers=user_headers)
    assert stranger_view.status_code == 404


async def test_duplicate_items_are_merged(api, user_headers, products):
    keyboard = products[0]
    response = await api.post(
        "/orders",
        json={"items": [
            {"product_id": keyboard, "quantity": 1},
            {"product_id": keyboard, "quantity": 2},
        ]},
        headers=user_headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["quantity"] == 3
    assert Decimal(str(body["total_amount"])) == Decimal("59.70")   # 19.90 * 3


async def test_client_cannot_set_price(api, user_headers, products):
    keyboard = products[0]
    response = await api.post(
        "/orders",
        json={"items": [{"product_id": keyboard, "quantity": 1, "price": "0.01"}]},
        headers=user_headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert Decimal(str(body["total_amount"])) == Decimal("19.90")
    assert Decimal(str(body["items"][0]["unit_price"])) == Decimal("19.90")


async def test_old_order_keeps_original_price(api, user_headers, admin_headers, products):
    keyboard = products[0]
    created = await api.post(
        "/orders",
        json={"items": [{"product_id": keyboard, "quantity": 1}]},
        headers=user_headers,
    )
    order_id = created.json()["id"]

    # админ меняет цену товара уже после заказа
    await api.patch(
        f"/products/{keyboard}", json={"price": "99.00"}, headers=admin_headers
    )

    response = await api.get(f"/orders/{order_id}", headers=user_headers)
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert Decimal(str(item["unit_price"])) == Decimal("19.90")
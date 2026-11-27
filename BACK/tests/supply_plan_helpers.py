def select_recommendations(client, url, plan, headers=None):
    """Explicit user selection, kept separate from creating an empty document."""
    rows = client.get(url + "/products", headers=headers, params={"limit": 100}).json()["items"]
    rows = sorted(
        (r for r in rows if r["recommended_quantity"]), key=lambda r: -r["recommended_quantity"]
    )
    response = client.post(
        url + "/products",
        headers=headers,
        json={"revision": plan["revision"], "product_keys": [r["product_key"] for r in rows]},
    )
    assert response.status_code == 200, response.text
    selected = response.json()
    quantities = {r["product_key"]: r["recommended_quantity"] for r in rows}
    response = client.put(
        url,
        headers=headers,
        json={
            "revision": selected["revision"],
            "title": selected["title"],
            "destination": selected["destination"],
            "status": "draft",
            "items": [
                {"product_key": i["product_key"], "quantity": quantities[i["product_key"]]}
                for i in selected["items"]
            ],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()

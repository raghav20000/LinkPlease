import pytest


@pytest.mark.asyncio
async def test_create_rule_returns_201_with_shape(client):
    resp = await client.post("/rules", json={"keyword": "PRICE", "dm_message": "Here's the price list"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["keyword"] == "PRICE"
    assert body["dm_message"] == "Here's the price list"
    assert isinstance(body["rule_id"], str) and body["rule_id"]


@pytest.mark.asyncio
async def test_two_rules_get_distinct_ids(client):
    r1 = await client.post("/rules", json={"keyword": "PRICE", "dm_message": "a"})
    r2 = await client.post("/rules", json={"keyword": "INFO", "dm_message": "b"})
    assert r1.json()["rule_id"] != r2.json()["rule_id"]

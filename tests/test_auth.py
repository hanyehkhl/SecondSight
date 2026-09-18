from tests.conftest import API, register_and_login


async def test_register_login_and_me(client):
    headers = await register_and_login(client, role="clinic")
    response = await client.get(f"{API}/auth/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["role"] == "clinic"


async def test_duplicate_email_rejected(client):
    body = {"email": "dup@example.com", "password": "long-enough-pw", "full_name": "A"}
    assert (await client.post(f"{API}/auth/register", json=body)).status_code == 201
    assert (await client.post(f"{API}/auth/register", json=body)).status_code == 409


async def test_admin_cannot_self_register(client):
    body = {"email": "root@example.com", "password": "long-enough-pw", "full_name": "A", "role": "admin"}
    assert (await client.post(f"{API}/auth/register", json=body)).status_code == 403


async def test_wrong_password_and_missing_token(client):
    body = {"email": "wrong@example.com", "password": "long-enough-pw", "full_name": "A"}
    await client.post(f"{API}/auth/register", json=body)
    response = await client.post(f"{API}/auth/token", data={"username": body["email"], "password": "nope-nope-nope"})
    assert response.status_code == 401
    assert (await client.get(f"{API}/auth/me")).status_code == 401
    assert (await client.get(f"{API}/auth/me", headers={"Authorization": "Bearer garbage"})).status_code == 401

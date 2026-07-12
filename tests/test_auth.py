def test_home_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Campus Plug" in response.data

def test_login_page(client):
    response = client.get("/auth/login")
    assert response.status_code == 200

def test_register_page(client):
    response = client.get("/auth/register")
    assert response.status_code == 200

def test_marketplace_page(client):
    response = client.get("/marketplace")
    assert response.status_code == 200

def test_freelance_page(client):
    response = client.get("/freelance")
    assert response.status_code == 200

def test_terms_page(client):
    response = client.get("/terms")
    assert response.status_code == 200

def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200

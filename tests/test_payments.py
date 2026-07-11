import json


def test_dashboard_requires_login(client):
    response = client.get('/payments/dashboard', follow_redirects=True)
    assert response.status_code == 200


def test_checkout_requires_login(client):
    response = client.get('/payments/checkout', follow_redirects=True)
    assert response.status_code == 200


def test_webhook_missing_signature(client):
    response = client.post('/payments/webhook',
                           data=json.dumps({"event": "charge.success"}),
                           content_type='application/json')
    assert response.status_code == 400


def test_webhook_bad_signature(client):
    response = client.post('/payments/webhook',
                           data=json.dumps({"event": "charge.success"}),
                           content_type='application/json',
                           headers={'x-paystack-signature': 'fake'})
    assert response.status_code == 400


def test_health_endpoint(client):
    response = client.get('/health')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'healthy'


def test_marketplace_browse_loads(client, db):
    response = client.get('/marketplace')
    assert response.status_code == 200


def test_freelance_browse_loads(client, db):
    response = client.get('/freelance')
    assert response.status_code == 200


def test_index_loads(client, db):
    response = client.get('/')
    assert response.status_code == 200


def test_leaderboard_loads(client, db):
    response = client.get('/leaderboard')
    assert response.status_code == 200


def test_terms_loads(client):
    response = client.get('/terms')
    assert response.status_code == 200

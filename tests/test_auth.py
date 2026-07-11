def test_register_page_loads(client):
    response = client.get('/auth/register')
    assert response.status_code in (200, 302)


def test_register_success(client, db):
    response = client.post('/auth/register', data={
        'email': 'test@ug.edu.gh',
        'full_name': 'Test User',
        'password': 'TestPass@123',
        'confirm_password': 'TestPass@123',
        'university': 'University of Ghana',
        'phone': '0241234567',
        'momo_provider': 'MTN Mobile Money',
        'account_type': 'regular',
    }, follow_redirects=True)
    assert response.status_code == 200
    client.get('/auth/logout', follow_redirects=True)


def test_register_duplicate_email(client, db):
    client.post('/auth/register', data={
        'email': 'dup@ug.edu.gh',
        'full_name': 'First User',
        'password': 'TestPass@123',
        'confirm_password': 'TestPass@123',
        'university': 'University of Ghana',
        'phone': '0241234567',
        'momo_provider': 'MTN Mobile Money',
        'account_type': 'regular',
    })
    client.get('/auth/logout', follow_redirects=True)
    response = client.post('/auth/register', data={
        'email': 'dup@ug.edu.gh',
        'full_name': 'Second User',
        'password': 'TestPass@123',
        'confirm_password': 'TestPass@123',
        'university': 'KNUST',
        'phone': '0551234567',
        'momo_provider': 'MTN Mobile Money',
        'account_type': 'regular',
    }, follow_redirects=True)
    assert response.status_code == 200


def test_register_weak_password(client, db):
    response = client.post('/auth/register', data={
        'email': 'weak@ug.edu.gh',
        'full_name': 'Weak Password',
        'password': 'short',
        'confirm_password': 'short',
        'university': 'University of Ghana',
        'phone': '0241234567',
        'momo_provider': 'MTN Mobile Money',
        'account_type': 'regular',
    }, follow_redirects=True)
    assert response.status_code == 200


def test_login_page_loads(client):
    response = client.get('/auth/login')
    assert response.status_code in (200, 302)


def test_login_success(client, db):
    client.post('/auth/register', data={
        'email': 'login@ug.edu.gh',
        'full_name': 'Login User',
        'password': 'TestPass@123',
        'confirm_password': 'TestPass@123',
        'university': 'University of Ghana',
        'phone': '0241234567',
        'momo_provider': 'MTN Mobile Money',
        'account_type': 'regular',
    })
    client.get('/auth/logout', follow_redirects=True)
    response = client.post('/auth/login', data={
        'email': 'login@ug.edu.gh',
        'password': 'TestPass@123',
    }, follow_redirects=True)
    assert response.status_code == 200


def test_login_wrong_password(client, db):
    client.post('/auth/register', data={
        'email': 'wrong@ug.edu.gh',
        'full_name': 'Wrong Pass',
        'password': 'TestPass@123',
        'confirm_password': 'TestPass@123',
        'university': 'University of Ghana',
        'phone': '0241234567',
        'momo_provider': 'MTN Mobile Money',
        'account_type': 'regular',
    })
    client.get('/auth/logout', follow_redirects=True)
    response = client.post('/auth/login', data={
        'email': 'wrong@ug.edu.gh',
        'password': 'WrongPass@999',
    }, follow_redirects=True)
    assert response.status_code == 200


def test_heartbeat_requires_auth(client):
    response = client.post('/auth/heartbeat')
    assert response.status_code in (302, 401, 403)


def test_logout_requires_auth(client):
    response = client.get('/auth/logout', follow_redirects=True)
    assert response.status_code == 200

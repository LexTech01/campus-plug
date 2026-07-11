import os
import tempfile

os.environ['FLASK_ENV'] = 'development'
os.environ['SECRET_KEY'] = 'test-secret-key-for-testing-only'
os.environ['PAYSTACK_SECRET_KEY'] = 'sk_test_placeholder'
os.environ['PAYSTACK_PUBLIC_KEY'] = 'pk_test_placeholder'
os.environ['RESEND_API_KEY'] = 're_placeholder'
os.environ['SKIP_DB_CREATE'] = '1'

_db_fd, _db_path = tempfile.mkstemp(suffix='.db')
os.environ['DATABASE_URL'] = f'sqlite:///{_db_path}'

import pytest
from app import app as _app
from models import db as _db

_app.config['TESTING'] = True
_app.config['WTF_CSRF_ENABLED'] = False


@pytest.fixture(scope='session', autouse=True)
def setup_db():
    with _app.app_context():
        _db.create_all()
        yield
        _db.drop_all()
    os.close(_db_fd)
    os.unlink(_db_path)


@pytest.fixture
def client():
    return _app.test_client()


@pytest.fixture
def db():
    with _app.app_context():
        for table in reversed(_db.metadata.sorted_tables):
            _db.session.execute(table.delete())
        _db.session.commit()
        yield _db
        _db.session.rollback()

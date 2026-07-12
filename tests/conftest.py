import os
import pytest

os.environ.setdefault("FLASK_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing")
os.environ.setdefault("SKIP_DB_CREATE", "1")

from app import create_app
from models import db as _db


@pytest.fixture(scope="session")
def app():
    app = create_app()
    with app.app_context():
        _db.create_all()
        yield app
        _db.drop_all()

@pytest.fixture(scope="function")
def db(app):
    with app.app_context():
        _db.create_all()
        yield _db
        _db.session.rollback()
        _db.drop_all()

@pytest.fixture(scope="function")
def client(app):
    return app.test_client()

@pytest.fixture(scope="function")
def runner(app):
    return app.test_cli_runner()

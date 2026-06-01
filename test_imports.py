import pytest


def test_import_fastapi():
    import fastapi
    assert fastapi.__version__


def test_import_sqlite3():
    import sqlite3
    assert sqlite3.sqlite_version


def test_import_pydantic_settings():
    from pydantic_settings import BaseSettings
    assert BaseSettings


def test_import_fastapi_testclient():
    try:
        from fastapi.testclient import TestClient
        assert TestClient
    except RuntimeError:
        pytest.skip("httpx not installed (needed for TestClient)")

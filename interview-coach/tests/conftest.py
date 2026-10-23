import pytest


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch, tmp_path):
    """Keep tests independent of a developer's local .env file."""
    monkeypatch.chdir(tmp_path)

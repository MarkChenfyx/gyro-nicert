from backend.data_manager.rqdata_client import load_credentials


def test_rqdata_credentials_load_from_environment(monkeypatch):
    monkeypatch.setenv("GYRO_RQDATA_USERNAME", "demo-user")
    monkeypatch.setenv("GYRO_RQDATA_PASSWORD", "demo-password")

    credentials = load_credentials()

    assert credentials.username == "demo-user"
    assert credentials.password == "demo-password"
    assert credentials.source == "environment"

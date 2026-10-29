from conftest import mutate
from mas_backend import scaffold


def test_apply_os_error_identifies_path_and_cause(client, registered, monkeypatch):
    revision = registered["revision"]
    preview = mutate(client, "POST", "/projects/mas-self/preview", revision=revision).json()
    attempted = []
    def too_long(path, data, create=False):
        attempted.append(str(path))
        raise OSError(206, "Filename or extension is too long", str(path))
    monkeypatch.setattr(scaffold, "atomic_write", too_long)
    response = mutate(client, "POST", "/projects/mas-self/apply", dict(preview_id=preview["preview_id"]), revision)
    assert response.status_code == 503
    detail = response.json()["details"][0]
    assert detail["location"] == attempted[0]
    assert "206" in detail["code"]
    assert "too long" in detail["message"]

from __future__ import annotations

import base64
import json
import sys
import types
from pathlib import Path

import pytest

from academia_os.connectors.google import GoogleCredentialStore
from scripts.build_macos_sidecar import google_oauth_client_config, stage_google_oauth_client


CLIENT = {"installed": {"client_id": "test-client.apps.googleusercontent.com", "client_secret": "test-secret"}}


def test_release_client_json_is_read_from_base64_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACADEMIA_GOOGLE_OAUTH_CLIENT_JSON_B64", base64.b64encode(json.dumps(CLIENT).encode()).decode())
    monkeypatch.delenv("ACADEMIA_GOOGLE_CLIENT_JSON", raising=False)
    monkeypatch.delenv("ACADEMIA_REQUIRE_GOOGLE_CLIENT", raising=False)
    assert google_oauth_client_config() == CLIENT


def test_local_client_json_path_is_supported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client_path = tmp_path / "client.json"
    client_path.write_text(json.dumps(CLIENT), encoding="utf-8")
    monkeypatch.delenv("ACADEMIA_GOOGLE_OAUTH_CLIENT_JSON_B64", raising=False)
    monkeypatch.setenv("ACADEMIA_GOOGLE_CLIENT_JSON", str(client_path))
    assert google_oauth_client_config() == CLIENT


def test_release_build_requires_client_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ACADEMIA_GOOGLE_OAUTH_CLIENT_JSON_B64", raising=False)
    monkeypatch.delenv("ACADEMIA_GOOGLE_CLIENT_JSON", raising=False)
    monkeypatch.setenv("ACADEMIA_REQUIRE_GOOGLE_CLIENT", "1")
    keyring = types.SimpleNamespace(get_password=lambda *_args: None)
    monkeypatch.setitem(sys.modules, "keyring", keyring)
    with pytest.raises(ValueError, match="required"):
        google_oauth_client_config()


def test_local_packaging_can_read_the_client_from_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ACADEMIA_GOOGLE_OAUTH_CLIENT_JSON_B64", raising=False)
    monkeypatch.delenv("ACADEMIA_GOOGLE_CLIENT_JSON", raising=False)
    monkeypatch.delenv("ACADEMIA_REQUIRE_GOOGLE_CLIENT", raising=False)
    keyring = types.SimpleNamespace(get_password=lambda _service, _account: json.dumps(CLIENT["installed"]))
    monkeypatch.setitem(sys.modules, "keyring", keyring)
    assert google_oauth_client_config() == CLIENT


def test_bundled_client_does_not_read_or_write_the_client_keychain_item(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    resource = tmp_path / "google_client" / "client.json"
    resource.parent.mkdir()
    resource.write_text(json.dumps(CLIENT), encoding="utf-8")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    writes: list[tuple[str, str, str]] = []
    keyring = types.SimpleNamespace(
        get_password=lambda *_args: (_ for _ in ()).throw(AssertionError("client keychain must not be read")),
        set_password=lambda service, account, value: writes.append((service, account, value)),
    )
    monkeypatch.setitem(sys.modules, "keyring", keyring)

    client = GoogleCredentialStore().load_client()
    assert client == CLIENT["installed"]
    assert writes == []


def test_bundled_client_overrides_a_legacy_client_keychain_item(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    resource = tmp_path / "google_client" / "client.json"
    resource.parent.mkdir()
    resource.write_text(json.dumps(CLIENT), encoding="utf-8")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    keyring = types.SimpleNamespace(
        get_password=lambda *_args: (_ for _ in ()).throw(AssertionError("legacy client must not be read")),
        set_password=lambda *_args: (_ for _ in ()).throw(AssertionError("client must not be written")),
    )
    monkeypatch.setitem(sys.modules, "keyring", keyring)

    assert GoogleCredentialStore().load_client() == CLIENT["installed"]


def test_build_resource_is_staged_private_and_outside_the_repository(tmp_path: Path) -> None:
    resource = stage_google_oauth_client(tmp_path / "pyinstaller-work", CLIENT)
    assert resource.relative_to(tmp_path)
    assert json.loads(resource.read_text(encoding="utf-8")) == CLIENT
    assert resource.stat().st_mode & 0o777 == 0o600

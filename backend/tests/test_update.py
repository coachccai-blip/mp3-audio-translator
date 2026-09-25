"""Bouton « Mettre à jour » : version installée et lancement de la mise à jour."""


def test_version_without_windows_installer(app_env):
    client = app_env["client"]
    v = client.get("/api/version").json()
    assert v["can_update"] is False
    r = client.post("/api/update", json={"confirm": True})
    assert r.status_code == 404


def test_update_requires_json_body(app_env):
    """Un formulaire d'un autre site (sans pré-vérification CORS) ne peut pas lancer la mise à jour."""
    client = app_env["client"]
    r = client.post("/api/update", content="confirm=true", headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 422


def test_connect_and_disconnect_claude(app_env, monkeypatch, tmp_path):
    """Bouton « Connecter Claude » : la clé bascule la traduction sur Claude ; « Déconnecter » l'efface."""
    from app import config
    from app.api import settings as settings_api

    env = tmp_path / ".env"
    monkeypatch.setattr(settings_api, "write_env_values", lambda u: config.write_env_values(u, env))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client = app_env["client"]
    s = client.put("/api/settings", json={"keys": {"ANTHROPIC_API_KEY": " sk-ant-test "}}).json()
    assert s["keys"]["ANTHROPIC_API_KEY"] and s["translator_engine"] == "claude"
    assert "ANTHROPIC_API_KEY=sk-ant-test" in env.read_text()
    s = client.put("/api/settings", json={"remove_keys": ["ANTHROPIC_API_KEY"]}).json()
    assert not s["keys"]["ANTHROPIC_API_KEY"] and s["translator_engine"] == "local"
    assert "sk-ant-test" not in env.read_text()

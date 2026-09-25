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

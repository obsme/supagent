"""0.10.7: the service user the CLI and MCP tools act as is read where the error message says to set it:
SUPAGENT_MCP_USER in superset_config.py or the environment (it was named, never read)."""
from __future__ import annotations

from types import SimpleNamespace

from supagent import security, settings


def _app(**config):
    return SimpleNamespace(config=config)


def test_config_names_the_service_user(monkeypatch):
    monkeypatch.setattr(settings, "get", lambda key, *a, **k: "")
    monkeypatch.delenv("SUPAGENT_MCP_USER", raising=False)
    monkeypatch.delenv("TOOLS_USER", raising=False)
    assert security.service_username(_app(SUPAGENT_MCP_USER="svc")) == "svc"
    assert security.service_username(_app(MCP_DEV_USERNAME="dev")) == "dev"
    assert security.service_username(_app()) == ""


def test_environment_then_setting_order(monkeypatch):
    monkeypatch.setattr(settings, "get", lambda key, *a, **k: "")
    monkeypatch.setenv("SUPAGENT_MCP_USER", "env-svc")
    assert security.service_username(_app(SUPAGENT_MCP_USER="cfg", MCP_DEV_USERNAME="dev")) == "env-svc"
    monkeypatch.setattr(settings, "get", lambda key, *a, **k: "from-setting" if key == "mcp.user" else "")
    assert security.service_username(_app(SUPAGENT_MCP_USER="cfg")) == "from-setting"

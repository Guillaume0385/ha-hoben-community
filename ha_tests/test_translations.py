"""Verify custom-component runtime translations through Home Assistant itself."""

import json
from pathlib import Path

import pytest
from homeassistant.helpers.translation import async_get_translations

from custom_components.hoben.const import CONF_USER_GUID, DOMAIN

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / DOMAIN


@pytest.mark.parametrize("language", ["en", "fr"])
async def test_runtime_translations_load_without_core_strings(hass, language):
    translations = await async_get_translations(hass, language, "config", {DOMAIN})
    prefix = "component.hoben.config."
    assert translations[prefix + "step.user.title"]
    assert translations[prefix + "step.user.description"]
    assert translations[prefix + f"step.user.data.{CONF_USER_GUID}"]
    description = translations[prefix + f"step.user.data_description.{CONF_USER_GUID}"]
    assert "MyHOBEN" in description
    for error in (
        "invalid_identifier",
        "authorization_required",
        "cannot_connect",
        "unsupported_stove",
        "protocol_error",
        "unknown",
    ):
        assert translations[prefix + "error." + error]
    assert translations[prefix + "abort.already_configured"]
    assert not (INTEGRATION / "strings.json").exists()


def test_manifest_and_translation_schema():
    manifest = json.loads((INTEGRATION / "manifest.json").read_text())
    assert manifest["config_flow"] is True
    assert manifest["requirements"] == []
    assert manifest["iot_class"] == "cloud_polling"
    en = json.loads((INTEGRATION / "translations/en.json").read_text())
    fr = json.loads((INTEGRATION / "translations/fr.json").read_text())

    def paths(value, prefix=""):
        if isinstance(value, dict):
            return {
                path
                for key, item in value.items()
                for path in paths(item, prefix + "." + key)
            }
        assert isinstance(value, str) and value
        assert "[%key:" not in value
        return {prefix}

    assert paths(en) == paths(fr)

"""Verify custom-component runtime translations through Home Assistant itself."""

import json
from pathlib import Path

import pytest
from homeassistant.helpers.translation import async_get_translations

from custom_components.hoben.binary_sensor import BINARY_SENSORS
from custom_components.hoben.const import CONF_USER_GUID, DOMAIN
from custom_components.hoben.sensor import SENSORS

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / DOMAIN


@pytest.mark.parametrize("language", ["en", "fr"])
async def test_runtime_translations_load_without_core_strings(hass, language):
    translations = await async_get_translations(hass, language, "config", {DOMAIN})
    prefix = "component.hoben.config."
    assert translations[prefix + "step.user.title"]
    assert translations[prefix + "step.user.description"]
    assert translations[prefix + "step.reauth_confirm.title"]
    assert translations[prefix + "step.reauth_confirm.description"]
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
    for reason in ("already_configured", "reauth_successful", "unique_id_mismatch"):
        assert translations[prefix + "abort." + reason]
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


@pytest.mark.parametrize("language", ["en", "fr"])
async def test_entity_names_and_enum_states_load(hass, language):
    translations = await async_get_translations(hass, language, "entity", {DOMAIN})
    for platform, descriptions in (
        ("sensor", SENSORS),
        ("binary_sensor", BINARY_SENSORS),
    ):
        for description in descriptions:
            prefix = f"component.hoben.entity.{platform}.{description.translation_key}."
            assert translations[prefix + "name"]
            for option in getattr(description, "options", None) or ():
                assert translations[prefix + "state." + option]
    prefix = "component.hoben.entity.sensor.operation_mode."
    assert translations[prefix + "name"] == (
        "Operation mode" if language == "en" else "Mode de fonctionnement"
    )
    assert translations[prefix + "state.manual"] == (
        "Manual" if language == "en" else "Manuel"
    )

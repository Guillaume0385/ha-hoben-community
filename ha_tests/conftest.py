"""Separate real-HA test environment, with synthetic identities and no network."""

from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hoben.client import HobenClient, RawStoveSnapshot
from custom_components.hoben.const import CONF_DEVICE_GUID, CONF_USER_GUID, DOMAIN
from custom_components.hoben.helpers import user_guid_fingerprint
from custom_components.hoben.profiles import StoveProfile

# Independently invented test identities; never taken from a stove or capture.
USER_GUID = "12345678-1234-5678-1234-567812345678"
NORMALIZED_USER_GUID = USER_GUID.replace("-", "")
DEVICE_GUID = "D" * 32
ROTATED_DEVICE_GUID = "R" * 32
PRIVATE_TEXT = f"{USER_GUID} {NORMALIZED_USER_GUID} {DEVICE_GUID} PRIVATE_PAYLOAD"


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    """Load this checkout through HA's custom-integration loader."""


@pytest.fixture(autouse=True)
def no_hoben_network(monkeypatch):
    """A missed client patch must fail before creating any Hoben transport.

    The harness independently blocks external sockets/DNS for every HA test.
    No socket-enabling fixture is used in this suite.
    """
    monkeypatch.setattr(
        "custom_components.hoben.client.AsyncTlsTransport",
        Mock(side_effect=AssertionError("Live Hoben transport is forbidden")),
    )


@pytest.fixture(autouse=True)
async def unload_entries(hass):
    """Exercise normal HA unload and leave no entry-owned polling timer behind."""
    yield
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.fixture
def snapshot():
    """Use the real immutable model, with synthetic UInt16 values only."""
    return RawStoveSnapshot(
        profile=StoveProfile.V4,
        registers=tuple(range(20)),
        product_type=5,
        product_revision=0,
        software_major=8,
        software_minor=2,
        application_version=512,
    )


@pytest.fixture
def client(snapshot):
    """Only replace the network API; all HA orchestration stays real."""
    client = Mock(spec=HobenClient)
    client.async_refresh = AsyncMock(return_value=snapshot)
    client.async_close = AsyncMock()
    client.device_guid_for_persistence = DEVICE_GUID
    return client


@pytest.fixture
def client_factory(monkeypatch, client):
    """Patch both construction sites with one inspectable factory."""
    factory = Mock(return_value=client)
    monkeypatch.setattr("custom_components.hoben.HobenClient", factory)
    monkeypatch.setattr("custom_components.hoben.config_flow.HobenClient", factory)
    return factory


@pytest.fixture
def entry(hass):
    """A correctly persisted entry plus unrelated data/options to protect."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Hoben",
        unique_id=user_guid_fingerprint(NORMALIZED_USER_GUID),
        data={
            CONF_USER_GUID: NORMALIZED_USER_GUID,
            CONF_DEVICE_GUID: DEVICE_GUID,
            "future_setting": "retained",
        },
        options={"future_option": "retained"},
    )
    entry.add_to_hass(hass)
    return entry


def assert_private_values_absent(text):
    """Keep identifiers, arbitrary payloads and register dumps off public surfaces."""
    for value in (
        USER_GUID,
        NORMALIZED_USER_GUID,
        DEVICE_GUID,
        ROTATED_DEVICE_GUID,
        "PRIVATE_PAYLOAD",
        repr(tuple(range(20))),
    ):
        assert value not in text

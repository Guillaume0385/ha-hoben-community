"""One diagnostic entity; session signals never refresh retained stove values."""

import asyncio
from datetime import timedelta

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .client import HobenClient
from .const import DOMAIN

STATES = ["connected", "recovering", "reconnecting", "disconnected"]


class HobenSessionSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATES
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "session"

    def __init__(self, entry):
        self.coordinator = entry.runtime_data.coordinator
        self.client = entry.runtime_data.client
        self._attr_unique_id = f"{entry.unique_id}_session"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.unique_id)})
        self._pending = None
        self._active = False

    @property
    def native_value(self):
        if self.coordinator._shutdown_requested or type(self.client) is not HobenClient:
            return "disconnected"
        return self.client.session_state

    @property
    def extra_state_attributes(self):
        monitor = (
            self.client.session_monitor if type(self.client) is HobenClient else None
        )
        successful = self.coordinator.last_successful_read_at
        return {
            "last_error_category": monitor.last_error_category if monitor else None,
            "last_error_phase": monitor.last_error_phase if monitor else None,
            "last_error_at": monitor.last_error_at.isoformat()
            if monitor and monitor.last_error_at
            else None,
            "last_successful_read_at": successful.isoformat() if successful else None,
            "last_successful_read_age": max(
                0, int((dt_util.utcnow() - successful).total_seconds())
            )
            if successful
            else None,
            "reconnect_count": monitor.reconnect_count if monitor else None,
            "recovery_count": monitor.recovery_count if monitor else None,
        }

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._active = True
        if type(self.client) is HobenClient:
            self.async_on_remove(self.client.session_monitor.subscribe(self._schedule))
        # Only local age metadata; no client refresh or extra network poll.
        self.async_on_remove(
            async_track_time_interval(self.hass, self._schedule, timedelta(seconds=60))
        )

    @callback
    def _schedule(self, _now=None):
        if self._active and self._pending is None:
            self._pending = asyncio.get_running_loop().call_soon(self._publish)

    def _publish(self):
        self._pending = None
        if self._active:
            self.async_write_ha_state()

    async def async_will_remove_from_hass(self):
        self._active = False
        if self._pending is not None:
            self._pending.cancel()
            self._pending = None
        await super().async_will_remove_from_hass()

"""Shared in-memory coordinator entities with non-secret, stable identities."""

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HobenConfigEntry
from .const import DOMAIN
from .coordinator import HobenDataUpdateCoordinator
from .v4_state import V4StoveState


class HobenEntity(CoordinatorEntity[HobenDataUpdateCoordinator]):
    """Attach to the existing stove; availability follows the shared coordinator."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HobenDataUpdateCoordinator,
        entry: HobenConfigEntry,
        key: str,
    ) -> None:
        """Use the config flow's full fingerprint, never either private GUID."""
        super().__init__(coordinator)
        assert entry.unique_id is not None
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.unique_id)})

    @property
    def stove_state(self) -> V4StoveState:
        """Read only memory; entity properties cannot reach the protocol client."""
        return self.coordinator.data.state

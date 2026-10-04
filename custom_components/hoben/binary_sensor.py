"""Read-only V4 derogation flags and controller OnOff request read-back."""

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HobenConfigEntry
from .entity import HobenEntity
from .v4_state import V4StoveState


@dataclass(frozen=True, kw_only=True)
class HobenBinarySensorDescription(BinarySensorEntityDescription):
    """Read a typed boolean, including unknown OnOff, from coordinator memory."""

    value_fn: Callable[[V4StoveState], bool | None]


BINARY_SENSORS: tuple[HobenBinarySensorDescription, ...] = (
    HobenBinarySensorDescription(
        key="derogation_active",
        translation_key="derogation_active",
        value_fn=lambda state: state.derogation_active,
    ),
    HobenBinarySensorDescription(
        key="derogation_scheduled",
        translation_key="derogation_scheduled",
        value_fn=lambda state: state.derogation_scheduled,
    ),
    # This is the controller's request/read-back, not proof of combustion. Do
    # not assign RUNNING or HEAT; operation_state carries the actual V4 state.
    HobenBinarySensorDescription(
        key="controller_on_off",
        translation_key="controller_on_off",
        value_fn=lambda state: state.on_off,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HobenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Subscribe to the shared coordinator without a second refresh."""
    async_add_entities(
        HobenBinarySensor(entry, description) for description in BINARY_SENSORS
    )


class HobenBinarySensor(HobenEntity, BinarySensorEntity):
    """Only booleans in memory; no control methods or client access."""

    entity_description: HobenBinarySensorDescription

    def __init__(
        self, entry: HobenConfigEntry, description: HobenBinarySensorDescription
    ) -> None:
        """Attach a translated description to the existing stove identity."""
        super().__init__(entry.runtime_data.coordinator, entry, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Unknown OnOff yields None, never a valid off or on state."""
        return self.entity_description.value_fn(self.stove_state)

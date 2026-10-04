"""Read-only V4 values; parsing and all I/O belong to decoder/coordinator."""

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HobenConfigEntry
from .entity import HobenEntity
from .v4_state import (
    V4OperationMode,
    V4OperationState,
    V4StoveState,
    V4VentilationMode,
)


@dataclass(frozen=True, kw_only=True)
class HobenSensorDescription(SensorEntityDescription):
    """A value accessor on typed memory; optional derogation visibility policy."""

    value_fn: Callable[[V4StoveState], float | int | str | None]
    derogation_only: bool = False


SENSORS: tuple[HobenSensorDescription, ...] = (
    HobenSensorDescription(
        key="ambient_temperature",
        translation_key="ambient_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda state: state.ambient_temperature,
    ),
    HobenSensorDescription(
        key="target_temperature",
        translation_key="target_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda state: state.target_temperature,
    ),
    HobenSensorDescription(
        key="power_level",
        translation_key="power_level",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda state: state.power_level,
    ),
    HobenSensorDescription(
        key="operation_state",
        translation_key="operation_state",
        device_class=SensorDeviceClass.ENUM,
        options=[state.value for state in V4OperationState],
        value_fn=lambda state: state.operation_state,
    ),
    HobenSensorDescription(
        key="operation_mode",
        translation_key="operation_mode",
        device_class=SensorDeviceClass.ENUM,
        options=[mode.value for mode in V4OperationMode],
        value_fn=lambda state: state.operation_mode,
    ),
    HobenSensorDescription(
        key="ventilation_mode",
        translation_key="ventilation_mode",
        device_class=SensorDeviceClass.ENUM,
        options=[mode.value for mode in V4VentilationMode],
        value_fn=lambda state: state.ventilation_mode,
    ),
    HobenSensorDescription(
        key="smoke_temperature",
        translation_key="smoke_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.smoke_temperature,
    ),
    HobenSensorDescription(
        key="combustion_air_temperature",
        translation_key="combustion_air_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.combustion_air_temperature,
    ),
    HobenSensorDescription(
        key="wired_ambient_temperature",
        translation_key="wired_ambient_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda state: state.wired_ambient_temperature,
    ),
    HobenSensorDescription(
        key="rf_ambient_temperature",
        translation_key="rf_ambient_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda state: state.rf_ambient_temperature,
    ),
    HobenSensorDescription(
        key="derogation_temperature",
        translation_key="derogation_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        derogation_only=True,
        value_fn=lambda state: state.derogation_temperature,
    ),
    HobenSensorDescription(
        key="derogation_start_delay",
        translation_key="derogation_start_delay",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        derogation_only=True,
        value_fn=lambda state: state.derogation_start_delay,
    ),
    HobenSensorDescription(
        key="derogation_duration",
        translation_key="derogation_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        derogation_only=True,
        value_fn=lambda state: state.derogation_duration,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HobenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Subscribe all sensors to the already refreshed shared coordinator."""
    async_add_entities(HobenSensor(entry, description) for description in SENSORS)


class HobenSensor(HobenEntity, SensorEntity):
    """An in-memory V4 read-back; None yields unknown without device unavailability."""

    entity_description: HobenSensorDescription

    def __init__(
        self, entry: HobenConfigEntry, description: HobenSensorDescription
    ) -> None:
        """Describe the sensor without any network request or register parsing."""
        super().__init__(entry.runtime_data.coordinator, entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | int | str | None:
        """Hide inactive derogation read-back; never substitute UI defaults."""
        state = self.stove_state
        if self.entity_description.derogation_only and not (
            state.derogation_active or state.derogation_scheduled
        ):
            return None
        return self.entity_description.value_fn(state)

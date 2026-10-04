"""Home Assistant configuration keys and conservative cloud polling policy."""

from datetime import timedelta

DOMAIN = "hoben"
# Both values are sensitive and belong only in ConfigEntry.data, never options.
CONF_USER_GUID = "user_guid"
CONF_DEVICE_GUID = "device_guid"
UPDATE_INTERVAL = timedelta(seconds=60)

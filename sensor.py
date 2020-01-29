"""Support for CCS811 temperature and humidity sensor."""
from datetime import timedelta
from functools import partial
import asyncio
import logging
import sys
import os
import time
import time
import busio

import adafruit_ccs811 # pylint: disable=import-error

import voluptuous as vol

from homeassistant.core import DOMAIN as HA_DOMAIN, callback
from homeassistant.components.sensor import PLATFORM_SCHEMA
import homeassistant.helpers.config_validation as cv
from homeassistant.const import CONF_NAME, CONF_MONITORED_CONDITIONS, EVENT_HOMEASSISTANT_START, STATE_UNKNOWN
from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle
from homeassistant.helpers.event import (
    async_track_state_change,
)

_LOGGER = logging.getLogger(__name__)


CONF_I2C_ADDRESS = "i2c_address"
CONF_I2C_SCL = "i2c_scl"
CONF_I2C_SDA = "i2c_sda"

DEFAULT_NAME = "CCS811 Sensor"
DEFAULT_I2C_ADDRESS = 0x5A
DEFAULT_I2C_SCL = 3
DEFAULT_I2C_SDA = 2

MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=3)

CONF_HUMIDITY_SENSOR = 'humidity_sensor'
CONF_TEMPERATURE_SENSOR = 'temperature_sensor'

SENSOR_ECO2 = "eco2"
SENSOR_TVOC = "tvoc"
SENSOR_TYPES = {
    SENSOR_ECO2: ["eCO2", "ppm"],
    SENSOR_TVOC: ["tVOC", "ppb"],
}
DEFAULT_MONITORED = [SENSOR_ECO2, SENSOR_TVOC]

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_HUMIDITY_SENSOR, default=None): vol.Coerce(cv.entity_id),
        vol.Optional(CONF_TEMPERATURE_SENSOR, default=None): vol.Coerce(cv.entity_id),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_I2C_ADDRESS, default=DEFAULT_I2C_ADDRESS): vol.Coerce(int),
        vol.Optional(CONF_MONITORED_CONDITIONS, default=DEFAULT_MONITORED): vol.All(
            cv.ensure_list, [vol.In(SENSOR_TYPES)]
        ),
        vol.Optional(CONF_I2C_SCL, default=DEFAULT_I2C_SCL): vol.Coerce(int),
        vol.Optional(CONF_I2C_SDA, default=DEFAULT_I2C_SDA): vol.Coerce(int)
    }
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    name = config.get(CONF_NAME)
    i2c_address = config.get(CONF_I2C_ADDRESS)
    i2c_bus = busio.I2C(config.get(CONF_I2C_SCL), config.get(CONF_I2C_SDA))
    temperature_sensor_entity_id = config.get(CONF_TEMPERATURE_SENSOR)
    humidity_sensor_entity_id = config.get(CONF_HUMIDITY_SENSOR)

    sensor = await hass.async_add_job(
        partial(
            adafruit_ccs811.CCS811,
            i2c_bus=i2c_bus,
            address=i2c_address,
        )
    )

    sensor_handler = await hass.async_add_job(CCS811Handler, sensor)

    dev = []
    try:
        for variable in config[CONF_MONITORED_CONDITIONS]:
            dev.append(
                CCS811Sensor(sensor_handler, variable, name, temperature_sensor_entity_id, humidity_sensor_entity_id)
            )
    except KeyError:
        pass

    async_add_entities(dev, True)


class CCS811Handler:
    """CCS811 sensor working in i2C bus."""

    def __init__(self, sensor):
        """Initialize the sensor handler."""
        self.sensor = sensor
        self.temperature = None
        self.humitidy = None
        self.update()

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    def update(self):
        """Update temperature and humidity compensation and read sensor data."""
        if self.temperature != None and self.humidity != None:
            self.sensor.set_environmental_data(self.humidity, self.temperature)
#       Trim away error values.
        new_eco2 = self.sensor.eco2
        if new_eco2 < 65535:
            self.eco2 = new_eco2
        self.tvoc = self.sensor.tvoc

    def set_temperature(self, temperature):
        """Set new target temperature."""
        self.temperature = temperature

    def set_humidity(self, humidity):
        """Set new target humidity."""
        self.humidity = humidity

class CCS811Sensor(Entity):
    """Implementation of the CCS811 sensor."""

    def __init__(self, ccs811_client, sensor_type, name, temperature_sensor_entity_id, humidity_sensor_entity_id):
        """Initialize the sensor."""
        self.client_name = name
        self.temperature_sensor_entity_id = temperature_sensor_entity_id
        self.humidity_sensor_entity_id = humidity_sensor_entity_id
        self._name = SENSOR_TYPES[sensor_type][0]
        self.ccs811_client = ccs811_client
        self.type = sensor_type
        self._state = None
        self._unit_of_measurement = SENSOR_TYPES[sensor_type][1]
        
    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        # Add listener
        async_track_state_change(
            self.hass, self.temperature_sensor_entity_id, self._async_temperature_sensor_changed
        )
        async_track_state_change(
            self.hass, self.humidity_sensor_entity_id, self._async_humidity_sensor_changed
        )

        @callback
        def _async_startup(event):
            """Init on startup."""
            sensor_state_temperature = self.hass.states.get(self.temperature_sensor_entity_id)
            if sensor_state_temperature and sensor_state_temperature.state != STATE_UNKNOWN:
                self._async_update_temperature(sensor_state_temperature)

            sensor_state_humidity = self.hass.states.get(self.humidity_sensor_entity_id)
            if sensor_state_humidity and sensor_state_humidity.state != STATE_UNKNOWN:
                self._async_update_humidity(sensor_state_humidity)

        self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, _async_startup)


    async def _async_temperature_sensor_changed(self, entity_id, old_state, new_state):
        """Handle temperature changes."""
        if new_state is None:
            return

        self._async_update_temperature(new_state)

    @callback
    def _async_update_temperature(self, state):
        """Update thermostat with latest state from sensor."""
        try:
            self.ccs811_client.set_temperature(float(state.state))
        except ValueError as ex:
            _LOGGER.error("Unable to update from sensor: %s", ex)

    async def _async_humidity_sensor_changed(self, entity_id, old_state, new_state):
        """Handle humidity changes."""
        if new_state is None:
            return

        self._async_update_humidity(new_state)

    @callback
    def _async_update_humidity(self, state):
        """Update thermostat with latest state from sensor."""
        try:
            self.ccs811_client.set_humidity(float(state.state))
        except ValueError as ex:
            _LOGGER.error("Unable to update from sensor: %s", ex)

    @property
    def name(self):
        """Return the name of the sensor."""
        return f"{self.client_name} {self._name}"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement of the sensor."""
        return self._unit_of_measurement

    async def async_update(self):
        """Get the latest data from the CCS811 and update the states."""
        await self.hass.async_add_job(self.ccs811_client.update)
        if self.type == SENSOR_ECO2:
            eco2 = self.ccs811_client.eco2
            self._state = eco2
        elif self.type == SENSOR_TVOC:
            self._state = self.ccs811_client.tvoc


"""Support for CCS811 temperature and humidity sensor."""
from datetime import timedelta
from functools import partial
import logging
import sys
import os
import time
import time
import busio

import adafruit_ccs811 # pylint: disable=import-error

import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
import homeassistant.helpers.config_validation as cv
from homeassistant.const import CONF_NAME, CONF_MONITORED_CONDITIONS
from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle

_LOGGER = logging.getLogger(__name__)


CONF_I2C_ADDRESS = "i2c_address"
CONF_I2C_SCL = "i2c_scl"
CONF_I2C_SDA = "i2c_sda"

DEFAULT_NAME = "CCS811 Sensor"
DEFAULT_I2C_ADDRESS = 0x5A
DEFAULT_I2C_SCL = 3
DEFAULT_I2C_SDA = 2

MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=3)

SENSOR_ECO2 = "eco2"
SENSOR_TVOC = "tvoc"
SENSOR_TYPES = {
    SENSOR_ECO2: ["eCO2", "ppm"],
    SENSOR_TVOC: ["tVOC", "ppb"],
}
DEFAULT_MONITORED = [SENSOR_ECO2, SENSOR_TVOC]

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
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
                CCS811Sensor(sensor_handler, variable, name)
            )
    except KeyError:
        pass

    async_add_entities(dev, True)


class CCS811Handler:
    """CCS811 sensor working in i2C bus."""

    def __init__(self, sensor):
        """Initialize the sensor handler."""
        self.sensor = sensor
        self.update()

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    def update(self):
        """Read sensor data."""

# TODO:
#        temperature = get_temperature()
#        humidity = get_humidity()
        # self.sensor.set_environmental_data(humidity, temperature):
        self.eco2 = self.sensor.eco2
        self.tvoc = self.sensor.tvoc

class CCS811Sensor(Entity):
    """Implementation of the CCS811 sensor."""

    def __init__(self, ccs811_client, sensor_type, name):
        """Initialize the sensor."""
        self.client_name = name
        self._name = SENSOR_TYPES[sensor_type][0]
        self.ccs811_client = ccs811_client
        self.type = sensor_type
        self._state = None
        self._unit_of_measurement = SENSOR_TYPES[sensor_type][1]

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



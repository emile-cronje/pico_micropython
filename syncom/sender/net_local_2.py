# net_local.py Local network parameters for Pyboard MQTT link
# Edit for your network. See BRIDGE.md for this structure.

# Author: Peter Hinch.
# Copyright Peter Hinch 2017-2021 Released under the MIT license.

# See BRIDGE.md para 2.3.1

d = {
        # Customisations: mandatory
        'ssid' : 'Cudy24G',
        'password' : 'ZAnne19991214',
        'broker' : '192.168.10.125',
        'use_default_net' : False,
        'debug' : True,
        'verbose' : True,
    }
# or e.g. 'broker' : 'test.mosquitto.org'

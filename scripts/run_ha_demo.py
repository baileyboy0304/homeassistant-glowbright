"""Disposable real HA UI with synthetic Bright data; never use in production.

Run on Linux: python scripts/run_ha_demo.py
HA login: demo / glowbright-local-demo. Bright test login: demo / demo.
Only this process replaces the API; the shipped integration has no demo mode.
"""

import asyncio
from datetime import UTC, datetime, timedelta
import json
import logging
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CONFIG = ROOT / ".ha-test"
CONFIG.mkdir(exist_ok=True)
(CONFIG / "custom_components").mkdir(exist_ok=True)
link = CONFIG / "custom_components" / "glowbright"
if not link.exists():
    link.symlink_to(ROOT / "custom_components" / "glowbright", target_is_directory=True)
storage = CONFIG / ".storage"
storage.mkdir(exist_ok=True)
(storage / "onboarding").write_text(json.dumps({"version":4,"minor_version":1,"key":"onboarding","data":{"done":["user","core_config","integration","analytics"]}}))

from homeassistant.bootstrap import async_from_config_dict
from homeassistant.core import HomeAssistant
from homeassistant import loader
from custom_components.glowbright.api import GlowmarktClient, AuthError
from custom_components.glowbright.models import Resource

NOW = datetime.now(UTC).replace(hour=0,minute=0,second=0,microsecond=0)
FIRST = NOW - timedelta(days=14)
LAST = NOW - timedelta(days=1,minutes=30)

async def authenticate(self, rejected_token=None):
    if self._username != "demo" or self._password != "demo":
        raise AuthError("Synthetic test login: demo / demo")
    self.account_id="synthetic-bright-account"
    return self.account_id

async def discover(self):
    await self.authenticate()
    return [Resource("ve-full","DCC Sourced full","electricity","Electricity consumption","electricity.consumption","kWh",first_time=FIRST,last_time=LAST), Resource("ve-full","DCC Sourced full","stale-gas","Old gas consumption","gas.consumption","kWh",first_time=FIRST,last_time=FIRST), Resource("ve-gas","DCC Sourced","gas","Gas consumption","gas.consumption","m³",first_time=FIRST,last_time=LAST), Resource("ve-full","DCC Sourced full","electricity-cost","Electricity cost","electricity.consumption.cost","pence",first_time=FIRST,last_time=LAST), Resource("ve-gas","DCC Sourced","gas-cost","Gas cost","gas.consumption.cost","pence",first_time=FIRST,last_time=LAST)]

async def boundary(self, resource_id, first=False):
    return FIRST if first else LAST

async def readings(self, resource_id, start, end, period, last_time):
    result={}
    step=timedelta(minutes=30) if period=="PT30M" else timedelta(hours=1)
    t=start
    while t < end and t <= LAST:
        if t >= FIRST:
            h=t.hour+t.minute/60
            amount=.14+(.30 if 6<=h<9 else 0)+(.65 if 17<=h<21 else 0)+.045*((int(t.timestamp()/1800)*7)%5)
            if resource_id.startswith("gas"):
                amount *= .3
            if resource_id.endswith("cost"):
                amount *= 26 if resource_id.startswith("electricity") else 70
            if period=="PT1H":
                amount *=2
            result[t]=amount
        t+=step
    return result

async def tariff(self, resource_id):
    return {"unit_rate":26.0 if resource_id.startswith("electricity") else 6.7,"standing_charge":54.8 if resource_id.startswith("electricity") else 31.5}

async def catchup(self, resource_id):
    return {"data":{"valid":True}}

for name in ("authenticate","discover","boundary","readings","tariff","catchup"):
    setattr(GlowmarktClient,name,globals()[name])

async def main():
    hass=HomeAssistant(str(CONFIG))
    loader.async_setup(hass)
    config={"homeassistant":{"name":"GlowBright synthetic UI test","latitude":51.5,"longitude":-.1,"elevation":10,"unit_system":"metric","time_zone":"Europe/London","country":"GB","currency":"GBP"},"http":{"server_host":"127.0.0.1","server_port":8123},"frontend":{},"config":{},"recorder":{},"history":{},"energy":{}}
    if await async_from_config_dict(config,hass) is None:
        raise RuntimeError("Home Assistant setup failed")
    if not any(u.name=="GlowBright demo" for u in await hass.auth.async_get_users()):
        provider=next(p for p in hass.auth.auth_providers if p.type=="homeassistant")
        await provider.async_add_auth("demo","glowbright-local-demo")
        credentials=await provider.async_get_or_create_credentials({"username":"demo"})
        user=await hass.auth.async_create_user("GlowBright demo",group_ids=["system-admin"],local_only=True)
        await hass.auth.async_link_user(user,credentials)
    await hass.async_start()
    print("Synthetic Home Assistant UI ready at http://localhost:8123",flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await hass.async_stop()

if __name__=="__main__":
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())

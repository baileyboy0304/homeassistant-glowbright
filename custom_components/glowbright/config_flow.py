"""Bright account authentication and independent resource selection."""

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import SelectOptionDict, SelectSelector, SelectSelectorConfig

from .api import ApiError, AuthError, GlowmarktClient
from .const import DEFAULT_OPTIONS, DOMAIN, FUELS, NONE
from .models import cost_candidates


def selector(resources, optional=False):
    options = [SelectOptionDict(value=r.key, label=r.label) for r in resources]
    if optional:
        options.insert(0, SelectOptionDict(value=NONE, label="None"))
    return SelectSelector(SelectSelectorConfig(options=options, mode="dropdown"))


class SelectionSteps:
    """Shared validated selection sequence for initial and options flows."""

    async def async_step_electricity(self, user_input=None):
        return await self._select_fuel("electricity", user_input)

    async def async_step_gas(self, user_input=None):
        return await self._select_fuel("gas", user_input)

    async def _select_fuel(self, fuel, user_input):
        choices = [
            r
            for r in self.resources
            if r.classifier == f"{fuel}.consumption"
            and r.base_unit in (("kWh",) if fuel == "electricity" else ("kWh", "m³", "m3", "m^3"))
        ]
        errors = {}
        if user_input:
            key = user_input["resource"]
            if key not in {r.key for r in choices} and not (fuel == "gas" and key == NONE):
                errors["base"] = "invalid_resource"
            else:
                self.selections[fuel] = key
                return await (
                    self.async_step_gas() if fuel == "electricity" else self.async_step_costs()
                )
        if not choices and fuel == "electricity":
            return self.async_abort(reason="no_resources")
        default = self.selections.get(fuel)
        field = (
            vol.Required("resource", default=default)
            if default in {r.key for r in choices} | ({NONE} if fuel == "gas" else set())
            else vol.Required("resource")
        )
        return self.async_show_form(
            step_id=fuel,
            data_schema=vol.Schema({field: selector(choices, fuel == "gas")}),
            errors=errors,
        )

    async def async_step_costs(self, user_input=None):
        schema, allowed = {}, {}
        for fuel in FUELS:
            resource = next((r for r in self.resources if r.key == self.selections.get(fuel)), None)
            candidates = cost_candidates(self.resources, resource) if resource else []
            key = f"{fuel}_cost"
            allowed[key] = {r.key for r in candidates} | {NONE}
            default = self.selections.get(key)
            if default not in allowed[key]:
                default = candidates[0].key if len(candidates) == 1 else NONE
            schema[vol.Required(key, default=default)] = selector(candidates, True)
        if user_input:
            if any(user_input.get(key) not in values for key, values in allowed.items()):
                return self.async_show_form(
                    step_id="costs",
                    data_schema=vol.Schema(schema),
                    errors={"base": "invalid_resource"},
                )
            self.selections.update(user_input)
            return await self.async_step_confirm()
        return self.async_show_form(step_id="costs", data_schema=vol.Schema(schema))


class GlowBrightConfigFlow(SelectionSteps, config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return GlowBrightOptionsFlow()

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input:
            client = GlowmarktClient(
                async_get_clientsession(self.hass), user_input["username"], user_input["password"]
            )
            try:
                account_id = await client.authenticate()
                if self.source in ("reauth", "reconfigure"):
                    entry = (
                        self._get_reauth_entry()
                        if self.source == "reauth"
                        else self._get_reconfigure_entry()
                    )
                    if entry.unique_id != account_id:
                        return self.async_abort(reason="wrong_account")
                    if self.source == "reauth":
                        return self.async_update_reload_and_abort(
                            entry, data_updates={**user_input, "account_id": account_id}
                        )
                else:
                    await self.async_set_unique_id(account_id)
                    self._abort_if_unique_id_configured()
                self.resources = await client.discover()
            except AuthError:
                errors["base"] = "invalid_auth"
            except ApiError:
                errors["base"] = "cannot_connect"
            else:
                self.credentials = {**user_input, "account_id": account_id}
                self.selections = dict(DEFAULT_OPTIONS)
                if self.source == "reconfigure":
                    self.selections.update(self._get_reconfigure_entry().options)
                return await self.async_step_electricity()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required("username"): str, vol.Required("password"): str}),
            errors=errors,
        )

    async def async_step_confirm(self, user_input=None):
        if user_input is not None:
            if self.source == "reconfigure":
                entry = self._get_reconfigure_entry()
                self.hass.config_entries.async_update_entry(entry, options=self.selections)
                return self.async_update_reload_and_abort(entry, data_updates=self.credentials)
            return self.async_create_entry(
                title="GlowBright", data=self.credentials, options=self.selections
            )
        names = {
            fuel: next(
                (r.label for r in self.resources if r.key == self.selections.get(fuel)), "None"
            )
            for fuel in FUELS
        }
        return self.async_show_form(
            step_id="confirm", data_schema=vol.Schema({}), description_placeholders=names
        )

    async def async_step_reauth(self, entry_data):
        return await self.async_step_user()

    async def async_step_reconfigure(self, user_input=None):
        return await self.async_step_user(user_input)


class GlowBrightOptionsFlow(SelectionSteps, config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        errors = {}
        defaults = {**DEFAULT_OPTIONS, **self.config_entry.options}
        if user_input is not None:
            if user_input.get("gas_conversion") and not user_input.get("calorific_value"):
                errors["base"] = "calorific_required"
            else:
                self.selections = {**defaults, **user_input}
                client = GlowmarktClient(
                    async_get_clientsession(self.hass),
                    self.config_entry.data["username"],
                    self.config_entry.data["password"],
                    self.config_entry.unique_id,
                )
                try:
                    self.resources = await client.discover()
                    return await self.async_step_electricity()
                except AuthError:
                    errors["base"] = "invalid_auth"
                except ApiError:
                    errors["base"] = "cannot_connect"
        schema = {
            vol.Required("backfill_days", default=defaults["backfill_days"]): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=3650)
            ),
            vol.Required("refresh_days", default=defaults["refresh_days"]): vol.All(
                vol.Coerce(int), vol.Range(min=2, max=30)
            ),
            vol.Required("panel_enabled", default=defaults["panel_enabled"]): bool,
            vol.Required("gas_conversion", default=defaults["gas_conversion"]): bool,
            vol.Optional(
                "calorific_value",
                **(
                    {"default": defaults["calorific_value"]}
                    if defaults.get("calorific_value")
                    else {}
                ),
            ): vol.All(vol.Coerce(float), vol.Range(min=1, max=100)),
            vol.Required("volume_correction", default=defaults["volume_correction"]): vol.All(
                vol.Coerce(float), vol.Range(min=0.5, max=2)
            ),
        }
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema), errors=errors)

    async def async_step_confirm(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=self.selections)
        names = {
            fuel: next(
                (r.label for r in self.resources if r.key == self.selections.get(fuel)), "None"
            )
            for fuel in FUELS
        }
        return self.async_show_form(
            step_id="confirm", data_schema=vol.Schema({}), description_placeholders=names
        )

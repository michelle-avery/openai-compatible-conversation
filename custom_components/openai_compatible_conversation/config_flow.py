"""Config flow for OpenAI Compatible Conversation integration."""

from __future__ import annotations

import logging
from types import MappingProxyType
from typing import Any

import httpx
import openai
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_API_KEY, CONF_LLM_HASS_API
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TemplateSelector,
    BooleanSelector,
)
from homeassistant.helpers.typing import VolDictType

from .const import (
    CONF_CHAT_MODEL,
    CONF_MAX_TOKENS,
    CONF_PROMPT,
    CONF_RECOMMENDED,
    CONF_TEMPERATURE,
    CONF_TOP_P,
    DOMAIN,
    RECOMMENDED_CHAT_MODEL,
    RECOMMENDED_MAX_TOKENS,
    RECOMMENDED_TEMPERATURE,
    RECOMMENDED_TOP_P,
    CONF_BASE_URL,
    RECOMMENDED_BASE_URL,
    CONF_ENABLE_TOOLS,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): str,
        vol.Required(CONF_BASE_URL, default=RECOMMENDED_BASE_URL): str,
    }
)

RECOMMENDED_OPTIONS = {
    CONF_RECOMMENDED: True,
    CONF_LLM_HASS_API: llm.LLM_API_ASSIST,
    CONF_PROMPT: llm.DEFAULT_INSTRUCTIONS_PROMPT,
    CONF_ENABLE_TOOLS: True,
}


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> None:
    client = openai.AsyncOpenAI(api_key=data[CONF_API_KEY], base_url=data[CONF_BASE_URL])
    await hass.async_add_executor_job(client.with_options(timeout=10.0).models.list)


class OpenAICompatibleConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA)

        errors: dict[str, str] = {}
        try:
            await validate_input(self.hass, user_input)
        except openai.APIConnectionError:
            errors["base"] = "cannot_connect"
        except openai.AuthenticationError:
            errors["base"] = "invalid_auth"
        except Exception:
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            return self.async_create_entry(
                title="OpenAI Compatible",
                data=user_input,
                options=RECOMMENDED_OPTIONS,
            )

        return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return OpenAICompatibleOptionsFlow(config_entry)


class OpenAICompatibleOptionsFlow(OptionsFlow):
    def __init__(self, config_entry: ConfigEntry) -> None:
        self.last_rendered_recommended = config_entry.options.get(CONF_RECOMMENDED, False)
        self.available_models: list[str] = []

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        options: dict[str, Any] | MappingProxyType[str, Any] = self.config_entry.options

        # Fetch models dynamically from OpenRouter/Base URL
        if not self.available_models:
            client = get_async_client(self.hass)
            try:
                base_url = self.config_entry.data.get(CONF_BASE_URL, RECOMMENDED_BASE_URL).rstrip("/")
                api_key = self.config_entry.data.get(CONF_API_KEY, "")
                response = await client.get(f"{base_url}/models", headers={"Authorization": f"Bearer {api_key}"}, timeout=5.0)
                if response.status_code == 200:
                    data = response.json()
                    self.available_models = sorted([model["id"] for model in data.get("data", [])])
            except httpx.RequestError as err:
                _LOGGER.warning("Could not fetch models dynamically, falling back to text input: %s", err)

        if user_input is not None:
            if user_input[CONF_RECOMMENDED] == self.last_rendered_recommended:
                if user_input.get(CONF_LLM_HASS_API) == "none":
                    user_input.pop(CONF_LLM_HASS_API, None)
                return self.async_create_entry(title="", data=user_input)

            self.last_rendered_recommended = user_input[CONF_RECOMMENDED]
            options = {
                CONF_RECOMMENDED: user_input[CONF_RECOMMENDED],
                CONF_PROMPT: user_input[CONF_PROMPT],
                CONF_LLM_HASS_API: user_input.get(CONF_LLM_HASS_API, "none"),
                CONF_ENABLE_TOOLS: user_input.get(CONF_ENABLE_TOOLS, True),
            }

        schema = self.openai_compatible_config_option_schema(options)
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))

    def openai_compatible_config_option_schema(self, options: dict[str, Any]) -> VolDictType:
        hass_apis: list[SelectOptionDict] = [SelectOptionDict(label="No control", value="none")]
        hass_apis.extend(SelectOptionDict(label=api.name, value=api.id) for api in llm.async_get_apis(self.hass))

        schema: VolDictType = {
            vol.Optional(
                CONF_PROMPT,
                description={"suggested_value": options.get(CONF_PROMPT, llm.DEFAULT_INSTRUCTIONS_PROMPT)},
            ): TemplateSelector(),
            vol.Optional(
                CONF_LLM_HASS_API,
                description={"suggested_value": options.get(CONF_LLM_HASS_API)},
                default="none",
            ): SelectSelector(SelectSelectorConfig(options=hass_apis)),
            vol.Optional(
                CONF_ENABLE_TOOLS,
                description={"suggested_value": options.get(CONF_ENABLE_TOOLS, True)},
                default=True,
            ): BooleanSelector(),
            vol.Required(CONF_RECOMMENDED, default=options.get(CONF_RECOMMENDED, False)): bool,
        }

        if options.get(CONF_RECOMMENDED):
            return schema

        # If we successfully fetched models, create a beautiful searchable dropdown. 
        # Otherwise, fall back to a standard text string input.
        if self.available_models:
            model_selector = SelectSelector(SelectSelectorConfig(options=self.available_models, mode="dropdown", custom_value=True))
        else:
            model_selector = str

        schema.update(
            {
                vol.Optional(
                    CONF_CHAT_MODEL,
                    description={"suggested_value": options.get(CONF_CHAT_MODEL)},
                    default=RECOMMENDED_CHAT_MODEL,
                ): model_selector,
                vol.Optional(
                    CONF_MAX_TOKENS,
                    description={"suggested_value": options.get(CONF_MAX_TOKENS)},
                    default=RECOMMENDED_MAX_TOKENS,
                ): int,
                vol.Optional(
                    CONF_TOP_P,
                    description={"suggested_value": options.get(CONF_TOP_P)},
                    default=RECOMMENDED_TOP_P,
                ): NumberSelector(NumberSelectorConfig(min=0, max=1, step=0.05)),
                vol.Optional(
                    CONF_TEMPERATURE,
                    description={"suggested_value": options.get(CONF_TEMPERATURE)},
                    default=RECOMMENDED_TEMPERATURE,
                ): NumberSelector(NumberSelectorConfig(min=0, max=2, step=0.05)),
            }
        )
        return schema

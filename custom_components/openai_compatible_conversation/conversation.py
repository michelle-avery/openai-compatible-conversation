"""Conversation support for OpenAI Compatible APIs."""

from collections.abc import Callable
import json
from typing import Any, Literal, cast

import openai
from openai._types import NOT_GIVEN
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessage,
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCallParam,
    ChatCompletionToolMessageParam,
    ChatCompletionToolParam,
)
from openai.types.chat.chat_completion_message_function_tool_call import Function
from openai.types.shared_params import FunctionDefinition
from voluptuous_openapi import convert

from homeassistant.components import assist_pipeline, conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LLM_HASS_API, MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import chat_session, device_registry as dr, intent, llm
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import OpenAICompatibleConfigEntry
from .const import (
    CONF_CHAT_MODEL,
    CONF_MAX_TOKENS,
    CONF_PROMPT,
    CONF_TEMPERATURE,
    CONF_TOP_P,
    DOMAIN,
    LOGGER,
    RECOMMENDED_CHAT_MODEL,
    RECOMMENDED_MAX_TOKENS,
    RECOMMENDED_TEMPERATURE,
    RECOMMENDED_TOP_P,
    CONF_ENABLE_TOOLS,
)

MAX_TOOL_ITERATIONS = 99

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: OpenAICompatibleConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up conversation entities."""
    agent = OpenAICompatibleConversationEntity(config_entry)
    async_add_entities([agent])

def _format_tool(
    tool: llm.Tool, custom_serializer: Callable[[Any], Any] | None
) -> ChatCompletionToolParam:
    """Format Home Assistant tool specifications into OpenAI function parameters."""
    tool_spec = FunctionDefinition(
        name=tool.name,
        parameters=convert(tool.parameters, custom_serializer=custom_serializer),
    )
    if tool.description:
        tool_spec["description"] = tool.description
    return ChatCompletionToolParam(type="function", function=tool_spec)

def _convert_message_to_param(
    message: ChatCompletionMessage,
) -> ChatCompletionMessageParam:
    """Convert an OpenAI message object to a standard parameter dictionary."""
    tool_calls: list[ChatCompletionMessageToolCallParam] = []
    if message.tool_calls:
        tool_calls = [
            ChatCompletionMessageToolCallParam(
                id=tool_call.id,
                function=Function(
                    arguments=tool_call.function.arguments,
                    name=tool_call.function.name,
                ),
                type=tool_call.type,
            )
            for tool_call in message.tool_calls
        ]
    param = ChatCompletionAssistantMessageParam(
        role=message.role,
        content=message.content,
    )
    if tool_calls:
        param["tool_calls"] = tool_calls
    return param

def _convert_content_to_param(
    content: conversation.Content,
) -> ChatCompletionMessageParam:
    """Convert Home Assistant native chat content into OpenAI message format."""
    if content.role == "tool_result":
        assert type(content) is conversation.ToolResultContent
        return ChatCompletionToolMessageParam(
            role="tool",
            tool_call_id=content.tool_call_id,
            content=json.dumps(content.tool_result),
        )
    if content.role != "assistant" or not getattr(content, "tool_calls", None):
        return cast(
            ChatCompletionMessageParam,
            {"role": content.role, "content": content.content},
        )

    assert type(content) is conversation.AssistantContent
    return ChatCompletionAssistantMessageParam(
        role="assistant",
        content=content.content,
        tool_calls=[
            ChatCompletionMessageToolCallParam(
                id=tool_call.id,
                function=Function(
                    arguments=json.dumps(tool_call.tool_args),
                    name=tool_call.tool_name,
                ),
                type="function",
            )
            for tool_call in content.tool_calls
        ],
    )

class OpenAICompatibleConversationEntity(
    conversation.ConversationEntity, conversation.AbstractConversationAgent
):
    """The central conversation agent for OpenAI-compatible APIs."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, entry: OpenAICompatibleConfigEntry) -> None:
        """Initialize the agent with device registry info."""
        self.entry = entry
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="OpenAI Compatible",
            model="Local & Cloud LLM Agent",
            entry_type=dr.DeviceEntryType.SERVICE,
        )
        if self.entry.options.get(CONF_LLM_HASS_API):
            self._attr_supported_features = conversation.ConversationEntityFeature.CONTROL

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        return MATCH_ALL

    async def async_added_to_hass(self) -> None:
        """Register the pipeline engine when added."""
        await super().async_added_to_hass()
        
        if hasattr(assist_pipeline, "async_migrate_engine"):
            assist_pipeline.async_migrate_engine(
                self.hass, "conversation", self.entry.entry_id, self.entity_id
            )
            
        conversation.async_set_agent(self.hass, self.entry, self)
        self.entry.async_on_unload(
            self.entry.add_update_listener(self._async_entry_update_listener)
        )

    async def async_will_remove_from_hass(self) -> None:
        """Cleanup upon removal."""
        conversation.async_unset_agent(self.hass, self.entry)
        await super().async_will_remove_from_hass()

    async def async_process(
        self, user_input: conversation.ConversationInput
    ) -> conversation.ConversationResult:
        """Process incoming sentences from the user."""
        with (
            chat_session.async_get_chat_session(
                self.hass, user_input.conversation_id
            ) as session,
            conversation.async_get_chat_log(self.hass, session, user_input) as chat_log,
        ):
            return await self._async_handle_message(user_input, chat_log)

    async def _async_handle_message(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> conversation.ConversationResult:
        """Execute the API call and let HA handle the tool execution loops."""
        assert user_input.agent_id
        options = self.entry.options

        try:
            llm_context = llm.LLMContext(
                platform=DOMAIN,
                context=user_input.context,
                language=user_input.language,
                assistant=conversation.DOMAIN,
                device_id=getattr(user_input, "device_id", None),
            )
            
            if options.get(CONF_LLM_HASS_API):
                chat_log.llm_api = await llm.async_get_api(
                    self.hass, 
                    options[CONF_LLM_HASS_API], 
                    llm_context
                )
            if options.get(CONF_PROMPT):
                chat_log.system_prompt = options[CONF_PROMPT]
        except Exception as err:
            LOGGER.error("Failed to set LLM context: %s", err)

        enable_tools = options.get(CONF_ENABLE_TOOLS, True)
        tools: list[ChatCompletionToolParam] | None = None
        
        if enable_tools and chat_log.llm_api:
            tools = [
                _format_tool(tool, chat_log.llm_api.custom_serializer)
                for tool in chat_log.llm_api.tools
            ]
        
        messages = [_convert_content_to_param(content) for content in chat_log.content]
        client = self.entry.runtime_data

        for iteration in range(MAX_TOOL_ITERATIONS):
            model_args = {
                "model": options.get(CONF_CHAT_MODEL, RECOMMENDED_CHAT_MODEL),
                "messages": messages,
                "max_tokens": options.get(CONF_MAX_TOKENS, RECOMMENDED_MAX_TOKENS),
                "top_p": options.get(CONF_TOP_P, RECOMMENDED_TOP_P),
                "temperature": options.get(CONF_TEMPERATURE, RECOMMENDED_TEMPERATURE),
                "user": chat_log.conversation_id,
                "stream": True, 
            }
            
            if tools:
                model_args["tools"] = tools
            
            try:
                stream = await client.chat.completions.create(**model_args)
            except openai.RateLimitError as err:
                 raise HomeAssistantError("Rate limited or insufficient funds. Check your API provider.") from err
            except openai.OpenAIError as err:
                raise HomeAssistantError("Failed to communicate with the LLM provider.") from err

            accumulated_content = ""
            tool_calls_buffer = {}

            async def _process_stream():
                nonlocal accumulated_content, tool_calls_buffer
                try:
                    async for chunk in stream:
                        if not chunk.choices:
                            continue
                        delta = chunk.choices[0].delta
                        
                        if delta.content:
                            accumulated_content += delta.content
                            # FIX: Use the strict AssistantContentDeltaDict to stop HA from overwriting the memory
                            yield conversation.AssistantContentDeltaDict(
                                role="assistant", 
                                content=delta.content
                            )                        
                        if delta.tool_calls:
                            for tool_call in delta.tool_calls:
                                idx = tool_call.index
                                if idx not in tool_calls_buffer:
                                    tool_calls_buffer[idx] = {
                                        "id": tool_call.id,
                                        "name": tool_call.function.name if tool_call.function else "",
                                        "arguments": tool_call.function.arguments if tool_call.function else ""
                                    }
                                else:
                                    if tool_call.function and tool_call.function.arguments:
                                        tool_calls_buffer[idx]["arguments"] += tool_call.function.arguments
                except openai.APIError as stream_err:
                    LOGGER.error("Stream error: %s", stream_err)

                if tool_calls_buffer:
                    parsed_tool_calls = []
                    for idx, tc in tool_calls_buffer.items():
                        try:
                            parsed_tool_calls.append(
                                llm.ToolInput(
                                    id=tc["id"],
                                    tool_name=tc["name"],
                                    tool_args=json.loads(tc["arguments"]),
                                )
                            )
                        except json.JSONDecodeError:
                            LOGGER.error("Failed to parse tool arguments")
                    
                    if parsed_tool_calls:
                        # FIX: Format tool calls properly for HA 2026.1
                        yield conversation.AssistantContentDeltaDict(
                            role="assistant", 
                            tool_calls=parsed_tool_calls
                        )

            new_contents = [
                content
                async for content in chat_log.async_add_delta_content_stream(
                    user_input.agent_id, _process_stream()
                )
            ]
            
            messages.extend([_convert_content_to_param(content) for content in new_contents])

            if not getattr(chat_log, "unresponded_tool_results", False):
                break
                
            if iteration == MAX_TOOL_ITERATIONS - 1:
                LOGGER.warning("LLM reached max tool iterations. Forced stop.")

        intent_response = intent.IntentResponse(language=user_input.language)
        
        # FIX: Explicitly push our accumulated text to the screen to bypass any memory glitches
        if accumulated_content.strip():
            intent_response.async_set_speech(accumulated_content.strip())
        
        return conversation.ConversationResult(
            response=intent_response, 
            conversation_id=chat_log.conversation_id,
            continue_conversation=chat_log.continue_conversation,
        )

    async def _async_entry_update_listener(
        self, hass: HomeAssistant, entry: ConfigEntry
    ) -> None:
        """Handle dynamic options updates from the UI."""
        await hass.config_entries.async_reload(entry.entry_id)

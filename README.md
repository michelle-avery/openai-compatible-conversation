# 🤖 OpenAI Compatible Conversation (Community Revived - 2026 Edition)
**Unleash Local & Cloud AI in your Smart Home.**  

CODE OWNER WHERE I FORKED FROM 
https://github.com/michelle-avery

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/)
[![Maintained](https://img.shields.io/badge/Maintained%3F-yes-green.svg)](https://github.com/yourusername/openai-compatible-conversation/commits/main)

Bring the power of advanced Language Models to Home Assistant. This integration doesn't just chat—it can physically control your smart home devices and stream responses in real-time.

Because it uses the universal OpenAI API standard, you aren't locked into a single provider. You can point this integration at **OpenRouter**, **LM Studio**, **LocalAI**, **Groq**, **Ollama**, or any other compatible endpoint!

---

## 🌟 The "Next Level" Updates
This project was originally created by Michelle Avery as a simple fork of the native HA OpenAI agent. As Home Assistant's native agent became strictly tailored to OpenAI's proprietary features, this integration became vital for users who wanted to use alternative providers. 

This **Community Revived** version supercharges the original vision with modern features:
* **Live Text Streaming with Tool Buffering:** Responses type out on your screen instantly. Includes a custom background buffer that safely catches and executes fragmented JSON tool calls without breaking the chat UI.
* **Dynamic Model Sync:** No more guessing model names! The integration now automatically connects to your provider (like OpenRouter or LM Studio) and builds a searchable dropdown of every available model.
* **The "Safe Chat" Tool Toggle:** Easily sever the LLM's connection to your smart home devices with a single UI switch. Perfect for using fast, lightweight models for general chatting without risking them hallucinating a command.
* **Infinite Loop Protection:** A built-in killswitch prevents models from getting stuck in endless tool-calling loops, saving your API credits and system resources.
* **Version Compatibility:** Updated to support modern Home Assistant `assist_pipeline` methods and `AssistantContentDeltaDict` streaming.

---

## ✨ Core Features
* **Smart Home Control:** Fully integrated with Home Assistant's `llm_hass_api`. The AI can turn off lights, check sensor statuses, and run scripts automatically based on your natural language requests.
* **Custom Base URLs:** Have a local model running on an old gaming PC? Just change the `Base URL` in the config flow to point to your local IP.
* **Legacy Parameter Support:** Continues to use `max_tokens` instead of the newer `max_completion_tokens` to ensure maximum compatibility across older or open-source local models.

---

## 🚀 Installation & Setup

1. Copy the `openai_compatible_conversation` folder into your `custom_components` directory.
2. Restart Home Assistant.
3. Go to **Settings > Devices & Services > Add Integration**.
4. Search for **OpenAI Compatible Conversation**.
5. Enter your **API Key** and your target **Base URL** (defaults to `https://api.openai.com/v1`).
6. Go to the integration's **Configure** menu. Uncheck "Recommended" and click submit to reveal the advanced options, including the dynamic model dropdown!

---

## ⚠️ A Note on Open-Source Models & Tools
When using this integration to control your house, you must use a model smart enough to understand Home Assistant's internal API. 
* **Tiny models (2B - 7B parameters)** may struggle and output raw formatting instead of acting on the commands. 
* **Recommended Free Models:** `meta-llama/llama-3.1-8b-instruct` or any 20B+ model. 
* **Recommended Paid Models:** `openai/gpt-4o-mini` or `anthropic/claude-3-haiku`.

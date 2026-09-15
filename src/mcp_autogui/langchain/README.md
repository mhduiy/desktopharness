# LangChain client extension

This directory is an optional MCP **client** integration.  The AutoUI MCP
server neither imports nor starts it.  It is only for a separate LangChain
process that connects to an already running, JSON-configured server.

Use `langchain_settings/mcp_config.remote.json` as the client configuration
template and install optional dependencies with:

```bash
uv sync --extra langchain
```

`mcp_manager.py` loads configured MCP client sessions.  `agent_graph.py`
builds a tool-calling graph for a caller that supplies its own model and tools.
Neither module is a server entrypoint or part of the default desktop runtime.

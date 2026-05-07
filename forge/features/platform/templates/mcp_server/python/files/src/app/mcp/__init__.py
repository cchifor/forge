"""MCP (Model Context Protocol) server integration.

Exposes two endpoints:

    GET  /mcp/tools    — list discovered MCP tools across every connected server
    POST /mcp/invoke   — proxy a tool call with approval-mode enforcement

Config lives at project-root ``mcp.config.json`` (see
``docs/mcp.md``). On startup, the router reads the config, spawns a
subprocess per declared server, and builds an in-memory tool registry.
"""

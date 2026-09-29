# Install Rederive in your chat app

Rederive's plugin runs one local MCP server: `plugins/rederive/server/rederive_mcp.py`. It needs Python 3.9 or later and nothing else. Memory is stored in `~/.rederive/memory.db`, shared by every app you connect.

## Claude Code

```
/plugin marketplace add vishanthashok/Rederive
/plugin install rederive@rederive
```

Or from a shell: `claude plugin marketplace add vishanthashok/Rederive` and `claude plugin install rederive@rederive`.

To try a local checkout without installing: `claude --plugin-dir ./plugins/rederive`.

## Claude Desktop and Cowork

Once the directory listing is live, add Rederive from Customize > Plugins. The plugin also reaches Claude Code through account sync.

Local MCP servers run in Claude Code and in Cowork sessions on your computer. claude.ai web chat loads only the skill.

## Codex CLI

As a plugin, which includes the skill:

```
codex plugin marketplace add vishanthashok/Rederive
codex plugin add rederive@rederive
```

Or as a plain MCP server:

```
git clone https://github.com/vishanthashok/Rederive ~/Rederive
codex mcp add rederive -- python3 ~/Rederive/plugins/rederive/server/rederive_mcp.py
```

which writes this to `~/.codex/config.toml`:

```toml
[mcp_servers.rederive]
command = "python3"
args = ["/home/you/Rederive/plugins/rederive/server/rederive_mcp.py"]
```

## Cursor, VS Code, Gemini CLI, Windsurf, and other MCP apps

Clone the repository, then add this server entry to the app's MCP config. Use the absolute path of your clone.

```json
{
  "mcpServers": {
    "rederive": {
      "command": "python3",
      "args": ["/absolute/path/to/Rederive/plugins/rederive/server/rederive_mcp.py"]
    }
  }
}
```

- Cursor: `~/.cursor/mcp.json`
- Gemini CLI: `~/.gemini/settings.json`
- VS Code: `.vscode/mcp.json` in a workspace uses `"servers"` in place of `"mcpServers"`
- Claude Desktop without the plugin: Settings > Developer > Edit Config

Apps without skills don't get the plugin's usage guide. Paste the guidance from `plugins/rederive/skills/memory/SKILL.md` into the app's custom instructions, or rely on the server's built-in instructions, which most apps show to the model.

## ChatGPT

Not supported yet. ChatGPT connects only to MCP servers on a public HTTPS address, and this plugin runs on your computer.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `REDERIVE_DB` | `~/.rederive/memory.db` | Path of the SQLite memory file |

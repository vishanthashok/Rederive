"""Spawn the MCP server and talk to it over stdio, as a chat app would."""

import json
import subprocess
import sys

from plugin_paths import SERVER_DIR


def run(messages, tmp_path):
    proc = subprocess.run(
        [sys.executable, str(SERVER_DIR / "rederive_mcp.py"), "--db", str(tmp_path / "memory.db")],
        input="".join(json.dumps(m) + "\n" for m in messages),
        capture_output=True, text=True, cwd=tmp_path, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return [json.loads(line) for line in proc.stdout.splitlines()]


def call(i, tool, **arguments):
    return {"jsonrpc": "2.0", "id": i, "method": "tools/call",
            "params": {"name": tool, "arguments": arguments}}


def test_handshake_list_and_calls(tmp_path):
    replies = run([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        call(3, "remember", text="I work at Globex.", name="m_globex"),
        call(4, "derive", inputs=["m_globex"], instruction="Employer.", text="User works at Globex.",
             kind="belief", name="employer"),
        call(5, "retract", ref="m_globex"),
        call(6, "recall", ref="nope"),
        call(7, "remember"),
        {"jsonrpc": "2.0", "id": 8, "method": "ping"},
        {"jsonrpc": "2.0", "id": 9, "method": "resources/list"},
    ], tmp_path)
    by_id = {r["id"]: r for r in replies}
    assert len(replies) == 9  # the notification gets no reply

    init = by_id[1]["result"]
    assert init["protocolVersion"] == "2025-06-18"
    assert init["serverInfo"]["name"] == "rederive"
    assert "tools" in init["capabilities"]

    tools = {t["name"]: t for t in by_id[2]["result"]["tools"]}
    assert set(tools) == {"remember", "recall", "derive", "retract", "correct", "forget", "rebuild",
                          "pending_rebuilds", "why", "history", "exposure"}
    assert tools["recall"]["annotations"]["readOnlyHint"] is True
    assert tools["forget"]["annotations"]["destructiveHint"] is True
    for t in tools.values():
        assert t["inputSchema"]["type"] == "object"

    assert by_id[3]["result"]["isError"] is False
    body = json.loads(by_id[5]["result"]["content"][0]["text"])
    assert body["stale_count"] == 1
    assert body["tally"] == {"waiting_for_rewrite": 0, "done": 1}

    assert by_id[6]["result"]["isError"] is True
    assert "no memory found" in by_id[6]["result"]["content"][0]["text"]
    assert by_id[7]["result"]["isError"] is True
    assert by_id[8]["result"] == {}
    assert by_id[9]["error"]["code"] == -32601


def test_unknown_protocol_version_gets_latest(tmp_path):
    replies = run([{"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "1999-01-01"}}], tmp_path)
    assert replies[0]["result"]["protocolVersion"] == "2025-11-25"


def test_bad_json_line(tmp_path):
    proc = subprocess.run([sys.executable, str(SERVER_DIR / "rederive_mcp.py"), "--db", str(tmp_path / "m.db")],
                          input="{not json\n", capture_output=True, text=True, timeout=30)
    assert json.loads(proc.stdout)["error"]["code"] == -32700

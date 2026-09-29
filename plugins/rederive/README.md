# Rederive

Long-term memory for Claude that you can correct.

Most memory tools store facts and summaries and never look back. When one fact turns out wrong, every summary built on it stays wrong. Rederive keeps the lineage: which facts each summary, belief, or profile came from, and how it was built. When you retract or correct a fact, Rederive marks every memory built on it as stale and has Claude rebuild them in dependency order. It stops early when a rebuilt memory says the same thing as before, so one small correction does not rewrite your whole memory.

## What you can do

- **Remember**: Claude saves durable facts you share, such as your job, team, time zone, or preferences.
- **Summarize with lineage**: Claude keeps summaries such as your profile, and each one lists the facts it came from.
- **Correct**: say "that's wrong, it's Sam now". Claude corrects the fact, then rebuilds the profile and everything else that depended on it.
- **Forget**: ask Claude to forget something. Rederive erases it and rejects any rebuild that still contains it, including simple paraphrases.
- **Audit**: ask why Claude believes something, see every version of a memory, or list earlier answers that relied on a fact that has since changed.

Example:

> You: I work at Globex. My manager is Priya.
> Claude builds your profile from those facts.
> You: Actually I left Globex, I'm at Initech now.
> Claude corrects the fact, rebuilds your profile and your renewal plan, and tells you the profile now says Initech.

## Install

**Claude Code**

```
/plugin marketplace add vishanthashok/Redrive
/plugin install rederive@rederive
```

**Claude Desktop and Cowork**: add Rederive from Customize > Plugins once the directory listing is live. The memory tools run in Claude Code and in Cowork sessions on your computer. In claude.ai web chat only the skill loads, because web chat cannot start a local program.

**Codex CLI**

```
codex plugin marketplace add vishanthashok/Redrive
codex plugin add rederive@rederive
```

**Cursor, VS Code, Gemini CLI, and other MCP apps**: see [docs/install.md](https://github.com/vishanthashok/Redrive/blob/main/docs/install.md) in the repository.

## Requirements

Python 3.9 or later, available as `python3`. macOS and most Linux systems already have it. On Windows, install Python from python.org and make sure `python3` works in a terminal. There is nothing else to install: the server uses only the Python standard library.

## What it runs, stores, and sends

- **Runs**: one local program, `server/rederive_mcp.py`, which your chat app starts over standard input and output (MCP stdio). It stops when the app closes.
- **Stores**: one SQLite file, `~/.rederive/memory.db` by default. Set the `REDERIVE_DB` environment variable to use another path. Memories are tagged with the project folder they were saved in and are only visible there, unless saved with global scope. Every app you connect shares the same file, so Claude Code and Codex see the same memory.
- **Sends**: nothing. The server makes no network requests and needs no API key. Your chat app's own model writes every summary and rebuild. Rederive stores the text, tracks what depends on what, orders the rebuilds, and decides when a cascade can stop.
- **Deletes**: forgetting a memory replaces its text with `[deleted]` in the database. To keep future rebuilds from bringing it back, Rederive stores the forgotten text in a constraint table and checks new text against it. To erase everything, delete the database file.

## Tools

| Tool | What it does |
|---|---|
| `remember` | Save a fact |
| `recall` | Search memory or read one memory. Each recall is logged for the exposure report. |
| `derive` | Save a summary, belief, profile, or procedure with the facts it came from |
| `retract` | Mark a memory wrong. Returns the records to rebuild. |
| `correct` | Replace a fact with the corrected version. Returns the records to rebuild. |
| `forget` | Delete a memory so rebuilds cannot bring it back |
| `rebuild` | Submit one rebuilt record. Returns the next records in the queue. |
| `pending_rebuilds` | Resume an unfinished rebuild |
| `why` | Show the facts and instructions behind a memory |
| `history` | Show every version of a memory and the last change |
| `exposure` | List earlier recalls that used a memory that has since changed |

## How early cutoff works

After Claude rewrites a stale record, Rederive compares the old and new text claim by claim. Each sentence is matched to its closest sentence on the other side, and the weakest match is the score. At 0.97 or above, the record counts as unchanged, and records built on it are marked valid again without a rewrite. Below that, the change is treated as real and the records built on it are queued. The comparison runs locally with a hashed bag-of-words embedding.

## Limits

- The paraphrase check for forgotten information uses word overlap, digit runs, and email names. It catches close rewordings, not every possible paraphrase, so Claude is also told not to repeat forgotten information.
- Rebuilds happen while you chat. A correction that touches many memories takes several tool calls.
- The memory file is not encrypted. It has the same protection as other files in your home folder.

## Source and license

Source: https://github.com/vishanthashok/Redrive. MIT license. The plugin is a local port of the Rederive server in the same repository, which adds Postgres, background workers, a graph UI, and optional Claude API calls for unattended rebuilds.

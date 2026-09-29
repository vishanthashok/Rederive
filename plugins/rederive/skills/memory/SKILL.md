---
name: memory
description: Long-term memory about the user with lineage and corrections. Use when the user shares a durable fact about themselves (job, name, preferences, plans), asks what you remember, says something you remembered is wrong or outdated, or asks you to forget something. Also use before answering questions that depend on who the user is.
---

# Rederive memory

Rederive stores what the user tells you, the summaries you build from it, and which facts each summary came from. When a fact turns out wrong, Rederive marks every memory built on it as stale and hands you a queue of records to rewrite, in dependency order. It stops the cascade early when a rewrite says the same thing as before.

The tools come from the `rederive` MCP server. If they are not available, tell the user that Rederive needs Python 3.9 or later on this computer, and that it runs in Claude Code and Cowork, not in claude.ai web chat.

## Recall before you answer

Before answering anything that depends on the user (their job, team, preferences, past requests), call `recall` with a short query. Prefer derived records such as `profile` over raw facts when both exist. Never state a remembered fact as current if its status is `stale`.

## Remember durable facts

When the user states a fact that will matter later, call `remember` with the fact in their words. One fact per call. Skip small talk, one-off task details, and anything the user asks you not to keep.

Use `scope: "global"` for facts about the person (name, timezone, preferences). Use the default project scope for facts about the current project.

## Build summaries with derive

After a few related facts, keep a summary current with `derive`:

- `inputs`: the ids or names of every memory you used, and only those.
- `instruction`: how to build this record, written so someone could rebuild it from new inputs. Example: "One-paragraph customer profile: name, employer, role, manager, timezone. Use the most recent statement when facts conflict."
- `text`: the record itself. Use only facts from the inputs.
- `name`: a stable name such as `profile`, `employer`, or `contact_plan`. Deriving again with the same name creates a new version and marks everything built on the old version stale.
- `kind`: `belief` for a single fact, `summary` for a profile or topic summary, `procedure` for how to act for this user.

## When the user corrects you

1. Find the wrong memory with `recall`, then `why` if you need to see where a summary's claim came from.
2. If the user gave the right fact, call `correct` on the original fact. If the fact was simply wrong, call `retract`.
3. Work through `rebuild_queue`. For each item, rewrite the record by following its `instruction`, using only its current `inputs`, then call `rebuild` with the new text. Each call returns the next queue. Continue until the queue is empty. Do not skip items. If the output would say the same thing as `previous_text`, submit it anyway: Rederive detects that and stops the cascade there.
4. Tell the user what changed in one or two lines: how many memories were rebuilt, how many stopped early, and the new value of the key fact.
5. Call `exposure`. If earlier answers or actions relied on the wrong fact, name them so the user can review them.

If a conversation ended mid-cascade, `pending_rebuilds` returns the remaining queue.

## When the user asks you to forget something

Call `forget` on the memory. Then rebuild every item in `rebuild_queue` without the forgotten information. Rederive rejects a rebuild that still contains it, so rewrite and resubmit if that happens. If `still_mentioned_in` lists other facts, ask the user whether to forget those too.

## Explain your memory

- `why`: which facts and instructions produced a memory.
- `history`: every version of a memory and what changed last.

Keep tool output out of your reply unless the user asks for it. Summarize instead.

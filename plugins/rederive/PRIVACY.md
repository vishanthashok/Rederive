# Rederive privacy policy

Last updated: September 29, 2026

Rederive is a plugin that gives Claude and other chat apps long-term memory. It runs entirely on your computer.

## What Rederive stores

- Facts you ask the chat app to remember, in your words. These can include personal details you choose to share, such as your name, email address, phone number, employer, or preferences.
- Summaries, beliefs, and procedures that the chat app's model writes from those facts, with a record of which facts each one came from.
- A log of which memories each recall returned, used for the exposure report.
- Text you asked Rederive to forget, kept only as a rule that blocks future rebuilds from repeating it.

## Where it is stored

Everything is stored in one SQLite file on your computer, `~/.rederive/memory.db` by default, or the path you pass with `--db`. The file is not encrypted. It has the same protection as other files in your home folder.

## What Rederive sends

Nothing. Rederive makes no network requests, has no telemetry or analytics, and needs no account or API key. The developer never receives your data.

Your chat app sends conversation content, including memories it recalls, to its own model provider under that app's privacy policy. For Claude, see https://www.anthropic.com/legal/privacy.

## How long data is kept

Memories stay in the file until you remove them. To remove one memory, ask the chat app to forget it: Rederive replaces its text with `[deleted]` and marks memories built on it for rebuilding. To remove everything, delete the database file.

## Children

Rederive is not intended for users under 18.

## Changes and contact

Changes to this policy are published in this file in the repository, https://github.com/vishanthashok/Rederive. For questions, open an issue in that repository.

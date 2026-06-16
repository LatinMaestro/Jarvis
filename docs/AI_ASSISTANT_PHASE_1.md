# Jarvis Discord AI Assistant - Phase 1

## Purpose

Phase 1 adds a Discord-native `@Jarvis` assistant to the existing bot. The assistant is mention-based, uses Gemini free tier only, and keeps all existing `!` commands intact.

Phase 1B makes stat answers data-first: Jarvis detects factual stat intent, runs approved read-only helpers, builds the factual answer, and then uses Gemini only for style and light banter.

Website and web app work is paused for this phase.

## User interface

Users ask questions by mentioning the bot in a normal Discord channel:

```text
@Jarvis roast LatinMaestro
@Jarvis who improved the most this season?
@Jarvis which duo has the best chemistry?
@Jarvis what hero should I play more?
```

Jarvis ignores:

- bot messages;
- non-mention messages;
- existing `!` commands after passing them through `bot.process_commands`.

Empty mentions return a short help message.

## Provider model

Phase 1 supports Gemini only:

```env
AI_ASSISTANT_ENABLED=true
AI_PROVIDER=gemini
AI_MODEL=gemini-2.5-flash-lite
GEMINI_API_KEY=
AI_ASSISTANT_FREE_ONLY=true
```

There is no OpenAI, Groq, Anthropic, paid Gemini fallback, or automatic paid fallback path.

If Gemini is disabled, missing a key, rate-limited, or quota-limited, Jarvis replies gracefully instead of switching providers. When approved stat helpers already produced a factual answer, Jarvis returns that deterministic stat-backed answer instead of a generic AI-unavailable message.

## Data model

The assistant does not give Gemini unrestricted SQL access.

Phase 1A flow:

```text
Discord question
Bot strips @Jarvis mention
Bot chooses approved read-only helpers
Bot sends bounded stat summaries to Gemini
Gemini writes the final Discord response
```

Phase 1B data-first flow:

```text
Discord question
Bot strips @Jarvis mention
Bot detects stat intent
Bot runs approved read-only helpers
Bot builds a deterministic factual answer
Gemini receives the factual answer plus bounded context for wording only
Final response preserves the factual answer
```

The assistant cannot:

- write league stats;
- delete matches;
- change seasons;
- trigger imports;
- run admin commands;
- execute arbitrary SQL;
- dump raw match JSON;
- access secrets.

Gemini must not invent exact stats or tell the user to "ask the bot"; Jarvis is the bot. The model can add concise personality only after the stat answer is already present.

## Approved Phase 1 tools

The assistant package exposes predefined read-only helpers for:

- current season marker;
- known player list;
- player summaries;
- player comparisons;
- hero summaries;
- duo synergy;
- recent games;
- latest session summary;
- player roast context;
- lobby roast context;
- leaderboard summaries;
- first-place lookup using the main leaderboard threshold;
- top players by whitelisted metric;
- highest win rate;
- top or worst duo chemistry;
- best players by role;
- best players by hero;
- player podium context;
- player recommendation context.

These helpers are parameterized and bounded. They use the configured bot database at runtime and copied snapshot fixtures during tests.

## Controls

Environment controls:

- `AI_ASSISTANT_ALLOWED_CHANNEL_IDS`
- `AI_ASSISTANT_DENIED_CHANNEL_IDS`
- `AI_ASSISTANT_MAX_CONTEXT_ROWS`
- `AI_ASSISTANT_MAX_RESPONSE_CHARS`
- `AI_ASSISTANT_COOLDOWN_SECONDS`
- `AI_ASSISTANT_LOGGING_ENABLED`
- `AI_ASSISTANT_DAILY_SOFT_LIMIT`
- `AI_ASSISTANT_MONTHLY_SOFT_LIMIT`

## Logging

When enabled, Phase 1 creates and writes to:

```sql
ai_query_log
```

The log stores metadata, question text, tool names, response preview, error class, detected intent, whether Gemini was called, and whether a deterministic fallback was used. It must not store secrets.

## Testing

Normal offline checks:

```bash
python -S -m py_compile main.py
python scripts/inspect_jarvis_db.py
python scripts/jarvis_offline_smoke.py
python scripts/generate_db_sample_outputs.py
python -m unittest discover -s tests
```

Tests mock Gemini and do not connect to live Discord, Railway, production data, or the live database.

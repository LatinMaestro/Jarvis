# Jarvis Web Platform Vision

## Purpose

Jarvis should evolve from a Discord-only statistics bot into a private league platform with two coordinated surfaces:

- the existing Discord bot; and
- a private website for league stats, seasons, profiles, match history, team generation, and session tools.

The website is a future product surface. It should preserve the current bot's statistics meaning, league language, and trusted workflows while making league history easier to browse outside Discord.

This document is planning guidance only. It does not authorize building or deploying a production web app yet.

## Sources of truth

The existing operating model remains required:

- GitHub remains the source of truth for bot code, documentation, CI, and future website code.
- Railway remains the live runtime for the Discord bot.
- The Railway persistent volume database remains the source of truth for current live statistics.
- The GitHub-bundled `marvel_rivals_stats.db` remains an offline regression snapshot only.

The GitHub snapshot database must never be described as current production data. It is useful for local development, regression checks, schema inspection, and sample output generation.

## Why Railway and GitHub still matter

Railway is still needed for the live Discord bot unless the owner explicitly approves a runtime migration. The future web platform should not force a bot hosting change.

GitHub is still needed as the reviewed source of truth for code, docs, CI, issue history, and pull requests. Future website work should land through GitHub PRs with offline evidence before any owner-approved deployment.

## Product goals

The private website should eventually provide:

- season and all-time league dashboards;
- player profile pages;
- hero and role statistics;
- bans and ban trends;
- match history and match detail pages;
- head-to-head views;
- leaderboards;
- team generation tools;
- session and fairness tools;
- pregame output previews;
- role distribution summaries;
- admin-only or owner-only league maintenance views, if approved later.

## Non-goals for the first planning phase

The first phase must not:

- replace the Discord bot;
- access the live Railway production database;
- connect to live Discord;
- introduce production secrets;
- migrate the live database;
- change season windows;
- change command behavior;
- create public access to private league data.

## Success criteria

A successful first web-platform effort should:

- keep the Discord bot stable;
- make read-only league data easier to browse;
- use copied fixtures or snapshot data for development;
- keep production data isolated from Codex and local test runs;
- document all assumptions before live data access is considered;
- provide owner-reviewable PRs with tests, screenshots, and sample output evidence.


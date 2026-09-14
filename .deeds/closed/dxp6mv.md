---
tier: objective
---
# Compress the packaged guide with subagents and remove context leaks

User request, 2026-09-13: iterate over `binja/guide.md` (printed by `binja skill`)
with subagents to remove context leaks and perform semantic compression.

Background: the guide grew to about 300 lines across the Rust rewrite and the
recipe work, written section by section by agents who had the session in front
of them. Every agent pays for the whole file on each `binja skill`, so the
per-session cost is a few thousand tokens before any work starts. Two failure
modes to hunt:

- Context leaks: sentences that only make sense against a change ("remains
  available with its previous semantics", "no fixed polling delay", trial
  numbers, phase names, comparisons to behavior that no longer exists).
- Redundancy: the same rule stated in two sections, JSON field lists that
  repeat what `--json` output shows, defensive caveats an agent will never act on.

Method: subjects without repository context read the guide and do a task; a
separate pass rewrites for a reader who has never seen a previous version. Keep
the recipes runnable and validated, and keep every rule that a trial subject
actually needed. Measure tokens before and after with the same tokenizer proxy
used in the investigation log. Do not move content into `docs/`; the guide is
the single installed source.

Closed: Guide compressed from 4792 to 2621 o200k tokens over five cold subagent reviews; two factual corrections; four tool follow-ups filed (jxc5gg, 33qaa7, sq389d, aqxvch). Evidence in temp/guide-compression/ and docs/log.md.

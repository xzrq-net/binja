---
tier: objective
---
# Remove session context from docs and simplify workspace sessions

User request: review the completed MVP, focusing on written materials: repeated
upstream versions, repository-specific paths, the BINJA_STATE_DIR prerequisite,
and other context leaks. This is a preliminary cleanup; do not run subagent
reviews or usability trials yet.

Keep setup in README, the installed workflow in `binja skill`, architecture in
the design, delivery work in deeds, and historical observations in the log.
Make ordinary commands select a workspace session without shell exports; retain
an explicit state-directory option. Verify the changed command behavior and
review the docs against the implementation.

Closed: Cleaned reference docs and installed guide; added workspace session defaults and path-preserving recovery hints. Nix build, focused CLI checks, and live smoke suite passed. Save-limit bug filed as 2ajrs7; subagent trials remain gated.

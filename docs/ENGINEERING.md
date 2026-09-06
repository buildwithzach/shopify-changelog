# Project-aware checks: v0.2 design

Goal: starting a Shopify development task should surface relevant release evidence without requiring a special prompt.

## Boundaries

The scanner reads project manifests, Shopify config, and selected source files locally. It never executes project code or uploads source. Reads are bounded by file count, total bytes, and elapsed time; skipped or incomplete scanning is reported. Symlinks and dependency/build/secret directories are excluded.

A project API version is evidence with a file, line, and scope. Webhook versions do not establish an Admin API client's version. Dependency ranges are declared ranges, not resolved installed versions. A release's version tags are mentions, not universal minimum versions. Multiple components and unknown versions remain explicit.

Findings distinguish identifiers actually present in code from broad surface matches. Both are candidates for review, not proof that a release breaks the project. Every finding includes the article URL, dated source text, and local evidence. No results is not a certification of compatibility.

## Runtime

`inspect` identifies project signals. `check` refreshes stale feeds by default, then reports relevant evidence as text or JSON. `--offline` uses the archive with explicit freshness. Empty or failed archives are incomplete results, not clean checks.

SessionStart and UserPromptSubmit hooks perform bounded offline checks only. They inject short context, never block a prompt, and tell the agent when a refresh is needed. They do not perform network requests, execute repository scripts, log prompts, or edit the project. Installation merges the selected agents' existing hook configuration and preserves unrelated hooks. Enabling hooks is an explicit setup option.

Official hook contracts:

- https://developers.openai.com/codex/hooks
- https://code.claude.com/docs/en/hooks

Codex requires review/trust of new or changed non-managed hook definitions. Hooks may also be disabled by user or administrator settings. Setup does not bypass either restriction.

## Release acceptance

- Version detection retains correct scope and source locations.
- Exact identifier changes outrank broad category matches; unrelated source text does not become a confirmed finding.
- No detected Shopify project produces no hook output or network requests.
- Empty/stale archives and scan limits remain visible.
- Installer is idempotent and preserves unrelated settings/instructions.
- Hook payloads match both documented event schemas and fail open.
- The packaged skill works from a fresh public install.

Automated fixture tests validate these behaviors; they are not a measured accuracy claim across real production projects.

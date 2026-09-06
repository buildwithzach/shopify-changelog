# Worked example: an order import

This was checked against the downloaded official feed archive on September 6, 2026. The project is a small detection fixture, not a runnable application or a customer repository.

The fixture has a Shopify Remix dependency, an `orderCreate` mutation in `app/import.ts:4`, and an Admin API version declaration of `2026-07` in `app/shopify.ts:2`. Its app TOML separately declares webhook version `2026-10`.

Run against a project with that structure:

```sh
shopify-updates check /path/to/project --task "Add multiple tracking numbers to order imports"
```

The check returned the [August 3 announcement about multiple tracking numbers](https://shopify.dev/changelog/order-create-fulfillment-tracking-numbers). It matched the identifier in the source file and identified that the app's client version precedes the version mentioned by the announcement. It did not mistake the newer webhook version for the API client version.

| Report field | Evidence |
| --- | --- |
| Match | `orderCreate` in `app/import.ts:4` |
| Client version | `2026-07`, declared in `app/shopify.ts:2` |
| Announcement version | `2026-10` |
| Webhook version | Retained separately; excluded from client comparison |
| Next step | Read the announcement and applicable API docs before choosing the implementation |

The task-specific report prioritized the identifier finding and suppressed broad surface-only candidates. The report also included the original source link, publication date, archive freshness, and release-condition excerpts.

This validates that evidence retrieval and version scoping work for this example. It does not prove the agent will make the right implementation decision, nor establish accuracy across all Shopify projects.

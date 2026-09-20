# Windows plan balance

The Windows settings page shows the automatically detected **Codex** plan.
Its selector is read-only; it does not write a manual override.

| Plan | Growth requirements | Shop prices | Rare Candy XP |
| --- | --- | --- | --- |
| Go / Plus | Current Plus baseline | Current Plus baseline | 100M |
| Pro (5x or 20x) | 5 × Plus | 5 × Plus | 500M |

The Pro growth requirements and shop prices match the original balance.
Candy effects scale with the current Plus baseline, so they intentionally
differ from the original Swift candy effect. Counts of items, reward grants,
and shiny/rarity odds do not change with a plan.

When the detected plan changes, both the egg progress and the current
Pokemon's stage XP are converted to the new units. For example, 10M / 25M
becomes 50M / 125M: 40% in both cases. Conversion rounds down by less than one
destination XP. It does not evolve, graduate, or hatch a Pokemon by itself.
The scale is saved alongside progress, including in exported saves, so a
restart or import cannot multiply progress again.

Actual usage statistics, per-provider scan baselines, and earned/spent shop
tokens remain unchanged. New tokens still grant their actual amount of XP;
scaling new XP as well would cancel out the plan adjustment. Candy grants
growth only, not spendable tokens.

Detection uses the local Codex app-server `account/read` method with
`refreshToken: false`. Only a supported plan name is retained, not account
identifiers, email, or credentials. The Windows desktop's bundled native CLI
is used if Codex is not on PATH. Queries run in a background thread with a
timeout and no console window. A completed result wakes the daemon promptly;
normal rechecks occur on polling, no more often than every two minutes.

If Codex is missing, signed out, uses an API key, returns an unsupported plan,
or cannot be read, settings show that detection is unavailable. The last saved
scale is retained; a new or legacy save without scale metadata uses Plus.
Other providers' plans are not inferred from their token usage.

The plan name may be returned simply as `pro`. Both Pro tiers deliberately
have the same scale, so a more specific subscription tier is not required.

Reference: [Codex app-server account API](https://learn.chatgpt.com/docs/app-server).

Windows notification helpers and update validation also use
`CREATE_NO_WINDOW`, preventing the console flashes associated with actions.

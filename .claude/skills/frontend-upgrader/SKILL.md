---
name: frontend-upgrader
description: Use this skill whenever the user wants to improve, polish, or "upgrade" the frontend of a website or app — transitions/animations, charts and data visualizations, or overall layout/spacing/component design. Trigger it for requests like "make this feel more premium," "add smoother transitions," "the charts look flat," "improve the spacing," "this page looks dated," or any request to restyle, re-lay-out, or animate an existing UI. This skill pulls concrete component/animation/layout patterns from a curated set of free, open-source reference libraries instead of inventing styles from scratch, so use it any time real inspiration or copy-pasteable component patterns would improve the result more than a generic redesign would.
---

# Frontend Upgrader

## Purpose

Most "make my UI better" requests fail not because the code is wrong, but because the result has no reference point — it's just a generic guess at "modern." This skill fixes that by grounding upgrades in real, current examples pulled from a curated set of free component/animation/dataviz libraries, then adapting the *patterns* (not copy-pasted code, unless the source is genuinely free-to-copy) to the user's actual stack.

Also read `/mnt/skills/public/frontend-design/SKILL.md` before making visual changes — it covers general design-token and styling constraints for this environment and should be used alongside this skill, not instead of it.

## Reference sources

Route the request to the right source(s) based on what's being upgraded. If a request spans categories (e.g. "upgrade the whole dashboard"), pull from more than one.

### Transitions & motion
- **Motion** (https://motion.dev/) — the animation library formerly known as Framer Motion. Use for React/JS animation primitives: springs, gestures, scroll-linked effects, layout transitions, view transitions. Has 400+ free copy-paste examples.
- **KokonutUI** (https://kokonutui.com/) — 100+ free, open-source animated components (buttons, cards, nav, micro-interactions) built with Tailwind CSS, shadcn/ui, and Motion. Good for whole-component transition patterns rather than raw animation primitives.

### Charts & data visualization
- **Bklit UI** (https://bklit.com/) — free, open-source chart components (line, area, ring, radar, bar, and more) built on shadcn/ui with Motion-powered transitions. Composable — combine primitives like Grid, XAxis, ChartTooltip rather than using monolithic chart components.

### Overall layout, spacing & component design
- **Refero Styles** (https://styles.refero.design/ai-agents/design-resources) — a library of `DESIGN.md` files extracting the actual design tokens (color, type scale, spacing, motion, component patterns) from real, well-regarded product sites (Linear, Stripe, Vercel, etc.). Use this to ground layout/spacing decisions in a *specific* named reference rather than vague taste words.
- **Aceternity UI** (https://ui.aceternity.com/) — 200+ free, animated Tailwind + Framer Motion components and blocks (heroes, bento grids, navbars, cards). Good for whole-section layout inspiration, not just individual components.
- **Watermelon UI** (https://ui.watermelon.sh/) — open-source registry of 260+ copy-pasteable React components plus full page blocks and dashboards, built with Tailwind + Radix/shadcn. Good for both individual components and assembled sections (auth pages, dashboards, footers, blog layouts).
- **GrayBlocks** (https://grayblocks.net/) — a mixed free/paid library of layout blocks (hero, pricing, testimonials, etc.) for **Figma, Framer, and Webflow only** — no React/code output. Use it purely for visual/layout inspiration (composition, hierarchy, section structure) to reimplement in code, not as a source of copy-pasteable code. Check whether the specific block you're referencing is in GrayBlocks' free tier before assuming it's freely reusable.

## Hard rule: every decision traces back to a source

Nothing in this skill should be invented from scratch. Every component, animation, chart, or layout/spacing decision must come from one of the sources listed above — either:

- **used directly**, when the source is free/open-source and the code is copy-pasteable as-is (e.g. Bklit UI, KokonutUI, Watermelon UI, Aceternity UI components), or
- **adapted**, when the source isn't directly usable — wrong stack, paid tier, design-tool-only output like GrayBlocks, or a pattern that needs reshaping to fit the user's codebase — in which case reimplement the *pattern* (the spacing rhythm, the easing curve, the composition) rather than the exact asset.

Which sources apply to a given request, and whether to use a source directly or adapt it, is Claude's judgment call — the reference sections above are a starting map, not a rigid lookup table. If a request could reasonably be grounded in more than one source, pick whichever gives the closest, most concrete match rather than blending vague impressions of several. The one thing that isn't optional is skipping the sources entirely and defaulting to generic/default styling, spacing, or motion choices — always go look first, even for small tweaks.

## Workflow

1. **Clarify the target.** Confirm (or infer from context) which file(s)/component(s) are being upgraded and what category applies (motion, charts, or layout). If genuinely ambiguous and nothing in the conversation or codebase hints at it, ask — don't guess on a codebase-wide change.

2. **Look, don't assume — always.** Before proposing changes, use `web_search` for the relevant site(s) above (site content isn't fetchable directly from memory — search first, then `web_fetch` the specific page/doc that shows the pattern you need, e.g. a component's docs page or code example). Pull 1-3 concrete patterns relevant to the request rather than a broad survey. This step applies even to small tweaks — never fall back on generic/default choices just because the request seems minor.

3. **Adapt, don't clone.** Study the interaction pattern, spacing rhythm, or animation curve — then reimplement it to fit the user's existing stack, component structure, and design tokens. Copy exact free/open-source code (e.g. Bklit UI or KokonutUI components, which are explicitly free-to-copy) when it saves the user time and licensing allows it; for anything not explicitly free-to-reuse, describe and reimplement the pattern rather than lifting code verbatim.

4. **Keep it consistent.** Cross-check new spacing, color, and motion choices against what's already in the user's project (existing Tailwind config, design tokens, component library) so the upgrade blends in rather than clashing with untouched parts of the UI.

5. **Show, then explain briefly.** Apply the change to the actual file(s). After, give a short (2-3 sentence) note on which reference pattern inspired the change and why it fits — not a full design essay.

## Notes

- Most of these are free-tier/open-source as of the last check, but GrayBlocks is mixed free/paid and design-tool-only (no code) — verify tier and treat as visual reference only. If a fetch shows any source has gone paid-only or changed significantly, mention that to the user rather than silently substituting a different source.
- Motion, KokonutUI, Aceternity UI, Bklit UI, and Watermelon UI are all Tailwind + React-first. If the user's project uses a different stack, translate the *pattern* (easing curves, spacing scale, layout structure) rather than the exact code.
- Don't reproduce large verbatim code blocks from documentation pages as if summarizing an article — treat fetched docs as reference material to learn from and reimplement, same as any other source.

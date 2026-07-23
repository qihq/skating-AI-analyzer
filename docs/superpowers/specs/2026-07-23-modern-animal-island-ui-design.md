# IceBuddy Modern Animal-Island UI Redesign

**Date:** 2026-07-23

**Status:** Approved design

## Objective

Rebuild only IceBuddy's modern UI into a coherent, Animal-Island-inspired family growth experience. The redesign must simplify navigation, merge duplicate entry points, improve every page layout, and provide first-class phone PWA, iPad, and desktop behavior. The existing classic UI remains available and receives no intentional visual or navigation changes.

This is an information architecture and layout redesign, not a theme-only reskin.

## Product Decisions

- Keep classic and modern UI as equally supported choices; this project changes modern UI only.
- Use a family-growth product model rather than a professional-analysis-first model.
- Use four primary spaces: Home, Review, Growth, and Me.
- Combine a conventional four-space architecture with an optional island-map presentation on Home.
- Give child and parent modes the same page structure. Mode changes copy, density, disclosure, and permissions, not navigation or layout.
- Put advanced tools behind parent verification under Me.
- Merge duplicate pages and entry points while preserving old URLs.
- Use time-aware morning, daytime, sunset, and night themes with a manual override.
- Make Start Review the raised central action in the phone PWA navigation.

## Reference Library and License

The visual reference is [guokaigdg/animal-island-ui](https://github.com/guokaigdg/animal-island-ui), version `1.3.0` at design time. A complete offline clone is stored locally at `tmp/animal-island-ui-reference`; it contains 165 commits and 15 tags and is excluded from this repository by `.gitignore`.

The library is licensed under CC BY-NC 4.0. IceBuddy is confirmed to be personal and non-commercial. Any reused or adapted code and assets must retain attribution and the CC BY-NC 4.0 notice. Modern UI exposes that attribution under Me > About and Open-Source Licenses. If IceBuddy's use ever becomes commercial, reused library code and assets must be removed or separately licensed before distribution.

The reference project states that its visual elements, layouts, icons, and animations are independently designed and do not directly include official Nintendo art, code, or resource files. IceBuddy must not add Nintendo trademarks, characters, official artwork, audio, or other first-party game assets.

## Information Architecture

### 1. Home: Today Island

Home answers one question: "What is the most useful thing to do today?"

It contains:

- the current skater and family context;
- one primary next action;
- an unfinished review resume card when applicable;
- the latest progress highlight;
- today's training reminder or active plan;
- a small recent milestone feed;
- shortcuts to monthly story and the full Growth space.

Child mode presents these destinations as an interactive island map with recognizable landmarks. Parent mode adds compact metrics and explanatory summaries. The island map is never the sole navigation mechanism: an equivalent semantic list is always present for keyboard access, assistive technology, reduced-motion users, and low-performance devices.

### 2. Review: Ice Rink Lodge

Review is one continuous task rather than a set of unrelated pages:

1. select or upload a video;
2. select the skater;
3. confirm the target and analysis window;
4. review notes and analysis options;
5. submit and view processing progress;
6. enter the resulting Analysis Detail.

The flow persists its current step and analysis identifier. Reopening the PWA resumes an unfinished flow rather than returning to a blank upload screen.

### 3. Analysis Detail

Analysis Detail is the single authoritative surface for an analysis. It combines the existing report, evidence workspace, pose view, diagnostics, and follow-up chat.

Its internal sections are:

- Summary: conclusion, training focus, issues, improvements, and scores;
- Moments: video, action phases, keyframes, and synchronized evidence;
- Body: pose and biomechanics;
- Ask: contextual follow-up and corrections;
- More: quality information, retry actions, target correction, and parent-only diagnostics.

Phone uses a single column with a sticky section switcher and a context-aware bottom action sheet. iPad and desktop can show video/evidence beside the active report section. Diagnostics remain progressively disclosed and require parent access where appropriate.

### 4. Growth: Growth Archipelago

Growth owns all longitudinal content. Its overview shows the latest trend, recent sessions, active skills, current plan, monthly story status, and a clear next action. Internal destinations are:

- Overview;
- Timeline, including history and filtering;
- Compare;
- Monthly Chapters;
- Annual Collection;
- Skills and Goals;
- Plans;
- Snowball as a growth topic rather than a primary route.

These are sections of one product space, not competing primary navigation entries. Only the active section and its immediate supporting content render at high density.

### 5. Me: Resident Services

Me owns:

- family members and current skater;
- child/parent mode and parent PIN;
- automatic or fixed time theme;
- notifications and PWA preferences;
- storage and application information;
- About and Open-Source Licenses;
- Advanced Tools.

Advanced Tools requires parent verification and groups provider/API configuration, debugging, Golden labels, pose diagnostics, and the professional analysis workspace. These tools use the same shell and tokens but may retain higher information density.

## Navigation and Entry-Point Rules

Modern UI has exactly four primary destinations. Contextual links may deep-link into them, but no contextual link becomes an additional primary destination.

- Home is the default modern landing page.
- Start Review is the global primary action.
- Growth is the only top-level entry for progress, history, comparisons, chapters, collections, skills, goals, and plans.
- Me is the only top-level entry for identity, modes, appearance, configuration, and advanced tools.
- Analysis Detail is contextual and does not appear as a permanent primary tab.
- A common action has one authoritative entry. Other appearances are labeled shortcuts that land on the same state.
- Common destinations require no more than two navigation levels from a primary space.

## Modern Canonical Routes

Modern UI uses the following canonical route model:

| Purpose | Canonical route |
| --- | --- |
| Today Island | `/home` |
| Review flow | `/review` with persisted step state |
| Growth overview | `/growth` |
| Growth section | `/growth?view=timeline|compare|chapters|annual|skills|plans|snowball` |
| Analysis detail | `/analysis/:id?view=summary|moments|body|ask|more` |
| Resident Services | `/me` |
| Advanced tools | `/me/advanced?tool=providers|debug|golden|pose|workspace` |

Classic UI keeps its current route components and behavior. A theme-aware routing boundary decides whether a legacy URL renders the classic component or maps modern UI to the canonical destination. Identifier parameters and meaningful query state must survive mapping.

### Legacy Modern-Mode Mapping

| Existing route | Modern destination |
| --- | --- |
| `/chapters` | `/growth?view=chapters` |
| `/annual` | `/growth?view=annual` |
| `/path` | `/growth?view=skills` |
| `/snowball` | `/growth?view=snowball` |
| `/archive`, `/history`, `/progress` | `/growth?view=timeline` |
| `/compare/results/:comparison_id` | `/growth?view=compare&comparison=:comparison_id` |
| `/compare/:id_a/:id_b` | `/growth?view=compare&a=:id_a&b=:id_b` |
| `/report/:id` | `/analysis/:id?view=summary` |
| `/report/:id/workspace?tab=pose` | `/analysis/:id?view=body` |
| `/report/:id/workspace?tab=evidence` | `/analysis/:id?view=moments` |
| `/report/:id/workspace?tab=followup`, `/analysis-chat` | `/analysis/:id?view=ask` when an ID is available |
| `/report/:id/workspace?tab=diagnostics`, `/report/:id/pose-debug` | `/analysis/:id?view=more&tool=diagnostics` |
| `/report/:id/target` | `/review?analysis=:id&step=target` |
| `/settings` | `/me` |
| `/settings/api` | `/me/advanced?tool=providers` |
| `/debug` | `/me/advanced?tool=debug` |
| `/golden` | `/me/advanced?tool=golden` |
| `/plan/:plan_id` | `/growth?view=plans&plan=:plan_id` |
| `/parent/setup` | `/me?panel=parent-access` |

When `/analysis-chat` has no analysis identifier, modern UI opens the Ask section with an analysis picker. Redirects use `replace` to avoid polluting browser history. Back navigation returns to the originating modern space when route state is available and otherwise uses the canonical parent.

## Responsive Layout System

### Breakpoints and Shared Rules

Retain the project's established breakpoints: phone `375px`, tablet `768px`, iPad `1024px`, web `1280px`, and wide `1440px`. Component layout behavior is defined by available space rather than device names wherever practical.

- Maintain one semantic page tree and rearrange it responsively; do not create three separate page implementations.
- Minimum touch target is `44px`; child-mode primary targets are at least `56px`.
- Apply top and bottom safe-area insets for standalone PWA display.
- Page title, back behavior, and primary action follow shared shell contracts rather than page-local headers.
- Prevent horizontal page overflow at every supported width.
- Phone modal interactions become bottom sheets; tablet and desktop use a centered dialog or right drawer according to task context.
- Dense tables become prioritized cards or horizontally contained data regions on narrow screens, never page-wide overflow.

### Phone and PWA

- Use a compact top bar for page identity, time-theme indication, and one page-level action.
- Use a safe-area-aware fixed bottom island dock.
- Arrange Home, Growth, and Me around a raised central Start Review action; Home remains the leftmost destination and Me the rightmost.
- Give the central action a persistent text label, not an icon alone.
- Use single-column content, horizontally scrollable section tabs with visible focus states, and contextual bottom sheets.
- Restore unfinished review and upload state after app relaunch.
- Ensure installed standalone mode does not place controls under browser or OS chrome.

### iPad

- Portrait uses the bottom island dock and upgrades compatible content to a primary/secondary two-column layout.
- Landscape uses a compact left island rail and a main content area.
- Analysis Detail can show video/evidence and report content simultaneously.
- Filters, secondary navigation, and advanced settings open in drawers to preserve context.

### Desktop

- Use a fixed left Island Pier navigation with the four spaces, current skater, and a prominent Start Review action.
- Use the top bar only for breadcrumbs, current mode, page-level actions, and theme controls; do not repeat primary navigation.
- Use a 12-column content grid.
- Standard pages cap near `1280px`; Analysis Detail and advanced workspaces may expand to `1480px`.
- Growth and Analysis Detail use a main content region plus contextual side region when it improves comprehension.

## Visual System: Ice Island

The modern theme combines the reference library's warm, rounded natural language with IceBuddy-specific ice, snow, and skate-track motifs.

### Foundation

- Body and surfaces: warm cream and paper tones rather than clinical white.
- Text: deep tea brown for comfortable reading; technical panels may use a cooler dark neutral while remaining within the same system.
- Primary brand: island teal and mint.
- Primary action: warm yellow where a single action needs emphasis.
- Ice accent: clear sky blue and snow white.
- Data semantics: stable success, warning, error, and informational colors that do not change with time themes.
- Typography: Nunito for Latin and numerals, Noto Sans SC for Chinese, with tabular numerals for metrics.

### Time Themes

| Period | Atmosphere |
| --- | --- |
| Morning | peach sky, pale mint, warm cream |
| Daytime | sky blue, island teal, bright green |
| Sunset | coral orange, lavender, warm yellow |
| Night | deep ocean blue, moon white, muted mint |

Automatic mode follows local time. Users may pin any period. Time themes change environmental background, illustration, and atmosphere tokens only. Text contrast and semantic data colors stay stable. Theme selection is stored locally and must not flash the wrong theme during startup.

### Reference Components

Prefer adapting the reference library's Button, Card, Tabs, Drawer, Notification, Progress, Tag, Tooltip, and Divider patterns. Preserve its recognizable rounded geometry, dotted card pattern, swallowtail title, tactile button press, pill tags, striped progress, and speech-bubble feedback where appropriate.

Redesign navigation, island map, data charts, video workspaces, and analysis layouts specifically for IceBuddy. Do not use the full Nook Phone shell or custom game cursor because they reduce responsive usability. Item PNG and phone-style SVG assets may appear as decorative badges, child-mode rewards, and empty-state illustrations, but never as the sole indicator of meaning.

## Child and Parent Modes

Both modes use identical route hierarchy, page regions, section names, and responsive behavior.

Child mode:

- uses larger cards and targets;
- uses shorter, encouraging copy;
- emphasizes island-map discovery, rewards, and one next action;
- hides technical evidence and advanced actions behind parent access.

Parent mode:

- increases information density within the same regions;
- exposes filters, quality context, evidence explanations, retry controls, and family management;
- maintains the same warm Ice Island visual language rather than reverting to the existing dark workstation shell.

Switching modes must preserve the current route, active analysis, active section, form state, and scroll context where possible.

## State, Offline, and Error Design

- Loading uses layout-preserving skeleton cards or a small island-weather status, not blank screens or unnecessary full-screen spinners.
- Analysis processing shows the active stage, completed stages, what happens next, whether the user may leave, and how to resume.
- Empty states provide one primary action and at most one explanatory secondary link.
- Offline mode identifies cached content and permits reading cached Home summary and recent reports. Upload, retry, provider changes, and other online mutations are disabled with a reason.
- Failures are classified as retryable, target-selection-required, parent-action-required, or advanced-diagnostics-only.
- PWA update prompts are non-blocking and never force a refresh during upload or analysis processing.
- Notifications use stable keys for long-running operations so progress updates replace an existing notice instead of producing a stack of duplicates.

## Component and Code Boundaries

Implementation should create modern-only primitives and shells rather than layering more global CSS overrides onto classic components.

- `ModernAppShell`: responsive navigation, top bar, safe areas, theme atmosphere, and content frame.
- `ModernRouteBoundary`: classic-versus-modern route selection and legacy mapping.
- `IslandThemeProvider`: automatic/pinned period, persistence, startup hydration, and token application.
- `FamilyModePresentation`: disclosure and density policy without separate route trees.
- `ModernPageHeader`: consistent title, breadcrumb/back behavior, and page actions.
- `IslandDock` and `IslandRail`: phone and wide-screen representations of one navigation model.
- `SectionNav`: accessible in-space navigation for Growth and Analysis Detail.
- `ModernSurface` primitives: card, button, tag, progress, notice, dialog/sheet, empty state, and skeleton.
- Feature compositions: Today Island, Review Flow, Analysis Detail, Growth, Resident Services, and Advanced Tools.

Existing domain APIs and business behavior stay authoritative. The redesign composes existing feature logic behind new presentation boundaries; it must not duplicate analysis, growth, plan, or settings state models merely to support layout.

## Accessibility and Performance

- Every island-map destination has a semantic link counterpart.
- All controls have visible keyboard focus and useful accessible names.
- Color is never the only carrier of analysis state, score, or navigation selection.
- Text and essential controls meet WCAG AA contrast in all four time themes.
- Honor `prefers-reduced-motion`; disable ambient floating, map drift, animated stripes, and nonessential transitions.
- Lazy-load decorative maps and large asset groups. Do not ship the reference repository's complete 500-plus item image set to every client.
- Use responsive images and explicit dimensions to avoid layout shifts.
- Preserve useful content when decorative assets fail to load.

## Testing and Acceptance

### Automated Coverage

- route mapping tests cover every legacy route and preserve identifiers/query state;
- navigation tests verify exactly four primary spaces and correct active state;
- theme tests cover automatic period selection, manual pinning, persistence, and no startup flash contract;
- child/parent tests verify shared structure and correct disclosure;
- responsive component tests cover dock/rail selection, safe-area classes, and section behavior;
- workflow tests cover review resume, analysis section links, Growth deep links, parent-gated tools, offline mutations, and PWA update deferral;
- existing classic UI navigation and representative page tests remain passing.

### Manual Viewports

Verify at minimum:

- 320x568 and 375x812 phone browsers;
- installed iOS/Android-style standalone safe-area simulation;
- 768x1024 iPad portrait;
- 1024x768 iPad landscape;
- 1280x800 desktop;
- 1440x900 wide desktop.

### Product Acceptance

- No supported viewport has page-level horizontal overflow.
- The bottom dock and its raised review action clear device safe areas.
- Every common function is reachable within two navigation levels.
- Modern UI has one authoritative entry for each function.
- Child/parent switching preserves the current task and uses the same structure.
- Automatic and pinned themes retain readable text and stable semantic colors.
- Keyboard, screen reader, reduced-motion, and low-performance alternatives complete all core workflows.
- Classic UI has no intentional visual, navigation, or route behavior regression.
- Old links resolve to the correct modern state without losing IDs.
- Offline and interrupted analysis states explain what remains available and how to continue.

## Delivery Strategy

Implement in vertical, independently testable slices:

1. modern design tokens, time themes, attribution, and reusable surfaces;
2. responsive modern shell and four-space navigation;
3. route boundary and legacy compatibility;
4. Today Island and Resident Services;
5. continuous Review flow;
6. unified Analysis Detail;
7. unified Growth space;
8. advanced-tool consolidation, PWA/offline polish, accessibility, and full regression verification.

Each slice must leave classic UI working. Modern legacy redirects should ship only when their canonical destination is functional.

## Out of Scope

- Redesigning classic UI.
- Changing backend analysis algorithms or stored data contracts unless a minimal compatibility field is required for resume/offline presentation.
- Introducing official Nintendo assets, characters, trademarks, or music.
- Making the reference library or IceBuddy available for commercial use.
- Rebuilding every technical tool from scratch; advanced tools are consolidated and restyled before deeper tool-specific redesign.

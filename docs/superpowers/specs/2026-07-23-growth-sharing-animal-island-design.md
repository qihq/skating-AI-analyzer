# Growth and Sharing Animal Island Design

## Goal

Repair annual PDF export, replace invalid parameter dead ends in growth plans and comparisons, and unify parent verification, generation controls, and every share workflow under the responsive Animal Island interface.

## Functional Design

- The all-in-one image installs and verifies `reportlab` and `pypdf`; annual export failures preserve actionable dependency details.
- `/growth?view=plans` is a plan hub. It lists existing plans, offers an empty state and report-based generation path, and opens `/plan/:plan_id` only with a real identifier.
- `/growth?view=compare` is a comparison launcher. It selects two completed analyses for one skater and opens persisted results; parameterized routes remain result/detail routes.
- Parent PIN prompts share one Animal Island modal treatment with keyboard-safe mobile layout, clear validation, loading, error, and close states.
- Generate, regenerate, retry, share, and download controls use shared island button variants and a restrained leaf loading motion that honors reduced-motion preferences.

## Sharing Design

- A shared Animal Island share dialog owns preview, copy, native share, download, safe-area layout, and responsive actions.
- Report, progress, follow-up, milestone, training plan, comparison, and monthly chapter shares create one width-stable, height-adaptive poster. Text measurement determines poster height so content is not clipped.
- Posters use the existing Animal Island leaf/map/camera/miles/design assets, cream paper surfaces, teal ribbons, grass texture, sea, and tree-line artwork.
- Annual sharing creates a compact cover summary with year, skater, included months, milestone count, and highlights. It shares the generated PDF as a file when supported and falls back to PDF download, summary copy, and cover download.
- Heavy poster rendering modules are loaded only after the user invokes sharing.

## Responsive Design

- Phone: full-width scrollable dialog, sticky safe-area action footer, single-column preview.
- Tablet: preview and actions use a balanced two-column layout when space permits.
- Desktop: centered preview with a compact side action rail.
- Long content scrolls inside the viewport while generated poster height remains content-driven.

## Error Handling

- Missing PDF dependencies report which modules are unavailable and keep retry available.
- Empty plan and comparison hubs explain the required next action instead of emitting invalid-ID errors.
- Share capability degradation never blocks download or text copy.
- Generation failures retain the current plan/result and show an inline island notice.

## Verification

- Backend annual PDF and export-route tests.
- Frontend route-hub, modal, share-height, annual-file-share, and page integration tests.
- Full frontend test/build and focused backend tests.
- Browser validation at 375x812, 768x1024, 1024x768, and 1440x900 for core flows and share dialogs.


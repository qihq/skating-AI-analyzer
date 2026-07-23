export type AnalysisView = "summary" | "moments" | "body" | "ask" | "more";

const ANALYSIS_VIEWS = new Set<AnalysisView>(["summary", "moments", "body", "ask", "more"]);

const LEGACY_WORKSPACE_VIEWS: Record<string, AnalysisView> = {
  evidence: "moments",
  pose: "body",
  followup: "ask",
  diagnostics: "more",
};

export function resolveAnalysisView({
  initialView,
  view,
  legacyTab,
}: {
  initialView?: AnalysisView;
  view?: string | null;
  legacyTab?: string | null;
}): AnalysisView {
  if (initialView) return initialView;
  if (view && ANALYSIS_VIEWS.has(view as AnalysisView)) return view as AnalysisView;
  if (legacyTab && LEGACY_WORKSPACE_VIEWS[legacyTab]) return LEGACY_WORKSPACE_VIEWS[legacyTab];
  return "summary";
}

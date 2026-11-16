"""Shared observation exclusions; independent of candidate detection."""
EXCLUDED_TRACKING_STATES = {"lost", "interpolated", "low_confidence"}
EXCLUDED_TRACKER_STATES = {
    "full_frame_yolo_relock_pending",
    "local_zoom_yolo_relock_pending",
    "relock_pending",
    "detector_relocked",
    "relocked",
    "continuity_rejected",
    "relock_rejected",
    "lost_reused",
}

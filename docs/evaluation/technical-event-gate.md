# Technical Event Timeline Gate

Checked on 2026-07-23 while implementing P2-A.

P2-B is blocked. The repository contains the G3/G4 target definitions in the
high-accuracy plans, but no committed acceptance reports with measured
candidate recall, specialty macro F1, high-confidence error, T/A/L timing,
coverage, uncertainty rate, pipeline version, and frozen-test hash.

Do not implement or enable the full-video technical event timeline until those
reports exist and each action profile (jump, spin, step interval, held pose)
has measured acceptance. The current single action window is not full-video
coverage.

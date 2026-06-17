from __future__ import annotations


CURRENT_PIPELINE_VERSION = "v5.2.303"

# v1.1.1: Add manual target bbox lock and per-frame bbox tracking for pose extraction.
# v1.1.2: Pass effective sampling fps into biomechanics to correct slow-motion jump metrics.
# v1.1.3: Unwrap shoulder rotation angles before estimating jump rotation speed.
# v1.1.4: Retry transient AI provider failures and degrade vision/report output when AI is unavailable.
# v1.1.5: Add video prechecks and no-person target preview status before pose/LLM analysis.
# v1.1.6: Smooth pose keypoints with One-Euro filtering and interpolate short low-visibility gaps.
# v1.1.7: Add geometric jump subtype evidence for Lutz/Flip and inject it into vision prompts.
# v1.1.8: Add Qwen-VL native action-window video mode with frame-mode fallback.
# v1.1.9: Drive profile sampling density from config and protect motion peak neighborhoods.
# v1.1.10: Add frame-mode self-consistency voting and key-frame phase overrides.
# v1.1.11: Add multi-provider Qwen/Doubao vision voting and Doubao video slot validation.
# v5.0.0: Add Qwen 3.6 Plus video temporal localization, semantic keyframe arbitration, semantic FFmpeg extraction, image AI video_context, and video/image/MediaPipe report fusion.
# v5.1.0: Add Pose Debug replay page, responsive PWA-safe debug UI, and separate pose/YOLO runtime checks.
# v5.2.0: Align debug replay with the formal sampling pipeline and exclude unreliable pose frames from keyframe scoring.
# v5.2.302: Fail closed when manual target locks lack tracker diagnostics so pose backfills cannot redraw wrong-person skeletons.
# v5.2.303: Allow review uploads with only a broad action category and pass user comments into video-temporal action recognition.
# v5.2.301: Treat manual target selection as identity-authoritative by blocking automatic support-anchor recovery and blanking those poses.
# v5.2.300: Harden manual target locks by rejecting no-overlap initial target binding and same-ID recovery drift instead of switching skeleton identity.
# v5.2.299: Blank semantic Path B skeleton annotations under manual target lock so auxiliary vision prompts cannot inherit wrong-person pose.
# v5.2.298: Treat manual target locks as identity-authoritative in pose extraction; relock states are blanked instead of trusted.
# v5.2.297: Enforce manual target locks through tracker fallback and pose extraction so confirmed skaters cannot silently switch identities.
# v5.2.296: Keep zoomed multiperson background locks in manual review when same-anchor or dense moving competitor risk is present.
# v5.2.295: Keep motion-supported low-prominence apex plateaus from drifting to late COM minima in wide jump windows.
# v5.2.294: Let stable repeated video-backed non-jump history override weak mixed-action jump drift.
# v5.2.293: Stabilize repeated video-backed non-jump mixed-action profiles across step/spin/spiral drift.
# v5.2.292: Guard weak mixed-action jump drift with video-backed prior same-video non-jump history.
# v5.2.291: Auto-lock clear compact zoomed targets through dense other-frame competitors when same-frame target competition is absent.
# v5.2.290: Allow stable same-video jump history to preserve mixed-action jumps when current MiMo jump confidence is borderline but coherent.
# v5.2.289: Preserve mixed-action jump profile when current weak MiMo jump evidence is supported by stable same-video jump history.
# v5.2.288: Add foreground-context target-lock review reason diagnostics without relaxing manual-review safety gates.
# v5.2.287: Add zoomed multiperson target-lock review reason diagnostics without relaxing wrong-person safety gates.
# v5.2.286: Reuse clean valid MiMo video T/A/L over low-confidence late-pose-core candidate clusters to stabilize same-video jump keyframes.
# v5.2.285: Reject weak compressed late-pose-core skeleton fallback so unreliable jump clusters cannot own final T/A/L.
# v5.2.284: Report support-anchor handoff reuse separately from ordinary tracker loss.
# v5.2.283: Keep ByteTrack identity close to the target-lock support anchor immediately after support-anchor recovery.
# v5.2.282: Auto-lock high-support small zoomed multiperson targets when same-frame competition is absent.
# v5.2.281: Allow full-video MiMo jump T/A/L to override nearby weak late-pose-core skeleton clusters.
# v5.2.280: Promote full-video MiMo jump T/A/L over nearby weak-geometry skeleton fallback clusters.
# v5.2.279: Auto-lock isolated high-confidence zoomed multiperson targets only when same-frame competitors stay safely distant.
# v5.2.278: Preserve current mixed-action video AI during semantic reuse and allow only stable video-backed non-jump profile reuse.
# v5.2.277: Block mixed-action jump recovery from hard-risk skeleton candidates so spin/step clips do not become T/A/L-missing jumps.
# v5.2.276: Flag tiny-target weak-geometry T/A/L candidates so distant skeleton drift is separated from trusted keyframe evidence.
# v5.2.275: Cap tiny or narrow target motion-only T/A/L fallback confidence so full-frame motion peaks stay low-trust.
# v5.2.274: Auto-lock stable sparse-background zoomed multiperson targets only when support is strong and competitors stay distant.
# v5.2.273: Keep strong skeleton mixed-action jumps from being downgraded by primary non-jump video AI; require coherent retry evidence.
# v5.2.272: Keep strong skeleton mixed-action jumps from being downgraded by medium-confidence non-jump video AI.
# v5.2.271: Auto-lock compact stable zoomed targets through two-frame background-person ambiguity when support is strong.
# v5.2.270: Auto-lock stable medium zoomed targets through only transient background-person ambiguity.
# v5.2.269: Keep dispersed small zoomed multiperson targets in manual review and add MiMo report-provider fallback/visibility.
# v5.2.268: Refine mixed-action tracker risk diagnostics so pending-only tiny targets do not masquerade as wrong-person relock failures.
# v5.2.267: Sync late-pose-core candidate fallback T/A/L into bio keyframes even when sampled-frame fallback flags remain.
# v5.2.266: Block phase-range visual T/A/L promotion after late-pose-core candidate conflict rejection.
# v5.2.265: Tighten late-pose-core semantic conflict tolerance so retry T/A/L must stay within the keyframe accuracy target.
# v5.2.264: Sync repaired late-pose-core skeleton fallback T/A/L back into bio keyframes after semantic rejection.
# v5.2.263: Allow repaired late-pose-core candidates to replace rejected semantic T/A/L instead of falling back to stale sampled frames.
# v5.2.262: Reject early semantic T/A/L when repaired late-pose-core candidates identify a later low-motion jump instance.
# v5.2.261: Reselect late low-motion pose-supported jump cores after rejected tail windows so early approach noise cannot own T/A/L.
# v5.2.260: Use core T/A/L confidence and tighter semantic motion windows when rejecting late unreliable-pose fallback candidates.
# v5.2.259: Reject low-confidence semantic jump T/A/L when unreliable-pose fallback candidates sit in a later stronger motion window.
# v5.2.258: Separate non-jump keyframe diagnostics and downgrade unclear-apex or early weak-landing jump candidates.
# v5.2.257: Allow nearby high-confidence wide-pose target-lock support anchors to recover tracker loss without accepting foreground scale jumps.
# v5.2.256: Clean legacy target-preview candidates that still combine background auto-lock allowed with manual-review gates.
# v5.2.255: Remove contradictory zoomed multiperson background auto-lock allowed flags when another manual-review gate overrides the lock.
# v5.2.254: Back off Mimo 429 completion retries with Retry-After support for safer batch analysis.
# v5.2.253: Downgrade weak mixed-action skeleton jump false positives when video AI rejects jump confidence.
# v5.2.252: Reuse stable same-video semantic phase keyframes for non-jump profiles.
# v5.2.251: Keep dense tiny zoomed multiperson target locks in manual review instead of background-auto locking.
# v5.2.250: Grace moderate terminal tracker loss after stable/support-anchor tracking and align batch diagnostics with recovered support anchors.
# v5.2.249: Let high-confidence non-jump video retry profiles override weak mixed-action skeleton jump inference.
# v5.2.248: Sync resolver-promoted visual T/A/L when long unresolved motion fallback is unsafe.
# v5.2.247: Persist resolver-confirmed mixed-action non-jump profiles before report generation.
# v5.2.246: Treat 自由滑/节目片段 batch uploads as mixed-action auto profile inference instead of forcing jump.
# v5.2.245: Keep bio-synced degraded same-video semantic reuse reliable through low-visibility weak-semantic final-loss validation.
# v5.2.244: Stabilize repeated low-confidence degraded semantic same-video T/A/L by reusing bio-synced prior timestamps over untrusted motion fallbacks.
# v5.2.243: Reuse prior degraded semantic low-visibility T/A/L for matching videos when current skeleton candidates are untrusted motion fallbacks.
# v5.2.242: Prefer compact motion-supported skater candidates over tall multiperson review risks while keeping manual review gates.
# v5.2.241: Keep ordered degraded semantic T/A/L in bio keyframes when skeleton candidates cannot be safely restored.
# v5.2.240: Use accepted target-lock support anchors as ByteTrack selection seeds and record rejected support-anchor diagnostics.
# v5.2.239: Feed target-lock support anchors into person tracking so distant selected skaters can recover without foreground relock drift.
# v5.2.238: Preserve accepted full-context semantic T/A/L after rejected retries instead of falling back to weak skeleton motion windows.
# v5.2.237: Reject long-lost moving relocks that scale from small distant targets into foreground person boxes.
# v5.2.236: Prefer supported narrow skater review candidates over wide partial foreground boxes in zoomed multiperson target locks.
# v5.2.235: Preserve semantic T/A/L through unreliable-pose weak skeleton conflicts and prefer foreground review candidates over tiny background locks.
# v5.2.234: Keep compressed weak-window reselection from jumping to early approach motion when the current main peak is comparable.
# v5.2.233: Mark compressed weak takeoff-apex skeleton candidates as weak temporal geometry even without late reselection.
# v5.2.232: Cap multi-signal weak-geometry T/A/L candidate confidence so unstable skeleton anchors stay low-trust.
# v5.2.231: Cap takeoff-anchor tail-window motion fallback confidence so drifted late motion peaks remain low-trust diagnostics.
# v5.2.230: Reselect landing away from compressed weak apex gaps only when a later contact frame has stronger support.
# v5.2.229: Prefer clearly fuller zoomed body boxes over medium partial motion boxes while preserving multiperson manual-review gates.
# v5.2.228: Cap early weak-geometry motion-window T/A/L candidates when later motion support suggests the selected window is approach noise.
# v5.2.227: Try same-frame detector relock after continuity rejects a wrong confirmed track when another detector box matches the target.
# v5.2.226: Auto-lock strong foreground targets through brief background-only zoomed multiperson ambiguity.
# v5.2.225: Ignore highly overlapping duplicate body boxes in zoomed multiperson target-lock checks.
# v5.2.224: Auto-lock strong foreground skaters when zoomed multiperson competitors are only tiny background detections.
# v5.2.223: Treat early-takeoff semantic candidate conflicts as unreliable for bio sync and same-video reuse.
# v5.2.222: Retry early semantic takeoff timestamps when a high-confidence ordered candidate core still supports a later takeoff.
# v5.2.221: Prefer early landing contact on low-tail takeoff-anchor motion fallback plateaus.
# v5.2.220: Preserve moderate-confidence semantic T/A/L when early approach motion peaks contaminate drifted takeoff-anchor candidates.
# v5.2.219: Keep small moving zoomed multiperson locks in manual review when motion support is weak or competitor load is high.
# v5.2.218: Preserve semantic T/A/L when main motion supports video timing over early weak-geometry skeleton candidates.
# v5.2.217: Keep large moving zoomed multiperson locks in manual review instead of background-auto locking.
# v5.2.216: Preserve accepted source candidate-conflict context when reusing same-video semantic T/A/L.
# v5.2.215: Preserve video T/A/L when low-precision takeoff-anchor candidates are phase-shifted with L near semantic takeoff.
# v5.2.214: Preserve high-confidence video T/A/L when early approach motion windows contaminate low-precision takeoff-anchor candidates.
# v5.2.213: Retry core analysis JSON saves under transient SQLite locks and bound batch API submissions during local full-video coverage.
# v5.2.212: Mark late low-motion landing candidates with no knee absorption as unreliable temporal geometry.
# v5.2.1: Tighten jump action-window padding and anchor target preview on high-motion sampled frames.
# v5.2.2: Preserve tracker-aligned crop poses during fast target motion instead of over-penalizing seed-bbox drift.
# v5.2.3: Let pose extraction use unconfirmed-but-gated tracker relock boxes as crop hints without switching target identity.
# v5.2.4: Keep ordered visible T/A/L candidates complete while preserving low-confidence keyframe warnings.
# v5.2.5: Validate regular pose crops against their actual reference bbox when motion-predicted crops are also attempted.
# v5.2.6: Reuse overlap-safe continuity-rejected tracker boxes as pose crop hints without accepting target identity changes.
# v5.2.7: Apply tracker-style crop padding to overlap-safe rejected tracker hints even when they become the reference bbox.
# v5.2.8: Treat reused lost tracker boxes as padded pose crop hints for distant tiny skaters.
# v5.2.9: Recover malformed Path A JSON and ground report issues/improvements in Path B evidence when Path A is unavailable.
# v5.2.10: Stop startup AI provider seeding so legacy duplicate provider rows cannot block container startup.
# v5.2.11: Use full video context by default, expose manual input windows, and require manual target selection for review-flagged multi-person locks.
# v5.2.211: Preserve reused semantic T/A/L when sparse-track stitched candidates own the later motion cluster.
# v5.2.210: Reuse stable same-video semantic T/A/L over sparse-track stitched skeleton candidate drift.
# v5.2.209: Recover unique full-body multi-pose skeletons when stale tracker boxes would otherwise reject them.
# v5.2.208: Reuse canonical same-video semantic T/A/L over low-visibility motion fallback drift.
# v5.2.207: Show semantic confidence and refinement metadata for synced bio keyframes in Compare.
# v5.2.206: Evaluate auto-eval keyframe order from final bio T/A/L before candidate evidence.
# v5.2.205: Sync accepted semantic T/A/L over contaminated low-visibility motion fallback candidates.
# v5.2.204: Flag multiperson relock instability and treat partial detector relocks as unreliable pose crops.
# v5.2.203: Estimate takeoff before sparse pre-apex motion clusters only when the selected sample is at the start of the active motion window.
# v5.2.202: Reselect away from compressed weak motion windows and keep weak-contact landing candidates near the apex instead of late timing-zero glide frames.
# v5.2.201: Restore dense tail-excluded bounded motion fallback T/A/L into bio keyframes when sampled semantic fallback would otherwise clear complete candidate frames.
# v5.2.200: Use dense motion-score timestamps after rejecting contaminated tail windows so low-precision fallback candidates are less limited by sparse sampled frames.
# v5.2.199: Exclude rejected compressed tail-motion windows from fallback keyframe selection so late full-frame motion spikes do not replace the jump core.
# v5.2.198: Surface tiny-target low-pose-tracking risk so distant skater locks are diagnosed separately from wrong-person relocks.
# v5.2.197: Mark compressed low-motion tail-window T/A/L candidates as untrusted without reselecting to unrelated early motion.
# v5.2.196: Recover low-confidence T/A/L timing from occluded main motion peaks when tracker protection would otherwise drift candidates into post-relock glide.
# v5.2.195: Extend foreground height-growth tracking rejection to wide-video child-skater frames.
# v5.2.194: Reject unanchored tall same-track foreground growth and clear stale detector relock confirmations after recovered tracking.
# v5.2.193: Preserve motion-aligned retry T/A/L over weak temporal skeleton candidates when tail-motion rejection passes visibility gates.
# v5.2.192: Keep semantic T/A/L when a stronger motion window is attached to weak-geometry skeleton candidates with adequate semantic support.
# v5.2.191: Attach semantic-vs-candidate T/A/L conflict evidence to ignored weak motion windows so batch diagnostics can separate full-frame motion peaks from target keyframe drift.
# v5.2.190: Require clearly stronger support before a fuller zoomed body box can replace a tiny target lock with higher same-frame competitor risk.
# v5.2.189: Prefer supported fuller zoomed skater boxes over over-tight partial tiny target-lock boxes while preserving foreground gates.
# v5.2.188: Confirm same-track small-body shape recovery through area-plus-aspect continuity rejections before declaring target loss.
# v5.2.187: Reuse foreground-occlusion-repaired same-video T/A/L only when current pose-supported candidates confirm the same timing.
# v5.2.186: Reuse stable same-video semantic keyframes by querying matching video hashes beyond the recent same-action window.
# v5.2.185: Roll back phase-range late reanchors when foreground occlusion proves the reanchored core frames are not visible.
# v5.2.184: Preserve accepted visible phase-range T/A/L after rejected quality retries and keep semantic effective source in sync.
# v5.2.183: Promote visible phase-range T/A/L over weak foreground-contaminated geometry candidates and repair distant occluded takeoff frames with zoomed visibility checks.
# v5.2.182: Reanchor late phase-range T/A/L after compressed candidate windows instead of syncing late glide drift.
# v5.2.181: Preserve retry T/A/L with weak phase confidence when current skeleton candidates are compressed and early motion peaks belong to approach.
# v5.2.180: Separate relock-reference pose crops from pending relock identity and reject core-center drift during unconfirmed relock states.
# v5.2.179: Tighten small-target pose validation so oversized foreground keypoint spreads and unconfirmed multi-pose relock hints are rejected.
# v5.2.178: Validate pending tracker relock pose crops against the existing target reference before allowing them to drive skeleton extraction.
# v5.2.177: Block final weak takeoff-apex skeleton fallbacks from restoring obscured or compressed T/A/L keyframes.
# v5.2.176: Keep zoomed multi-person target locks in manual review when a smaller high-support motion competitor matches the selected target evidence.
# v5.2.175: Restore bounded motion-fallback T/A/L when semantic sampled-frame fallback is unreliable but candidate timing remains ordered and plausible.
# v5.2.174: Require landing contact to clear the apex and mark short weak apex-to-landing skeleton gaps as compressed unreliable evidence.
# v5.2.173: Reuse matching-video late-reanchored phase-range T/A/L through early approach motion peaks for repeat stability.
# v5.2.172: Preserve high-confidence visual T/A/L when an early approach motion peak contaminates drifted takeoff-anchor skeleton candidates.
# v5.2.171: Keep weak distant single-jump zoomed target locks in manual review when support confidence is too low for reliable skeleton tracking.
# v5.2.12: Sync legacy bio keyframes to semantic T/A/L, tighten T/A/L candidate timing, and avoid far-person relock after tracker loss.
# v5.2.13: Keep biomechanics keyframes when semantic T/A/L are rejected and sampled-frame fallback is used.
# v5.2.14: Treat manually confirmed review-flagged target locks as confirmed, and reject retry semantic T/A/L that still conflicts with skeleton or motion timing.
# v5.2.15: Keep biomechanics T/A/L when semantic T/A/L remains in unresolved skeleton or motion-cluster conflict after quality retry.
# v5.2.16: Restore legacy bio T/A/L from current biomechanics candidates when semantic T/A/L is downgraded after unresolved conflict.
# v5.2.17: Do not sync semantic T/A/L into bio keyframes when top-level resolved keyframes fell back to sampled frames.
# v5.2.18: Treat top-level fallback-to-sampled semantic keyframes as unreliable even when the same flag also appears in rejected retry diagnostics.
# v5.2.19: Use weak motion-cluster fallback for low-height jumps and reject over-compressed retry/refined T/A/L.
# v5.2.20: Isolate retry and partial-merge semantic frame artifacts until the replacement is accepted.
# v5.2.21: Downgrade unresolved retry semantic T/A/L conflicts to reliable motion-cluster fallback keyframes.
# v5.2.22: Sync bio keyframes from resolved motion-cluster fallback after unresolved semantic retry conflicts.
# v5.2.23: Treat extreme late retry semantic conflicts as weak motion-cluster fallback candidates.
# v5.2.24: Relax aspect-only tracker continuity for skating pose changes and avoid batch auto-confirming manual-review target locks.
# v5.2.25: Preserve target-preview manual-review flags in API responses and only batch-confirm true auto locks.
# v5.2.26: Fall back to takeoff-anchored motion T/A/L when unclear skeleton apex drifts into late glide.
# v5.2.27: Expose target-preview support diagnostics, avoid merging far zoomed fragments, and compare bio T/A/L instead of stale semantic selections.
# v5.2.28: Add target-preview trajectory and motion-anchor diagnostics without relaxing manual-review gates.
# v5.2.29: Report blocked target auto-lock candidates separately from confirmed auto locks.
# v5.2.30: Add zoomed multi-person competitor diagnostics to target previews and batch summaries.
# v5.2.31: Reject unresolved semantic T/A/L conflicts from trusted video timestamp usage.
# v5.2.32: Reject detector relock foreground scale explosions while preserving close target scale changes.
# v5.2.33: Sync Compare video alignment and batch summaries to final bio T/A/L instead of stale semantic/candidate timestamps.
# v5.2.34: Reject low-confidence late-shift semantic retries and weak tail-motion keyframe windows.
# v5.2.35: Downgrade weakly refined semantic T/A/L when they drift late against candidate keyframe evidence.
# v5.2.36: Avoid over-compressing keyframe candidates when only the apex gap, not landing geometry, suggests drift.
# v5.2.37: Reselect takeoff from later plausible pre-apex evidence when the first T candidate is too early.
# v5.2.38: Reject incomplete jump semantic T/A/L before syncing into biomechanics keyframes.
# v5.2.39: Downgrade semantic T/A/L when tracker remains unrecovered and biomechanics only has low-precision motion fallback.
# v5.2.40: Downgrade weakly refined semantic T/A/L when tracker ends unrecovered against weak biomechanics candidates.
# v5.2.41: Flag complete-but-weak T/A/L geometry and carry tracker-final-loss weak-candidate diagnostics into bio sync.
# v5.2.42: Exclude pose frames from T/A/L candidate scoring when person-tracker diagnostics mark relock pending or unrecovered.
# v5.2.43: Fall back to takeoff-anchored motion timing when unclear apex leaves only late weak landing geometry.
# v5.2.44: Let near-overlapping static ByteTrack candidates re-enter relock confirmation after detector recovery.
# v5.2.45: Reject semantic T/A/L when weak candidate context conflicts with video AI by large core-frame offsets.
# v5.2.60: Allow reuse of otherwise stable semantic T/A/L when only local refinement delta was rejected.
# v5.2.61: Require identity support for full-frame detector relock so adjacent people cannot preempt local target recovery.
# v5.2.62: Ignore skeleton/semantic conflicts from temporally implausible T/A/L geometry in full-context videos.
# v5.2.63: Trust semantic T/A/L through full-video motion-cluster noise when current skeleton candidates agree within a tight local window.
# v5.2.64: Apply the same tight skeleton-candidate support before coherent semantic T/A/L are rejected by resolver-level late motion.
# v5.2.65: Include skeleton candidate T/A/L instance anchors in video-temporal retry prompts for full-video multi-segment clips.
# v5.2.66: Keep ordered semantic T/A/L when local refinement rejects only a motion peak and current skeleton boundaries still support the same jump instance.
# v5.2.67: Treat compressed weak apex/landing geometry as takeoff-anchored low-precision motion fallback instead of a strong A/L skeleton anchor.
# v5.2.68: Reject semantic T/A/L that drift away from bounded motion-fallback candidates after tracker final loss.
# v5.2.69: Revalidate matching-video semantic reuse against current tracker-final-loss and candidate T/A/L evidence.
# v5.2.70: Tighten tracker-final-loss bounded motion fallback conflicts to reject shifted high-confidence semantic core edges.
# v5.2.71: Replace rejected semantic selected T/A/L with keyframe-candidate fallback records in resolved API output.
# v5.2.72: Revalidate re-extracted matching-video semantic T/A/L against current weak-candidate evidence and expose candidate-vs-semantic diagnostics.
# v5.2.73: Recover tracker continuity and relock from tiny partial target boxes back to history-supported full-body boxes.
# v5.2.74: Reject weak-geometry semantic T/A/L when current candidate windows have stronger motion support than the semantic window.
# v5.2.75: Refine sparse-pose takeoff candidates from supported motion records and prefer early landing candidates when all landing contact evidence is weak.
# v5.2.76: Let long-lost single-person detector relock finish confirmation after ByteTrack relock rejection without relaxing multi-person identity gates.
# v5.2.77: Recover continuity when a late small relock returns to a history-supported full-body skating box.
# v5.2.78: Reject semantic takeoff when A/L align but stronger candidate takeoff motion supports a single-key T correction.
# v5.2.79: Keep high-confidence full-video semantic T/A/L when weak early candidate windows only slightly beat semantic motion support.
# v5.2.80: Keep high-confidence full-context semantic T/A/L when weak early candidate windows belong to a separated motion segment.
# v5.2.81: Select the key-moment-matching jump phase group when full-context video AI returns multiple T/A/L segments.
# v5.2.82: Keep accepted original semantic T/A/L reliable when a later quality retry is rejected for its own skeleton conflict.
# v5.2.83: Downgrade sparse-track stitched T/A/L candidates so fragmented skeleton segments cannot overwrite semantic keyframes.
# v5.2.84: Downgrade original semantic T/A/L after retry rejection when unresolved candidate-window conflicts remain.
# v5.2.85: Reject unanchored tall foreground detector relocks after small-target loss.
# v5.2.86: Ignore occlusion-contaminated motion windows when tracker loss/relock peaks inflate weak T/A/L candidates.
# v5.2.88: Promote high-confidence phase-range video T/A/L over low-visibility motion fallback candidates.
# v5.2.170: Bound phase-range reanchor A/L offsets so extremely late AI phases return to the observed jump apex and landing window.
# v5.2.169: Let late phase-range reanchoring use skeleton-near pre-takeoff motion when AI mislabeled the true jump window as approach.
# v5.2.168: Reanchor late phase-range jump T/A/L to preparation motion peaks when weak skeleton candidates and approach motion would otherwise force sampled fallback.
# v5.2.167: Promote ordered phase-range T/A/L over takeoff-anchored low-visibility motion fallback boundaries when takeoff geometry is weak.
# v5.2.166: Allow stable background-only zoomed target locks with no same-frame selected-target competitor while preserving manual review for same-anchor ambiguity.
# v5.2.165: Retry transient SQLite write failures and make takeoff ranking favor joint extension plus COM ascent near reliable apexes.
# v5.2.164: Reuse overlap-safe rejected detector boxes as pose crop hints without accepting tracker identity changes.
# v5.2.163: Allow background-only multi-person zoomed locks when selected target support is strong and no same-frame selected-target competitor exists.
# v5.2.162: Allow strongly supported zoomed skater locks through unrelated background multi-person frames.
# v5.2.161: Mark compressed late-reselected takeoff-to-apex geometry as untrusted candidate evidence.
# v5.2.160: Preserve single weak T/A/L geometry flags and exclude low-precision takeoff-anchor or weak-landing candidates from trusted batch delta statistics.
# v5.2.159: Exclude sparse-track and weak-temporal-geometry T/A/L candidates from trusted batch delta statistics while preserving their raw diagnostic deltas.
# v5.2.158: Mark late takeoff-anchor motion fallbacks with low-visibility A/L tail windows as untrusted candidate evidence for batch diagnostics and semantic reuse.
# v5.2.157: Mark tiny-target low-visibility motion-only T/A/L fallbacks as full-frame foreground-motion risk so diagnostics and semantic reuse stop treating them as trusted current evidence.
# v5.2.156: Retry failed tiny pose crops with a minimum ROI so distant skaters get extra pixels without replacing legacy crop successes.
# v5.2.155: Use pixel-aspect geometry for long-lost stable small-body tracker reacquire on wide videos.
# v5.2.154: Let long-lost stable tiny skater tracks reacquire unique plausible small-body ByteTrack candidates without accepting foreground scale explosions.
# v5.2.153: Cap compressed motion-only fallback T/A/L windows so short local motion bursts stay weak evidence.
# v5.2.152: Prefer local motion-fallback T/A/L clusters and cap cross-segment peak stitching as low-confidence evidence.
# v5.2.151: Reuse accepted distant/phase-range visual T/A/L promotions for matching videos and keep them consistent through low-visibility fallback revalidation.
# v5.2.150: Promote visible distant full-context video T/A/L, including low-confidence partial core frames, over compressed low-visibility motion fallback after tracker final loss.
# v5.2.149: Promote distant full-context phase-range T/A/L over compressed low-visibility motion fallback after tracker final loss.
# v5.2.148: Reject unanchored tiny local-zoom detector relocks and require post-relock identity confirmation before foreground growth.
# v5.2.147: Reuse stable same-video semantic T/A/L over accepted takeoff-anchor motion fallback candidate conflicts.
# v5.2.146: Keep high-confidence full-context video T/A/L over late takeoff-anchor low-precision motion fallback windows.
# v5.2.145: Let fuller high-support aggregate zoomed targets beat near-foreground adults in multi-person skating previews.
# v5.2.144: Confirm same ByteTrack-id tiny partial to full-body tracker recovery before rejecting continuity on area ratio alone.
# v5.2.143: Reuse stable same-video semantic T/A/L over extreme long unresolved motion fallback candidates.
# v5.2.142: Accept moderate-confidence ordered video T/A/L over extreme long unresolved motion fallback candidates.
# v5.2.141: Preserve ordered video T/A/L when blended semantic frames are rejected by tail motion against long unresolved fallback candidates.
# v5.2.140: Promote ordered partial video T/A/L when long unresolved low-precision motion fallback candidates are rejected.
# v5.2.139: Promote phase-range video T/A/L over unusually long unresolved low-precision motion fallback candidates.
# v5.2.138: Cap sparse stitched T/A/L candidates when unreliable pose gaps bridge unclear apex to weak landing.
# v5.2.137: Let unique high-confidence small-body ByteTrack candidates recover late tracker loss without opening ambiguous relocks.
# v5.2.136: Rank matching-video semantic reuse by historical stability when current candidates have weak temporal geometry.
# v5.2.135: Keep matching-video semantic T/A/L through weak temporal-geometry candidate conflicts to reduce repeat AI drift.
# v5.2.134: Reselect takeoff with timing-aware late-candidate support while preserving drift and occlusion diagnostics.
# v5.2.133: Narrow aggregate zoomed target ranking to fuller or lower-drift tracks so stable fragments are not displaced.
# v5.2.132: Prefer aggregate fuller zoomed target locks over high-support body fragments while preserving manual review.
# v5.2.131: Bootstrap initial tiny target anchors to nearby plausible full-body detections without relaxing relock identity gates.
# v5.2.130: Align delta-rejected semantic takeoff to a pose-supported candidate when refinement and skeleton evidence agree.
# v5.2.129: Extend same-window low-visibility main-motion alignment when semantic takeoff lands before the current motion peak.
# v5.2.128: Align near phase-range semantic T/A/L to current low-visibility main-motion candidates when they share the same jump window.
# v5.2.127: Reject fresh semantic T/A/L when overlapping windows hide weak local T/A support before the current main-motion peak.
# v5.2.126: Reject reused semantic T/A/L when a near current main-motion peak supports eligible low-visibility fallback candidates.
# v5.2.125: Grace short terminal tracker loss after stable history so high-coverage tails do not masquerade as unrecovered target failures.
# v5.2.124: Cap compressed or weak temporal-geometry T/A/L candidate confidence so implausible skeleton windows cannot masquerade as strong anchors.
# v5.2.123: Sync bio T/A/L from semantic selections when tracker-final-loss motion fallback was explicitly ignored by semantic validation.
# v5.2.122: Suppress report-issue churn in same-video comparisons when T/A/L and score outputs are stable.
# v5.2.121: Mark and filter motion-fallback T/A/L from unreliable tracker states so foreground peaks cannot masquerade as strong current candidates.
# v5.2.120: Allow near-prediction detector relock through skating pose scale shrink while preserving identity and foreground gates.
# v5.2.119: Rank same-video semantic reuse by pose-supported current-candidate agreement or historical stability instead of newest-first.
# v5.2.118: Reuse stable same-video semantic T/A/L through separated low-visibility motion fallback when current candidates have no pose support.
# v5.2.117: Ignore weak semantic refinement conflicts against separated low-visibility motion fallback when candidate keyframes have no pose support.
# v5.2.116: Keep current full-video semantic T/A/L when separated low-visibility bounded motion fallback has no pose support.
# v5.2.115: Reject reused semantic T/A/L when current low-visibility fallback aligns with a separated dominant motion window and reused timestamps have weak motion support.
# v5.2.114: Allow local-zoom tracker relock to confirm tiny-target scale recovery into a nearby full-body box without relaxing full-frame foreground gates.
# v5.2.113: Bound unclear apex and weak-foot-contact landing selection to the main motion window so complete skeleton tracks do not drift A/L into glide-out.
# v5.2.112: Sync bio keyframes from reused same-video semantic T/A/L when current tracker-final-loss motion fallback is low-visibility foreground noise.
# v5.2.111: Reuse same-video semantic T/A/L through low-visibility bounded motion fallback so foreground motion peaks cannot destabilize repeat analyses.
# v5.2.110: Use short-lived SQLite connections and online backups so Windows bind-mounted Docker data remains readable during batch analysis.
# v5.2.109: Keep phase-range visual promotion diagnostics clean after refinement so tracker-final-loss fallback flags are not re-added.
# v5.2.108: Let visible phase-range video T/A/L promotion override stale tracker-final-loss low-visibility motion fallback rejection flags.
# v5.2.107: Preserve visible tracker-final-loss video T/A/L promotion when low-visibility bounded motion fallback drift was already rejected.
# v5.2.106: Deprioritize ambiguous moderate zoomed foreground candidates when a stable tiny motion-supported skater target is present.
# v5.2.105: Avoid per-connection SQLite WAL switching and default bind-mounted Docker data to DELETE journal mode.
# v5.2.104: Preserve reliable reused semantic T/A/L when current candidates are insufficient-pose low-visibility motion fallbacks.
# v5.2.103: Deprioritize large zoomed foreground target candidates when stable motion-supported small skater targets are present.
# v5.2.102: Keep complete semantic jump T/A/L when stronger skeleton motion evidence is an implausibly compressed candidate window.
# v5.2.101: Cap long-lost tracker prediction extrapolation so relock crops do not drift away from the last reliable target.
# v5.2.100: Add tracker rejected-candidate geometry diagnostics and aggregate rejection-reason summaries.
# v5.2.99: Prefer aggregate stable zoomed targets over same-anchor late decoys when target-lock evidence is otherwise close.
# v5.2.98: Anchor confirmed target-lock payloads to the selected candidate frame so tracker seeds match the selected bbox.
# v5.2.97: Prefer motion-supported stable zoomed skater target locks over higher-confidence low-support decoys in multi-person distant videos.
# v5.2.96: Reject low-visibility moderate semantic T/A/L that drift late from bounded low-precision motion-fallback candidates.
# v5.2.95: Reselect secondary jump motion windows after weak tail-window rejection so foreground/tail peaks cannot stitch T/A/L across unrelated segments.
# v5.2.94: Reject fresh semantic T/A/L that drift late when occlusion-contaminated candidate windows still have ordered current-instance support.
# v5.2.93: Reject reused matching-video semantic T/A/L when current full-video motion peaks support a separated earlier jump instance.
# v5.2.92: Recompute stitched tracker diagnostics so anchor-frame tracking does not inherit stale half-sequence final-loss flags.
# v5.2.91: Confirm stable high-confidence detector relock candidates after long target loss without trusting drifted prediction boxes.
# v5.2.90: Keep ordered semantic T/A/L when local refinement rejects against weak temporal candidate geometry.
# v5.2.89: Treat compressed core T/A/L candidate gaps as weak temporal geometry so semantic keyframes can override them.
# v5.2.87: Promote visible video T/A/L over low-visibility motion fallback when tracker ends unrecovered.
# v5.2.59: Reuse only stable semantic T/A/L sources, excluding repaired/retry-rejected/conflict-tainted results.
# v5.2.58: Reuse reliable semantic T/A/L for matching video hashes and re-extract current semantic frame artifacts.
# v5.2.57: Keep semantic T/A/L when the only motion-conflict peak is an ignored unreliable pose/tracker fallback.
# v5.2.56: Cap takeoff-anchor motion-fallback confidence when A/L came from excluded pose or tracker states.
# v5.2.55: Ignore retry motion-cluster conflicts when the cluster peak is the same unreliable pose/tracker fallback candidate.
# v5.2.54: Ignore takeoff-anchor motion-fallback candidate conflicts when the fallback keyframes came from excluded pose/tracker states.
# v5.2.53: Accept retry semantic T/A/L through bio sync when absent landing geometry marks the old bio candidate as false evidence.
# v5.2.52: Mark absent landing geometry as weak bio evidence and keep retry semantic T/A/L when that weak candidate is the only conflict.
# v5.2.51: Reject semantic T/A/L outside reliable pose bounds when tracker remains unrecovered after bounded motion fallback.
# v5.2.50: Allow tracker continuity to recover from partial person boxes back to full-body boxes and grace short terminal losses.
# v5.2.49: Reject semantic T/A/L that conflicts on core takeoff or landing with takeoff-anchor motion fallback.
# v5.2.48: Reject unstable semantic apexes when takeoff-anchor motion fallback already found a conflicting A frame.
# v5.2.47: Bound low-precision motion fallback to reliable pose coverage and avoid rejecting semantic T/A/L with tail-contaminated final-loss fallback.
# v5.2.46: Keep just-recovered tracker frames out of T/A/L scoring so late relocks cannot pull keyframes into glide-out.

# Overnight evidence disposition — Oct 25 checkpoint

Market diagnostics are not evidence of a market-beating model. Each family below is INSUFFICIENT_DATA under the requested protocol. `n=0` means qualifying paired PIT evaluations, not zero games in the source. Brier/log loss vs authenticated close, calibration slope/intercept/ECE, mean CLV, ROI at logged entry, and EV>=2% selection count are all unavailable/null, not zero.

| Family | Qualifying paired n | Blocker |
|---|---:|---|
| NFL moneyline | 0 | Attempt9 has no tie-mass ML contract; composite replay needs archived pregame context; paired entry/close provenance absent |
| NFL spread | 0 | Score-only seasonal refits lack independent probability calibration; historical source not a logged entry/close receipt |
| NFL total | 0 | Same probability and entry/close gaps; no inherited calibration for refitted weights |
| NFL player props | 0 | Schedule CSV has no player outcomes/features or multi-season paired prop closes; #2606's one-week consensus/best-Over export is insufficient |
| CFB SDV ML/spread/total | 0 | All training rows reconstructed NON-PIT, weather availability unproven, paired entry/close absent |
| CFB_OPPONENT_ADJUSTED_V1 ML/spread/total | 0 | Canonical replay not executed: no joined real kickoff/history/spread input; no paired entry/close. No fabricated spread to bypass project() gate |

#2384 composite-specific structural audit (source branch base e39b1bcccb1642dfe6ab00081b56871aacb2c4f1): NFL PRIORS=(22,13.5,13.7,1.5); context rating is round(clamp(mean recent margin * .12,-3,3),3); score_means adds ratings to 22 ± HFA/2, then actual injury/weather adjustments. Therefore, conditional on absent adjustments, total means are restricted to [38,50] and home margin means to [-4.5,7.5]. This algebraic range demonstrates the mechanism for limited team separation; it is not an executed historical composite evaluation, calibration result, or proof of the original all-underdog card's cause. Real injury/weather receipts must not be replaced by zeros and called PIT.

CFB schedules inspected at data:history/cfb/current-release/1325bfb62031e54c1b46023bd170ad455d38516e/cfb_history/schedules/2025/cfb_schedule_2025.csv.gz have actual dates/finals but no spread or odds fields. This resolves availability of schedule timestamps, NOT the missing canonical replay lines. #2603 is the next authentic historical archive candidate; 2022 is partial and modern seasons remain unconfirmed. Flat56 result remains only a comparator.

Next final checkpoint: exact-head CI and any newly delivered authentic source files, then final report by 9 AM CT. No model math, thresholds, promotions, or frozen artifacts changed. No merges. No claim of all requested evaluations being completed.

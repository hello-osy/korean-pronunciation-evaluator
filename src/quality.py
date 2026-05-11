from __future__ import annotations

"""Audio quality and forced-alignment confidence gates."""

import math

import numpy as np

from src.types import AlignmentConfidenceReport, AudioQualityReport, ForcedAlignmentResult


def analyze_audio_quality(audio: np.ndarray, sampling_rate: int) -> AudioQualityReport:
    duration_sec = len(audio) / float(sampling_rate) if sampling_rate else 0.0
    rms = float(np.sqrt(np.mean(np.square(audio)))) if audio.size else 0.0
    rms_db = 20.0 * math.log10(max(rms, 1e-8))
    clipping_ratio = float(np.mean(np.abs(audio) >= 0.995)) if audio.size else 1.0

    frame_size = max(1, int(sampling_rate * 0.02))
    frames = [audio[index:index + frame_size] for index in range(0, len(audio), frame_size)] or [audio]
    frame_energy = [float(np.sqrt(np.mean(np.square(frame)))) if len(frame) else 0.0 for frame in frames]
    silence_ratio = float(sum(1 for energy in frame_energy if energy < 0.02) / len(frame_energy)) if frame_energy else 1.0

    reasons: list[str] = []
    if duration_sec < 0.6:
        reasons.append("음성이 너무 짧습니다.")
    if rms_db < -35.0:
        reasons.append("입력 음량이 너무 낮습니다.")
    if silence_ratio > 0.85:
        reasons.append("무음 비율이 너무 높습니다.")
    if clipping_ratio > 0.08:
        reasons.append("입력 신호에 clipping이 많습니다.")

    return AudioQualityReport(
        passed=not reasons,
        duration_sec=duration_sec,
        rms_db=rms_db,
        silence_ratio=silence_ratio,
        clipping_ratio=clipping_ratio,
        reasons=reasons,
    )


def assess_alignment_confidence(result: ForcedAlignmentResult) -> AlignmentConfidenceReport:
    """
    Check whether frame-level forced alignment is reliable enough.

    The old version mostly relied on average token confidence.
    This version also checks:
    - low-confidence token ratio
    - very-low-confidence token ratio
    - minimum confidence
    - blank ratio
    - normalized log probability
    """

    reasons: list[str] = []

    confidences = [segment.confidence for segment in result.segments]
    token_count = max(1, len(confidences))

    min_token_confidence = min(confidences) if confidences else 0.0
    low_conf_count = sum(conf < 0.20 for conf in confidences)
    very_low_conf_count = sum(conf < 0.05 for conf in confidences)

    low_conf_ratio = low_conf_count / token_count
    very_low_conf_ratio = very_low_conf_count / token_count

    # 1. Coverage: most reference tokens should be placed on the timeline.
    if result.coverage < 0.90:
        reasons.append(
            f"정답 음소 대부분이 시간축에 안정적으로 배치되지 않았습니다. "
            f"coverage={result.coverage:.3f}"
        )

    # 2. Average token confidence should not be too low.
    if result.avg_token_confidence < 0.45:
        reasons.append(
            f"정렬 경로의 평균 음소 신뢰도가 낮습니다. "
            f"avg_token_confidence={result.avg_token_confidence:.3f}"
        )

    # 3. Too many weakly aligned tokens means forced alignment is not stable.
    if low_conf_ratio > 0.30:
        reasons.append(
            f"신뢰도 0.20 미만 음소 비율이 높습니다. "
            f"low_conf_ratio={low_conf_ratio:.3f}"
        )

    # 4. Very low confidence tokens are especially suspicious.
    if very_low_conf_ratio > 0.15:
        reasons.append(
            f"신뢰도 0.05 미만 음소 비율이 높습니다. "
            f"very_low_conf_ratio={very_low_conf_ratio:.3f}"
        )

    # 5. If there are many tokens and at least one token is almost impossible,
    # reject. For very short utterances, do not overreact to a single token.
    if len(confidences) >= 10 and min_token_confidence < 0.005:
        reasons.append(
            f"일부 음소의 forced alignment confidence가 지나치게 낮습니다. "
            f"min_token_confidence={min_token_confidence:.6f}"
        )

    # 6. Overall CTC path probability.
    # The previous -4.5 was too loose for this use case.
    if result.normalized_log_prob < -1.50:
        reasons.append(
            f"전체 정렬 경로의 로그확률이 낮습니다. "
            f"normalized_log_prob={result.normalized_log_prob:.3f}"
        )

    # 7. If almost all frames are blank, phone-level timing is unreliable.
    if result.blank_ratio > 0.97:
        reasons.append(
            f"blank frame 비율이 너무 높습니다. "
            f"blank_ratio={result.blank_ratio:.3f}"
        )

    message = (
        "forced alignment를 신뢰할 수 있습니다."
        if not reasons
        else " ".join(reasons)
    )

    return AlignmentConfidenceReport(
        passed=not reasons,
        avg_token_confidence=result.avg_token_confidence,
        coverage=result.coverage,
        normalized_log_prob=result.normalized_log_prob,
        message=message,
    )
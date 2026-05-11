from __future__ import annotations

import csv
import json
import traceback
from pathlib import Path
from datetime import datetime

from pronunciation_backend_pipeline import evaluate_pronunciation_file


# =========================
# 경로 설정
# =========================

LABEL_DIR = Path(r"C:\OSYSTUDY\260429\Sample\label_speech_RU")
SOUND_DIR = Path(r"C:\OSYSTUDY\260429\Sample\sound_speech_RU")

OUT_DIR = Path("batch_eval_results")
OUT_DIR.mkdir(parents=True, exist_ok=True)

RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
CSV_PATH = OUT_DIR / f"batch_result_{RUN_ID}.csv"
JSONL_PATH = OUT_DIR / f"batch_result_{RUN_ID}.jsonl"


# =========================
# 유틸 함수
# =========================

def load_orthographic(json_path: Path) -> str:
    """JSON 파일에서 정답 문장 orthographic 추출"""
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    try:
        text = data["RecordingMetadata"]["orthographic"]
    except KeyError as e:
        raise KeyError(f"{json_path.name} 안에서 RecordingMetadata.orthographic을 찾지 못했습니다.") from e

    if not text or not text.strip():
        raise ValueError(f"{json_path.name}의 orthographic이 비어 있습니다.")

    return text.strip()


def get_sound_id(json_path: Path) -> str | None:
    """JSON 파일에서 sound_id 추출"""
    try:
        with json_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return str(data.get("sound_id", "")).strip() or None
    except Exception:
        return None


def find_audio_file(json_path: Path) -> Path | None:
    """
    JSON에 대응되는 음성 파일 찾기.

    우선순위:
    1. JSON 파일명과 같은 stem의 wav/mp3/flac/m4a
       ex) 00020-F-93-RU-A-ATQ012-0001023.json
           00020-F-93-RU-A-ATQ012-0001023.wav

    2. JSON 안의 sound_id 포함 파일
       ex) sound_id = 0001023
           *0001023*.wav

    3. JSON 파일 stem 일부가 포함된 파일
    """
    audio_exts = [".wav", ".mp3", ".flac", ".m4a", ".ogg"]

    # 1. 같은 stem 우선 탐색
    for ext in audio_exts:
        candidate = SOUND_DIR / f"{json_path.stem}{ext}"
        if candidate.exists():
            return candidate

    # 2. sound_id 기반 탐색
    sound_id = get_sound_id(json_path)
    if sound_id:
        for ext in audio_exts:
            matches = sorted(SOUND_DIR.glob(f"*{sound_id}*{ext}"))
            if matches:
                return matches[0]

    # 3. stem 포함 탐색
    for ext in audio_exts:
        matches = sorted(SOUND_DIR.glob(f"*{json_path.stem}*{ext}"))
        if matches:
            return matches[0]

    return None


def safe_get(d: dict, keys: list[str], default=None):
    """중첩 dict 안전 접근"""
    cur = d
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


# =========================
# 메인 실행
# =========================

def main(limit: int | None = None):
    json_files = sorted(LABEL_DIR.glob("*.json"))

    if limit is not None:
        json_files = json_files[:limit]

    print(f"[INFO] label json 개수: {len(json_files)}")
    print(f"[INFO] LABEL_DIR = {LABEL_DIR}")
    print(f"[INFO] SOUND_DIR = {SOUND_DIR}")
    print(f"[INFO] CSV 저장 위치 = {CSV_PATH}")
    print(f"[INFO] JSONL 저장 위치 = {JSONL_PATH}")

    fieldnames = [
        "index",
        "json_file",
        "audio_file",
        "reference_text",
        "status",
        "overall",
        "consonant",
        "vowel",
        "coda",
        "fluency_like",
        "audio_quality_passed",
        "coarse_token_alignment_passed",
        "alignment_confidence_passed",
        "artifact_dir",
        "error",
    ]

    total = len(json_files)
    success_count = 0
    fail_count = 0
    missing_audio_count = 0

    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as csv_f, \
         JSONL_PATH.open("w", encoding="utf-8") as jsonl_f:

        writer = csv.DictWriter(csv_f, fieldnames=fieldnames)
        writer.writeheader()

        for idx, json_path in enumerate(json_files, start=1):
            print("\n" + "=" * 80)
            print(f"[{idx}/{total}] {json_path.name}")

            row = {
                "index": idx,
                "json_file": str(json_path),
                "audio_file": "",
                "reference_text": "",
                "status": "",
                "overall": "",
                "consonant": "",
                "vowel": "",
                "coda": "",
                "fluency_like": "",
                "audio_quality_passed": "",
                "coarse_token_alignment_passed": "",
                "alignment_confidence_passed": "",
                "artifact_dir": "",
                "error": "",
            }

            try:
                reference_text = load_orthographic(json_path)
                audio_path = find_audio_file(json_path)

                row["reference_text"] = reference_text

                if audio_path is None:
                    missing_audio_count += 1
                    row["error"] = "matching audio file not found"
                    print(f"[WARN] 대응되는 음성 파일 없음: {json_path.name}")
                    writer.writerow(row)
                    jsonl_f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    jsonl_f.flush()
                    continue

                row["audio_file"] = str(audio_path)

                print(f"[TEXT] {reference_text}")
                print(f"[AUDIO] {audio_path.name}")

                result = evaluate_pronunciation_file(
                    audio_path=str(audio_path),
                    reference_text=reference_text,
                )

                status = result.get("status", "")
                gates = result.get("gates", {})
                artifact_paths = result.get("artifact_paths", {})

                # score 위치는 payload 구조 변화에 대비해서 여러 경로를 안전하게 확인
                full_payload = result.get("full_payload", {})
                score = (
                    safe_get(full_payload, ["evaluation", "score_breakdown"], {})
                    or safe_get(result, ["evaluation", "score_breakdown"], {})
                    or {}
                )

                row["status"] = status
                row["overall"] = score.get("overall", "")
                row["consonant"] = score.get("consonant", "")
                row["vowel"] = score.get("vowel", "")
                row["coda"] = score.get("coda", "")
                row["fluency_like"] = score.get("fluency_like", "")

                row["audio_quality_passed"] = safe_get(gates, ["audio_quality_gate", "passed"], "")
                row["coarse_token_alignment_passed"] = safe_get(gates, ["coarse_token_alignment_gate", "passed"], "")
                row["alignment_confidence_passed"] = safe_get(gates, ["alignment_confidence_gate", "passed"], "")

                row["artifact_dir"] = (
                    artifact_paths.get("artifact_dir")
                    or artifact_paths.get("output_dir")
                    or ""
                )

                success_count += 1

                print(f"[RESULT] status={row['status']}, overall={row['overall']}")
                print(f"[GATES] audio={row['audio_quality_passed']}, coarse={row['coarse_token_alignment_passed']}, align_conf={row['alignment_confidence_passed']}")

                # CSV에는 요약만 저장
                writer.writerow(row)

                # JSONL에는 result 전체도 같이 저장
                jsonl_record = {
                    **row,
                    "result": result,
                }
                jsonl_f.write(json.dumps(jsonl_record, ensure_ascii=False) + "\n")
                jsonl_f.flush()

            except Exception as e:
                fail_count += 1
                row["error"] = f"{type(e).__name__}: {e}"
                print(f"[ERROR] {row['error']}")
                traceback.print_exc()

                writer.writerow(row)
                jsonl_f.write(json.dumps(row, ensure_ascii=False) + "\n")
                jsonl_f.flush()

    print("\n" + "=" * 80)
    print("[DONE] Batch evaluation finished")
    print(f"total          : {total}")
    print(f"success        : {success_count}")
    print(f"failed         : {fail_count}")
    print(f"missing audio  : {missing_audio_count}")
    print(f"csv            : {CSV_PATH}")
    print(f"jsonl          : {JSONL_PATH}")


if __name__ == "__main__":
    # 전체 실행
    main()

    # 테스트로 앞 5개만 돌리고 싶으면 위 main() 대신 아래 사용
    # main(limit=5)
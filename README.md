# Pronunciation Backend Pipeline Guide

`files_for_backend` 폴더만 전달받아 백엔드에서 사용하는 기준의 간단 설명서입니다.

## 데이터셋
https://www.notion.so/260512-35d4af7a2973801098a4f089aec92b3b?source=copy_link 이 링크에 러시아 화자의 한국어 발화 데이터가 있습니다


## 1. 환경 세팅 방법

`files_for_backend` 폴더 안에서 실행합니다.

```powershell
cd files_for_backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

PowerShell에서 activate가 막히면:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

설치 확인:

```powershell
python -c "from pronunciation_backend_pipeline import evaluate_pronunciation_file; print('import ok')"
```

간단 실행 테스트:

```powershell
python -c "from pronunciation_backend_pipeline import evaluate_pronunciation_file; r = evaluate_pronunciation_file(r'sample4.wav', '안녕하세요 저는 오상영입니다'); print(r['status']); print(r['gates']); print(r['artifact_paths'])"
```

주요 라이브러리:

- `transformers`, `torch`, `torchaudio`: 음성 phone recognizer 모델 추론
- `librosa`, `soundfile`: 음성 파일 로딩/전처리
- `numpy`: forced alignment 및 confidence 계산
- `regex`: IPA token 처리
- `IPAkor`: 기존 IPA 변환 호환용

## 2. 기능 흐름

입력:

- 사용자 음성 파일 경로
- 정답 한국어 문장

출력:

- 발음 피드백 LLM용 데이터
- 억양 분석용 데이터
- gate 통과 여부
- 저장된 JSON/음성 파일 경로

전체 흐름:

```text
audio_path + reference_text
-> evaluate_pronunciation_file() : 백엔드에서 호출하는 메인 함수. 전체 평가 실행, 저장, 최종 dict 반환
-> run_evaluation() : 실제 평가 파이프라인 실행. gate 실패 시 retry/discarded로 조기 반환
-> build_reference_stage() : 정답 문장을 발음형 후보와 기준 IPA로 변환
-> recognize_audio_stage() : 사용자 음성을 phone/IPA로 추정하고 frame logits/timestamp 보존
-> audio_quality_gate() : 음성이 너무 짧거나 무음에 가까운지 확인. 실패 시 retry
-> recognition_gate() : 사용자 음성에서 token sequence가 나왔는지 확인. 실패 시 retry
-> coarse_token_alignment_stage() : 정답 IPA 후보와 사용자 IPA를 token-level로 거칠게 정렬
-> coarse_token_alignment_gate() : 다른 문장을 읽은 경우를 걸러냄. 실패 시 retry
-> forced_alignment_stage() : 선택된 기준 IPA를 음성 시간축에 forced alignment
-> alignment_confidence_gate() : forced alignment 신뢰도 확인. 실패 시 discarded
-> scoring_and_error_stage() : 발음 점수, mismatch, 오류 유형 생성
-> make_ready_result() : 모든 gate 통과 시 ready 상태의 내부 결과 객체 생성
-> save_backend_artifacts() : artifacts/<시각>/에 JSON과 음성 파일 저장
-> build_backend_payload() : llm_feedback_input/prosody_input 포함 최종 API 반환 dict 생성
-> result dict : status, gates, llm_feedback_input, prosody_input, artifact_paths, full_payload 포함
```

백엔드에서 보통 호출할 함수:

```python
from pronunciation_backend_pipeline import evaluate_pronunciation_file

result = evaluate_pronunciation_file(
    audio_path="sample.wav",
    reference_text="안녕하세요 저는 오상영입니다",
)
```

### Gate 요약

```text
1. audio_quality_gate
   -> 음성이 너무 짧거나 무음이면 retry

2. coarse_token_alignment_gate
   -> 정답과 너무 다른 발화면 retry

3. alignment_confidence_gate
   -> forced alignment 신뢰도가 낮으면 discarded

3개 모두 통과
   -> ready, 점수/오류 분석 생성
```

## 3. evaluate_pronunciation_file()의 반환값에서 원하는 정보 찾는 방법

`evaluate_pronunciation_file()` 반환값은 dict입니다.

주요 key:

```python
result["status"]
result["gates"]
result["llm_feedback_input"]
result["prosody_input"]
result["artifact_paths"]
result["full_payload"]
```

### 발음 피드백 LLM용

사용할 위치:

```python
llm_input = result["llm_feedback_input"]
```

주요 필드:

- `reference_text`: 정답 문장
- `reference_pronunciation`: 기준 발음형
- `reference_ipa`: 기준 IPA
- `user_ipa`: 사용자 추정 IPA
- `score_breakdown`: 전체/자음/모음/받침 점수
- `mismatches`: 기준 IPA와 사용자 IPA의 차이
- `issues`: 오류 유형과 교정 힌트
- `gate_summary`: gate 통과 여부

권장 사용:

- `result["status"]["evaluation_status"] == "ready"`일 때만 최종 피드백 생성
- `retry`면 재녹음 안내
- `discarded`면 alignment 신뢰도 부족 안내

### 억양 분석용

사용할 위치:

```python
prosody_input = result["prosody_input"]
```

주요 필드:

- `audio_file_path`: 분석에 사용할 음성 파일 경로
- `reference_text`: 정답 문장
- `selected_reference_pronunciation`: 선택된 기준 발음형
- `selected_reference_ipa`: 선택된 기준 IPA
- `reference_phonemes`: 정답 음소 목록
- `phoneme_segments`: 사용자 음성에서 정렬된 음소별 시간 정보
- `alignment_confidence`: forced alignment 신뢰도
- `gate_summary`: gate 통과 여부

음소 시간 정보 위치:

```python
segments = result["prosody_input"]["phoneme_segments"]
```

`phoneme_segments` 예시:

```json
{
  "token": "tɕ",
  "label": "J",
  "start_time": 0.82,
  "end_time": 0.94,
  "duration": 0.12,
  "frame_start": 41,
  "frame_end": 46,
  "confidence": 0.73
}
```

권장 사용:

- `result["gates"]["alignment_confidence_gate"]["passed"] == true`일 때 억양 분석에 사용
- `confidence`가 낮은 음소 구간은 보수적으로 해석

### 저장 파일 위치

기본적으로 실행할 때마다 아래에 저장됩니다.

```text
artifacts/<시각>/
├─ <시각>.json
└─ <시각>.<원본확장자>
```

경로 확인:

```python
result["artifact_paths"]["artifact_dir"]
result["artifact_paths"]["json_path"]
result["artifact_paths"]["audio_path"]
```

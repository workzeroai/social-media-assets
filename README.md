# social-media-assets

## Purpose

Public media hosting repository for ChatGPT-generated social media assets.
Images stored here are referenced by their GitHub RAW URL from external
tools (e.g. Buffer) that require a direct, publicly accessible file URL.

## Path convention

```
threads/YYYY/MM/{post-slug}/{filename}
instagram/YYYY/MM/{post-slug}/{filename}
```

Example:

```
threads/2026/08/test-post/test-image.png
```

## Direct URL convention

```
https://raw.githubusercontent.com/workzeroai/social-media-assets/main/{path}
```

Example:

```
https://raw.githubusercontent.com/workzeroai/social-media-assets/main/threads/2026/08/test-post/test-image.png
```

## Notes / 주의사항

- 이 저장소는 **PUBLIC**이다.
- 비공개/민감 정보를 저장하지 않는다.
- social media publishing용 최종 이미지 파일만 저장한다.
- 이미지 파일명에는 secret, token, private identifier를 사용하지 않는다.

## Chunked upload (large binary reconstruction)

### 문제

ChatGPT UI에서 생성한 이미지를 GitHub MCP의 `create_file` / blob 생성 호출에
base64 전체를 한 번에 담아 전달하면, 큰 payload가 중간에서 잘려 이미지 하단이
회색으로 깨지는 문제가 있었다. GitHub/Buffer는 헤더만 보고 width/height는
정상 인식하지만 실제 픽셀 데이터는 truncated 상태다.

**따라서 이미지 전체 base64를 단일 MCP 호출로 전달하지 않는다.** 대신 작은
텍스트 chunk 여러 개로 나눠 업로드하고, GitHub Actions가 서버 측에서
재조립·검증한 뒤 최종 경로에 commit한다.

### 흐름

```
ChatGPT generated image
  → local image file
  → base64 encode
  → split into small chunks (8-16 KB base64 text each)
  → GitHub MCP create_file 여러 번 (_ingest/{upload_id}/chunk-NNNN.txt)
  → manifest.json 마지막 commit
  → GitHub Action (push trigger: _ingest/**/manifest.json)
  → chunk concatenate → base64 decode
  → byte size / SHA-256 / 이미지 decode / width·height 검증
  → 모두 통과 시 threads/... 최종 경로에 commit + _ingest 파일 정리
  → RAW URL
  → Buffer MCP → Threads Draft
```

### ChatGPT MCP Upload Procedure

1. 생성된 이미지 파일의 SHA-256, byte size, width/height를 계산한다.
2. 이미지를 base64로 encode한다.
3. base64 문자열을 8~16 KB 단위 chunk로 split한다.
4. `_ingest/{upload_id}/chunk-0001.txt`, `chunk-0002.txt`, ... 순서대로
   GitHub MCP `create_file`로 커밋한다 (파일당 별도 호출).
5. 모든 chunk 업로드가 끝난 뒤 `_ingest/{upload_id}/manifest.json`을
   생성/커밋한다 (아래 스키마 참고). 이 커밋이 GitHub Action의 트리거다.
6. GitHub Action(`reconstruct-media-upload.yml`) 실행 완료를 기다린다.
7. workflow 실행 결과가 success인지 확인한다.
8. 로그에서 `RAW_URL`, `SHA256`, `ACTUAL_BYTES`, `WIDTH`, `HEIGHT`를 확인한다.
9. 필요하면 RAW URL을 다시 다운로드해 SHA-256/크기를 재검증한다.
10. 아래 "Buffer에 전달하기 위한 안전 조건"을 모두 만족했을 때만 Buffer MCP
    `create_post`를 `saveToDraft: true`로 호출한다.

`upload_id` 예시: `20260814-threads-chatgpt-test-001`

`manifest.json` 스키마:

```json
{
  "version": 1,
  "upload_id": "20260814-threads-chatgpt-test-001",
  "target_path": "threads/2026/08/chatgpt-test-v3/image-b-v3.jpg",
  "mime_type": "image/jpeg",
  "expected_bytes": 241234,
  "expected_sha256": "abc123...",
  "expected_width": 1080,
  "expected_height": 1080,
  "chunk_count": 22
}
```

- chunk 파일은 UTF-8 plain text, base64 문자열 일부만 포함 (줄바꿈 없어도 됨).
- chunk_count와 manifest의 chunk 개수가 정확히 일치해야 한다.

### 검증 규칙

`scripts/reconstruct_media_upload.py`는 아래를 모두 통과해야 최종 파일을
저장한다. 하나라도 실패하면 파일을 저장하지 않고 Action이 실패 처리된다.

- `expected_bytes == actual_bytes`
- `expected_sha256 == actual_sha256`
- Pillow `Image.verify()` 및 `Image.load()` 모두 성공 (truncated 이미지 검출)
- `expected_width/height == actual_width/height`
- mime_type에 대응하는 이미지 format 일치
- JPEG의 경우 파일 끝 EOI marker(`FFD9`) 존재 여부 보조 검증

`ImageFile.LOAD_TRUNCATED_IMAGES = True` 같은 느슨한 옵션은 사용하지 않는다.

### 성공/실패 시 `_ingest` 처리

- 검증 성공: 최종 이미지 commit과 함께 `_ingest/{upload_id}/` 삭제 (같은 commit).
- 검증 실패: `_ingest/{upload_id}/`를 그대로 남겨 디버깅할 수 있게 한다.

### Buffer에 전달하기 위한 안전 조건

ChatGPT는 Buffer에 RAW URL을 전달하기 전에 아래를 모두 확인해야 한다.
하나라도 실패하면 Buffer Draft 생성을 금지한다.

- GitHub Action workflow가 success로 종료됨
- RAW URL이 인증 없이 HTTP 200을 반환함
- byte size가 검증됨 (`expected_bytes == actual_bytes`)
- SHA-256이 검증됨
- 이미지 decode가 검증됨 (truncated 아님)
- width/height가 검증됨

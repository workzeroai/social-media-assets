"""_ingest/{upload_id}/manifest.json 을 읽어 base64 chunk 파일들을 순서대로
재조립하고, byte size / SHA-256 / 이미지 decode / width·height 를 검증한 뒤
모두 통과한 경우에만 manifest의 target_path에 최종 이미지 파일을 저장한다.

검증에 하나라도 실패하면 최종 파일을 저장하지 않고 0이 아닌 종료 코드로
종료한다. ImageFile.LOAD_TRUNCATED_IMAGES 같은 느슨한 옵션은 사용하지 않는다
— truncated 이미지는 반드시 오류로 검출되어야 한다.

사용법:
    python reconstruct_media_upload.py <manifest.json 경로>
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import os
import sys
from pathlib import Path

from PIL import Image

MIME_TO_FORMAT = {
    "image/jpeg": "JPEG",
    "image/jpg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
    "image/gif": "GIF",
}

REQUIRED_MANIFEST_FIELDS = [
    "upload_id",
    "target_path",
    "mime_type",
    "expected_bytes",
    "expected_sha256",
    "expected_width",
    "expected_height",
    "chunk_count",
]


class VerificationError(Exception):
    """검증 실패. 메시지는 어떤 검증이 왜 실패했는지 명확히 설명해야 한다."""


def load_manifest(manifest_path: Path) -> dict:
    if not manifest_path.is_file():
        raise VerificationError(f"manifest 파일을 찾을 수 없습니다: {manifest_path}")

    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = json.load(f)

    missing = [field for field in REQUIRED_MANIFEST_FIELDS if field not in manifest]
    if missing:
        raise VerificationError(f"manifest에 필수 필드가 없습니다: {missing}")

    return manifest


def read_chunks(ingest_dir: Path, chunk_count: int) -> str:
    parts = []
    for i in range(1, chunk_count + 1):
        chunk_path = ingest_dir / f"chunk-{i:04d}.txt"
        if not chunk_path.is_file():
            raise VerificationError(
                f"chunk 파일이 없습니다 (missing chunk): {chunk_path.name} "
                f"({i}/{chunk_count})"
            )
        text = chunk_path.read_text(encoding="utf-8")
        parts.append("".join(text.split()))  # 줄바꿈/공백 제거 후 concatenate

    return "".join(parts)


def decode_base64(b64_text: str) -> bytes:
    try:
        return base64.b64decode(b64_text, validate=True)
    except binascii.Error as exc:
        raise VerificationError(f"base64 decode 실패 (invalid base64): {exc}") from exc


def verify_bytes(data: bytes, expected_bytes: int) -> None:
    if len(data) != expected_bytes:
        raise VerificationError(
            f"byte size mismatch: expected={expected_bytes} actual={len(data)}"
        )


def verify_sha256(data: bytes, expected_sha256: str) -> str:
    actual = hashlib.sha256(data).hexdigest()
    if actual.lower() != expected_sha256.lower():
        raise VerificationError(
            f"SHA-256 mismatch: expected={expected_sha256} actual={actual}"
        )
    return actual


def check_jpeg_eoi_marker(data: bytes) -> None:
    if not data.endswith(b"\xff\xd9"):
        raise VerificationError(
            "JPEG EOI marker(FFD9)가 파일 끝에 없습니다. truncated JPEG로 의심됩니다."
        )


def verify_image(
    data: bytes, expected_format: str, expected_width: int, expected_height: int
) -> tuple[str, int, int]:
    # 1차: verify() — 컨테이너 구조 무결성 검사. 호출 후 해당 파일 핸들은
    # 더 이상 사용할 수 없으므로(Pillow 제약) 아래에서 새로 연다.
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
    except Exception as exc:  # noqa: BLE001 - Pillow는 다양한 예외 타입을 던진다
        raise VerificationError(f"이미지 verify() 실패 (구조 손상 의심): {exc}") from exc

    # 2차: 픽셀 데이터까지 끝까지 decode 되는지 load()로 재검증.
    # LOAD_TRUNCATED_IMAGES를 켜지 않으므로 truncated 이미지는 여기서 예외가 난다.
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            actual_format = img.format
            actual_width, actual_height = img.size
    except Exception as exc:  # noqa: BLE001
        raise VerificationError(f"이미지 load() 실패 (truncated 의심): {exc}") from exc

    if actual_format != expected_format:
        raise VerificationError(
            f"이미지 format mismatch: expected={expected_format} actual={actual_format}"
        )

    if (actual_width, actual_height) != (expected_width, expected_height):
        raise VerificationError(
            "이미지 크기 mismatch: "
            f"expected={expected_width}x{expected_height} "
            f"actual={actual_width}x{actual_height}"
        )

    if expected_format == "JPEG":
        check_jpeg_eoi_marker(data)

    return actual_format, actual_width, actual_height


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: reconstruct_media_upload.py <manifest.json path>", file=sys.stderr)
        return 2

    manifest_path = Path(sys.argv[1])
    ingest_dir = manifest_path.parent

    try:
        manifest = load_manifest(manifest_path)

        mime_type = manifest["mime_type"]
        expected_format = MIME_TO_FORMAT.get(mime_type)
        if expected_format is None:
            raise VerificationError(f"지원하지 않는 mime_type 입니다: {mime_type}")

        b64_text = read_chunks(ingest_dir, int(manifest["chunk_count"]))
        data = decode_base64(b64_text)

        verify_bytes(data, int(manifest["expected_bytes"]))
        actual_sha256 = verify_sha256(data, manifest["expected_sha256"])

        actual_format, actual_width, actual_height = verify_image(
            data,
            expected_format,
            int(manifest["expected_width"]),
            int(manifest["expected_height"]),
        )
    except VerificationError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    # 모든 검증 통과 -> 최종 파일 저장
    target_path = Path(manifest["target_path"])
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(data)

    raw_url = (
        "https://raw.githubusercontent.com/workzeroai/social-media-assets/main/"
        + manifest["target_path"]
    )

    output_lines = [
        f"UPLOAD_ID={manifest['upload_id']}",
        f"TARGET_PATH={manifest['target_path']}",
        f"RAW_URL={raw_url}",
        f"ACTUAL_BYTES={len(data)}",
        f"SHA256={actual_sha256}",
        f"WIDTH={actual_width}",
        f"HEIGHT={actual_height}",
        f"FORMAT={actual_format}",
    ]
    for line in output_lines:
        print(line)

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            for line in output_lines:
                f.write(line + "\n")

    print(f"\n검증 완료: {manifest['upload_id']} -> {manifest['target_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

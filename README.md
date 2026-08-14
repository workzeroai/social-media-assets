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

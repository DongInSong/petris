<p align="center"><a href="README.md">English</a> · <b>한국어</b></p>

# 펫트리스

바이브코딩에 낡고 지친 마음을 달래주는 펫트리스.

화면 구석에서 혼자 테트리스를 둡니다. 키보드를 두드리면 블록이 빨라지고 점수가 오릅니다. 하루치 기록은 다이어리에 쌓입니다.

<p align="center"><img src="screenshot.png" width="200" alt="화면 구석에서 도는 펫트리스"></p>

Windows 전용.

## 설치

[릴리스](../../releases)에서 `Petris.exe`를 받아 더블클릭. SmartScreen 경고가 뜨면 "추가 정보" → "실행".

## 빌드

```
py -m pip install -r requirements.txt
py -m PyInstaller --clean --noconfirm Petris.spec
```

## 라이선스

MIT.

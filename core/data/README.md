# 证件照人脸检测模型

`face_detection_yunet_2023mar.onnx` 来自 OpenCV Zoo 的 YuNet 人脸检测模型。

- 项目：https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet
- 文件：`face_detection_yunet_2023mar.onnx`
- 用途：本项目中仅用于证件照自动构图，不上传、不联网。
- 许可证：MIT（以 OpenCV Zoo 上游声明为准）

如果模型文件缺失，程序会自动回退到 OpenCV 自带 Haar 人脸检测；再失败时按构图中心裁剪。


## U2-Netp 抠图模型

`u2netp.onnx` 来自 rembg 的公开模型发布：

- 发布页：https://github.com/danielgatis/rembg/releases/tag/v0.0.0
- 上游项目：https://github.com/xuebinqin/U-2-Net
- 用途：本地 AI 抠图 / 证件照换背景，不上传、不联网。
- 许可证：U-2-Net 为 Apache-2.0（以原项目声明为准）。

如果模型文件缺失，抠图会自动降级为颜色容差算法。


## Real-ESRGAN x4 超分模型

`realesrgan/model.onnx` 与 `realesrgan/model.data` 来自公开的 Real-ESRGAN ONNX 转换模型。

- 模型页：https://huggingface.co/TheGuy444/Real-ESRGAN-ONNX
- 上游项目：https://github.com/xinntao/Real-ESRGAN
- 用途：本地图片 2×/3×/4× 超分，不上传、不联网。
- 许可证：BSD-3-Clause（以 Real-ESRGAN 上游声明为准）。
- 输入固定为 128×128，程序会分块推理后拼接。

如果模型缺失，超分工具会自动降级为 Lanczos 插值 + 锐化。

## faster-whisper tiny 字幕模型

`faster-whisper-tiny/` 包含 CTranslate2 格式的 Whisper tiny 多语言模型。

- 模型页：https://huggingface.co/Systran/faster-whisper-tiny
- 上游项目：https://github.com/openai/whisper
- 用途：本地音视频转 SRT/TXT 字幕，不上传、不联网。
- 许可证：MIT（以 OpenAI Whisper 上游声明为准）。
- 推理依赖：`faster-whisper` + `ctranslate2` + `av`（见 requirements.txt）。

如果模型或依赖缺失，字幕工具会提示先运行 install.bat；不会自动把文件上传到云端。

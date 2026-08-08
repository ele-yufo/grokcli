# 媒体生成实操

权威参数以 `grokcli help image|video|tts|transcribe|voice` 为准。这里给模型选择与流程判断。

## 模型矩阵（live 以 `grokcli models` 为准）

| 用途 | 默认模型 | 备注 |
|------|---------|------|
| 对话 | `grok-4.5` | 500k 上下文；`--effort` 可调 |
| 图像 | `grok-imagine-image-quality` | `-r 1k/2k`，7 种宽高比 |
| 视频生成 | `grok-imagine-video-1.5` | T2V/I2V/R2V 三合一；T2V/I2V 原生 1080p |
| 视频编辑/延长 | `grok-imagine-video`（base） | **1.5 不接受这两个端点**（400） |
| TTS | （无模型 id） | `voice_id` + `language`；无 model 参数 |
| STT | （无模型 id） | multipart；无 model 参数 |

## 视频：模式与约束

| 模式 | 用法 | 约束 |
|------|------|------|
| T2V | `video "描述"` | 1-15s；480p/720p/1080p |
| I2V | `video "描述" -i 图` | 首帧动画；与 R2V 互斥 |
| R2V | `video "描述" --ref 图...` | 参考图 ≤7 张；**上限 720p** |
| R2V 配音 | `--ref-audio 音色`（≤3） | 提示词里用 `<AUDIO_0>` 标签指位；**非美国团队 403** |
| 延长 | `video-extend 视频 ["后续"]` | 追加段 2-10s（默认 6） |
| 编辑 | `video-edit 视频 "改动"` | 保持原长（≤~8.7s），720p |

流程：提交即返回 → 轮询渲染（客户端自动，spinner 显示进度 %）→ 下载到 `./grokcli-output/`（当前工作目录下）。**分钟级**，耐心等；结果路径在 stdout。

## 图像

- `image`：生成（默认 `grok-imagine-image-quality`）；`image-edit`：按提示改源图（默认 **quality** 模型，`-m grok-imagine-image` 可回退 fast），1-3 张源图（本地路径或 URL）。
- 源图上限按模型表驱动（`models.image_edit_max_sources`）：当前 API 全部 3 张；**Imagine Image 2.0**（2026-08-07 发布，消费端 Quality Mode，API 未上线）公布模型 id 后注册为 5 张 multi-ref——届时 CLI 零改动生效。
- 输出 `./grokcli-output/<时间戳>_<slug>.png`（当前工作目录下），路径打印在 stdout。

## 语音

- `tts`：`--voice` 内置音色（`voices` 看列表）或克隆音色 id；`--speed 0.7-1.5`、`--latency 0|1|2`、`--normalize`；**文本 ≤15000 字符**；`-f mp3|wav|pcm|mulaw|alaw`。
- `voice clone 音频 [--name ...]`：从 ≤120s 参考片段克隆音色，返回 8 位 `voice_id`，可作 `tts --voice`；`voice list/delete` 管理。**Enterprise + 美国限定**（403 时提示）。
- `transcribe`：WAV/MP3/OGG/FLAC/AAC/MP4/M4A/MKV；`--vad-threshold 0-1`（0 关）、`--diarize` 分说话人、`--keyterm` 关键术语（可重复）、`--language` 启用格式化。

## 成本与节奏

- 视频按秒计费（1.5 比 base 贵），订阅用户走 OAuth 不按 token 计费但视频任务仍消耗渲染配额。
- 批量/长任务前确认用户意图；视频任务一次一个（或明说并行）。

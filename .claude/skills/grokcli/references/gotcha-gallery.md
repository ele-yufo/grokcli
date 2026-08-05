# Gotcha 案例库

每个案例：反面写法 → 错在哪 → 正面写法 → 判断关键。

## Gotcha #1 — 凭记忆用旧模型 id

反面：`grokcli video ... -m grok-imagine-video-1.5-preview` 或 `grokcli transcribe x.mp3 -m grok-transcribe`

错在哪：上游模型迭代——1.5-preview 已转正为 `grok-imagine-video-1.5`（能力也变了：现在支持 R2V）；`grok-transcribe` 已退役（404）。旧 id 来自记忆或旧文档，不是 live 状态。

正面：先 `grokcli models` 看 live 列表；TTS/STT 根本没有模型 id，不传 `-m`。

判断关键：要用的模型 id 不是刚才 `grokcli models` 输出里的 → 先验证再传。

## Gotcha #2 — 给 video-edit / video-extend 传 1.5

反面：`grokcli video-edit clip.mp4 "..."`（默认模型是 1.5 时）→ HTTP 400 "Video editing is not supported for this model"

错在哪：`/videos/edits` 和 `/videos/extensions` 只由 base `grok-imagine-video` 服务；1.5 只做生成。默认已切 base，但显式 `-m grok-imagine-video-1.5` 会踩中。

正面：edits/extensions 不传 `-m`（默认 base）；或显式 `-m grok-imagine-video`。

判断关键：目标是"改/延长已有视频" → 用 base 模型。

## Gotcha #3 — 参考图超过 7 张

反面：`grokcli video "..." --ref a.png ... --ref h.png`（8 张）→ HTTP 400 "Too many reference images: 8. Maximum allowed is 7."

错在哪：API 文档未写上限，但服务端实际限制 7（live 证实）。

正面：`--ref` 最多 7 张；超出就挑最强的 7 张或拆成多个视频。

判断关键：`--ref` 计数 >7 → 先砍再跑。

## Gotcha #4 — R2V 想要旁白配音被 403

反面：`grokcli video "角色说：<AUDIO_0>..." --ref-audio eve` → 403 "reference_audios is not enabled for this team"

错在哪：`reference_audios`（预设声音配音）目前只对"美国 trusted partners"开放；普通订阅团队直接 403。不是代码问题，重试无效。

正面：去掉 `--ref-audio` 出无声版，或提示用户这是账号权限限制。

判断关键：403 且提示 "not enabled for this team" → 功能级授权缺失，换路径（去掉该功能），别重试。

## Gotcha #5 — I2V 和 R2V 一起传

反面：`grokcli video "..." -i frame.png --ref style.png` → HTTP 400（模式互斥）

错在哪：image（首帧）与 reference（参考）是两种互斥模式；客户端已拦截，绕过校验直传 API 也会 400。

正面：只选一种：`-i`（动画化一张图）或 `--ref`（风格/主体参考）。

判断关键：`-i` 与 `--ref`/`--ref-audio` 同时出现 → 一定错。

## Gotcha #6 — R2V 传 1080p

反面：`grokcli video "..." --ref a.png -r 1080p` → 客户端直接 UsageError

错在哪：R2V 上限 720p（1.5 的原生 1080p 只覆盖 T2V/I2V）。

正面：R2V 用 `-r 720p` 或更低；要 1080p 就换 T2V/I2V。

判断关键：带 `--ref` 却要 1080p → 换 720p。

## Gotcha #7 — TTS 传 model 或超长文本

反面：`grokcli tts "..." -m grok-tts`（旧参数，无效果）或 `grokcli tts "$(cat 50000字.txt)"`

错在哪：TTS API 无 model 参数（`-m` 仅为兼容保留）；文本上限 15000 字符，超出客户端直接拒绝。

正面：不传 `-m`；长文本分块多次生成。

判断关键：TTS/STT 命令里出现 `-m` → 去掉；文本明显超长 → 分块。

## Gotcha #8 — 403 当成登录问题反复重登

反面：`grokcli login` 重登 N 次，403 依旧

错在哪：403 = 订阅 tier 缺该 API 表面（如自定义音色 Enterprise 限定），与 token 无关；重登不改变授权。

正面：`grokcli status` 确认登录态正常后，接受功能不可用并告知用户升级路径。

判断关键：错误是 "Access denied (HTTP 403)" 且 status 显示已登录 → 授权问题，不是登录问题。

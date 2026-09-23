# 视频协议与 kvmd 接口

## T6AU v1

所有整数按网络字节序。固定头长 48 字节：

| 偏移 | 大小 | 内容 |
|---:|---:|---|
| 0 | 4 | ASCII T6AU |
| 4 | 1 | version = 1 |
| 5 | 1 | kind：1 = AU，2 = 状态 JSON |
| 6 | 2 | header length = 48 |
| 8 | 4 | payload length |
| 12 | 4 | flags：1 online，2 key，4 discontinuity |
| 16 | 4 | 输出 width |
| 20 | 4 | 输出 height |
| 24 | 8 | epoch：编码器实例标識，非零 |
| 32 | 8 | sequence：该 epoch 的 AU 序号，从 1 递增 |
| 40 | 8 | pts_us：本机单调时钟微秒 |

AU payload 为一幅编码图像的完整 Annex-B 字节流，包含该图像全部 slice。payload 最大 4MiB；key 标记必须对应 IDR NAL 5，并同时携带 SPS 7、PPS 8。边界校验不是完整 H.264 语义解码器，不证明图片内容可解码。

状态 payload 最大 64KiB，仅 JSON object。offline 状态清空恢复状态。每秒在线统计状态不被当作编码图像。

消费者通过 Unix stream socket 读取。反向控制仅字节 `K` 请求 IDR；生产者去抖合并。原生 worker 同样从 stdin 读 `K`。不能把任意 URL 或 HTTP 参数直接当命令执行。

## HTTP Unix socket

- `GET /state`：`{ok:true,result:{encoder,source,stream,h264,t6}}`。source 使用实际接收到的输出尺寸和 online，不因配置写 1440 就上报 1440。
- `GET /snapshot`、`GET /stream`：501，明确没有实时 JPEG／截图后端。
- 不另实现绕过上游的 `/set_params`。参数入口是 kvmd 的 `/streamer/set_params`，由上游校验并通过 Runner 重启 `kvmd.streamer.cmd`。

`encoded_fps_observed` 是 supervisor 在滑动窗口观察到的**可接受 AU 到达速率**，不是视频输入 timing、显示器刷新率或 TigerVNC 实际解码帧率。`encoded_frames` 是跨 native 重启累加的可接受 AU 计数；worker 状态另带原生 capture/encoded 计数。`hardware_validated:false` 是刻意保留的实验标记，不会因为收到几个 AU 自动变成硬件验收成功。

## 参数归属

| 参数 | 主要位置 | 本版约束 |
|---|---|---|
| VNC 地址／端口 | main.yaml → vnc.server | 默认 127.0.0.1:5900；改变前检查占用与证书 |
| fps | main.yaml → vnc.desired_fps / kvmd.streamer.desired_fps | 1…60；默认 60，非实测保证 |
| bitrate / GOP | main.yaml → kvmd.streamer | 上游上限 20000 kbit/s、GOP 60 |
| video device / 最大、预期尺寸 | streamer.toml | 默认最大 1920×1080，实验 profile 强制 2560×1440 |
| 接管／拒绝策略 | streamer.toml → policy | takeover 或 reject；改后需显式重启 VNC 实例 |
| 队列／超时 | streamer.toml | 默认 3 帧／8 秒 |
| input_mode / copy_mode | streamer.toml | 仅 native / copy；缩放、zero-copy 报错 |

上游通过启动命令传入 fps、bitrate、GOP；这些参数会覆盖 TOML 中对应默认值。改变 main.yaml 后的服务重启由操作者明确执行，脚本不会自动替你中断会话。

## 错误语义

无信号不伪造 HDMI 图像；通过状态上报和 kvmd 文字等待画面表示。坏 frame、超长 payload、SPS/PPS 缺失、丢失参考帧都停止发送相应依赖帧。编码器失败会重建，不静默切换软件编码器或改为 1080p。客户端没有 H.264 时直接给出明确 RFB 错误，不承诺未经实现的实时 JPEG 兜底。

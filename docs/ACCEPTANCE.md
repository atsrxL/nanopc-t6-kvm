# 验收：不要把配置或单测当成硬件结果

结果格式：PASS / FAIL / BLOCKED / NOT TESTED。每个 PASS 必须有对应硬件、命令、实际输出、时间与测试条件。当前目标项均为 **NOT TESTED**。

| 验收项 | 必须保存的证据 | 当前 |
|---|---|---|
| 固定 upstream 完整构建 | 四个提交、patch diff、Python 导入、配置检查、MPP 编译链接日志 | BLOCKED：当前无 SDK / 完整源码 |
| 原生 1080p 输入 | QUERY_DV_TIMINGS、G_FMT、signal timing、实际 planes | NOT TESTED |
| MPP 硬编而非软件兜底 | 正确库／设备、运行日志、真实 SPS / slice、解码结果 | NOT TESTED |
| TigerVNC 实际 H.264 | 客户端版本／构建选项、协商日志 H264=True、真实显示 | NOT TESTED |
| 1920×1080@60 | 输入、编码、发送、解码分别计数；稳定时段、不混合 epoch | NOT TESTED |
| 原生 2560×1440@60 | 输入 timing、G_FMT、SPS、解码尺寸和 VNC framebuffer 一致 | NOT TESTED |
| H.264 缺口恢复 | 有意制造慢读／队列溢出，缺口后无依赖 P 帧，IDR 后真实解码恢复 | NOT TESTED |
| 热插拔／分辨率变化 | 无信号 → offline → 新 epoch → IDR；旧 mmap/MPP/进程释放 | NOT TESTED |
| 身份认证及接管 | 密码错误不踢旧端；正确认证后接管；reject 策略保留原端 | NOT TESTED |
| 重复 SetEncodings | 真正客户端重复协商，没有连续不必要重启／黑屏 | NOT TESTED |
| USB HID | 枚举、BIOS/系统界面、修饰键、按钮、滚轮、绝对鼠标边界 | NOT TESTED |
| 断线释放／迟到旧清理 | 按住键断开、不粘键；旧端晚清理不释放新端正在按的键 | NOT TESTED |
| 共存与长稳 | CPU/RSS/温度、丢帧、延迟、其他服务负载、至少一段长稳记录 | NOT TESTED |
| 停止／回滚／卸载 | 无残留 native 进程、owned socket 清理、旧服务/网络/gadget 不变 | NOT TESTED |
| 4K→1440 / RGA / 零拷贝 | 另阶段实现与真实证据 | NOT IMPLEMENTED |

## 用真实输出检查编码数据

先按部署流程启动本项目流。`dump_frames.py` 只消费真实 frames.sock，不生成视频；输出目录必须不存在，必须由执行者有权限创建。

```sh
/opt/t6-kvm/current/venv/bin/python /opt/t6-kvm/current/tools/dump_frames.py \
  --seconds 10 --output /你已批准的工作目录/capture-001
```

按实际生成的 epoch 文件执行 FFmpeg/ffprobe，示意：

```sh
ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,profile,level,width,height \
  -of json /实际目录/epoch-实际值.h264
ffmpeg -v error -i /实际目录/epoch-实际值.h264 -f null -
```

保存每个 epoch 的文件、frames.jsonl、summary.json、解码器 stderr。工具中的 `saved_au_fps_from_pts` 是保存 AU 的时间戳速率，不是屏幕刷新或端到端解码帧率。文件可解码、header 标记 IDR 都不单独证明 60fps 画面已在客户端显示。

输入 1440p 验收不得仅看 display mode / EDID 字符串；需要查询采集器实际接收的 timing、输出 frame header 和真实解码器宽高。允许像素损失压缩，但不得偷偷输出 1080 后让客户端放大。

## 延迟测量

记录测量方法和时钟来源。用同一高速摄影画面观察源屏与接收端、或其他可以解释误差的方法；不能把 socket 一次发送耗时／编码调用时间直接当 glass-to-glass 延迟。帧队列中断恢复、稳定显示、鼠标到画面各有不同延迟口径。

## 故障注入顺序

先离线测试 → 无线外依赖的本机 Unix 消费者 → 真实 TigerVNC 1080p → 两客户端接管 → HDMI 拔插 → 同分辨率格式变化 → 分辨率变化 → 原生 1440p → 长稳。任何一步失败先保存现场，不通过自动降级分辨率或关闭认证绕过。

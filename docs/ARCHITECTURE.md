# 架构与取舍

```text
受控主机 HDMI OUT → T6 HDMI IN → /dev/video0
  → V4L2 MMAP / 实际格式与 stride 检查
  → CPU 转换或拷贝到独立 NV12 MPP buffer
  → Rockchip MPP H.264 Baseline / 无 B 帧 / Level 5.1
  → T6AU 有序字节流 (stdout)
  → t6_kvm.daemon (kvmd 生命周期子进程)
  → Unix frames.sock → T6StreamerClient
  → 保留的 kvmd-vnc RFB H.264 写入方法 → TigerVNC

TigerVNC 键鼠 → 保留的 RFB 输入处理
  → kvmd 内部 Unix HTTP/WS → upstream otg HID 插件
  → 独立两个 USB HID functions → 受控主机 USB
```

## 为什么本版没有直接写 uStreamer memsink

固定的 uStreamer 6.41 memsink 具有本机 ABI 布局、单帧槽和覆盖语义。它适合原有链路，不应简单认定“不能用”；但本轮需要在自定义生产者和多个 Python 阶段之间明确发现每个 H.264 参考帧缺口。

本版不猜测 `long double`、`size_t` 和结构体对齐，不用 Python 假造本机内存布局。采用显式版本、长度、epoch、递增序号的独立字节协议。每个完整 AU 是一个消息；短读或多包粘连都由 readexactly 处理，不把 socket 一次 read 当成一帧。

因此本轮属于原交接允许的“有序视频适配器”方案，而非 ABI 兼容的 uStreamer memsink producer。只替换客户端选取及帧队列边界，保留 RFB 核心发送、认证处理、HID 和 kvmd 参数生命周期。

## 队列与 H.264 恢复

每层队列有固定上限，默认三帧。溢出不是扔一帧再继续发送 P 帧，而是清空失效 GOP、请求 IDR，丢弃依赖帧直到同一 AU 含 SPS/PPS+IDR。消费者中途加入、epoch 变化、序号缺口、分辨率变更、断流文字提示之后都重置门控。

原生 worker 对每个送出的完整 AU 递增 sequence；进程重启重新产生非零 epoch。MPP 分片输出聚合到 end-of-image 后才封装，最大 4MiB；不无限合并帧。最终 VNC 发送侧再次验证连续性。硬编接入的正确性还必须用真实解码器验收。

## 生命周期

只运行 `t6-kvmd.service` 与 `t6-kvmd-vnc.service`。`kvmd.streamer.cmd` 启动 Python supervisor，supervisor 再启动 native worker。不要另加一个永久运行 streamer unit 争夺同一视频设备／socket。

客户端会话引起上游流需求；参数经 kvmd 原有接口进入 Params 和 Runner，按原有机制重启专属 streamer。native 遇到信号丢失、尺寸／格式／步幅变化、异常 packet 或超时，退出并清理；supervisor 等待／终止／回收旧进程后重开。停止时 TERM，必要时 KILL，再 wait。已有 socket 或不属于自身 inode 的文件不会被强删。

## 格式、色彩和性能范围

支持源码路径：NV12、NV16、NV24、BGR24；检查真实 plane 数、bytesperline、sizeimage、data_offset、bytesused。单内存 plane 的逻辑 Y/UV 布局基于原交接驱动参考，仍需目标实测确认。NV16/NV24 经 CPU 色度平均降为 NV12；BGR24 经整数矩阵转换，输出按分辨率选择 601/709，不能据此声称 HDR 色彩正确。

每帧 CPU 写入 MPP buffer 前后调用并检查 MPP cache-sync。V4L2 buffer 在转换完成后归还，编码器持有独立输入 buffer，避免驱动覆盖仍在编码的数据。当前是同步逐帧编码，不假称零拷贝／异步流水线已经优化。Level 5.1 避免把 1440p60 误限定为 4.1，但是否被目标 MPP 和客户端正确执行必须检查 SPS。

## 不做的事情

不写 EDID，不更新内核，不改变 USB role，不挂载 configfs，不开 USB 网卡，不启动 nginx/Janus/PST/IPMI。不提供 ATX、MSD、音频、HDR 或缩放。PiKVM 特有的 RPi 电源遥测不伪造，可能显示不支持／产生日志；它不是 T6 测量值。

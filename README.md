> 2026-09-23 实机更新：已部署 dev20260923g，1080p 实测约 58–59 fps，真实 TigerVNC 1.15.0 显示及 PC 键鼠事件验证通过。连接与运行方式见 [docs/USAGE.md](docs/USAGE.md)，证据见 results/20260923-live/STATUS.md。下文保留最初交接记录。

# T6 KVM 0.1.0 — 第一版开发源码包

**用途：交给本地 Codex／开发者继续构建与上板验证。不是已验证的可直接安装成品。**

保持原有 TigerVNC 工作流：复用固定版 kvmd-vnc 的 RFB、认证和 USB HID；补上 RK3588 HDMI RX → MPP H.264 视频后端。不使用 X11 播放再抓屏，不转向 WebRTC，不替换现有设备系统。

本包在 2026-09-23 的 x86_64 / Python 3.13 环境完成离线测试。**没有访问 T6，没有修改它的配置／网络／内核／gadget，没有证明 1080p60 或原生 1440p60 跑通。**

## 从哪里开始

先读 **[HANDOFF.md](HANDOFF.md)**，再读 [构建](docs/BUILD.md)、[部署及回滚](docs/DEPLOYMENT.md)、[验收](docs/ACCEPTANCE.md)。原始交接包保存在 `reference/original-handoff.zip`，原文件校验值见 `reference/provenance.json`。

## 已写入源码的内容

| 部分 | 实现及验证边界 |
|---|---|
| `native/capture.c` | 实际 V4L2 多平面采集、MMAP、CPU 转 NV12、MPP H.264 编码调用、IDR、重建和资源释放；**未用真实 MPP 头文件编译，未上板** |
| `native/pixels.c` / `wire.c` | NV12/NV16/NV24/BGR24 处理、stride/长度校验、48 字节跨语言帧头；通过 C 单元测试及 ASan/UBSan |
| `src/t6_kvm/daemon.py` | 原生进程监督、Unix 有序帧分发、状态接口、断流／卡死重启、停止清理 |
| `protocol.py` / `buffer.py` | epoch、连续序号、SPS/PPS+IDR 恢复门控、有界队列；溢出后不继续发送依赖丢失参考帧的 P 帧 |
| `kvmd_adapter.py` / `tools/patch_kvmd.py` | 固定提交守卫的 kvmd 适配；认证成功后接管、旧会话清理隔离、重复 SetEncodings 不重复设置参数、强制 X509Plain；**完整上游补丁应用和导入仍待验证** |
| `tools/` / `systemd/` | 只读预检、固定源码获取、目标构建、隔离安装／回滚／保留数据式卸载、独立 gadget 工具、凭据工具、真实帧导出 |

## 本次实际测试

Python 共 **54 项通过**；C 的 `native-core` **1 项通过**。具体输出见 `results/`，最终状态以 `results/validation.json` 为准。

测试中的少量 NAL 数据是**不可直接解码的边界测试样本**，只用于协议／恢复状态机；不是编码性能测试。真实子进程测试也使用测试专用发送器，生产配置不会引用它。

## 当前有意保留的限制

- 首先验证不缩放的 1920×1080 输入；`config/streamer-native1440-experimental.toml` 要求**真实 2560×1440 输入**，不会把 1080p 冒充 2K。
- 4K→1440p 缩放、RGA、零拷贝 **未实现**；对应请求明确拒绝。RGA 和 uStreamer 固定提交仅作接口参考，本版不链接它们。
- 采用 CPU 拷贝／转换，尚无目标 CPU 占用、温度、延迟或帧率测量。
- 实时视频仅 H.264。实际 TigerVNC 构建必须协商 H.264 与 Tight；JPEG 仅用于断流文字提示，`/snapshot`、实时 JPEG `/stream` 返回 501。
- 仅 SDR 8-bit；不宣称支持 HDR、HDCP、ATX、存储、声音、4K 输入或高于 60fps。
- 固定了四个核心上游提交，但 Debian 和 Python 的所有传递依赖尚未做完整哈希锁定；首个成功目标构建须记录实际版本。

## 目录

```text
native/              原生采集、像素转换、有序帧封装、只读探针
src/t6_kvm/          监督器、队列、接管状态机、kvmd 适配
config/              默认 1080p 与实验性原生 1440p 配置
systemd/             两个独立命名的服务；不会自动启用
tools/               只读预检、构建、独立管理与验收工具
sources.lock.json    kvmd / uStreamer / MPP / RGA 固定提交与使用状态
tests/               离线测试，不等于实机验收
results/             本次真实测试结果和未完成验证记录
docs/                接口、构建、安全部署和验收说明
reference/           原始交接包及校验记录
```

项目新增源码按 GPL-3.0-or-later 提供；上游保留各自许可，见 `LICENSE`、`licenses/README.md` 与 `docs/SOURCES.md`。

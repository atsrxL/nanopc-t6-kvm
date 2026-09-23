> 2026-09-23 实机更新：已部署 dev20260923g，1080p 实测约 58–59 fps，真实 TigerVNC 1.15.0 显示及 PC 键鼠事件验证通过。连接与运行方式见 [docs/USAGE.md](docs/USAGE.md)，证据见 results/20260923-live/STATUS.md。下文保留最初交接记录。

> 2026-09-23 本地续作更新：已完成真实 ARM64 MPP/kvmd 构建，并部署 dev20260923c 到 T6。TLS、认证、接管、无信号提示、停止清理已做实机协议验证。HDMI ENOLINK、USB not attached，视频与实际键鼠仍未验收。最新证据见 results/20260923-live/STATUS.md；下文保留最初交接背景。

# 接手指引：T6 KVM 0.1.0

## 给接手 Codex 的首要指令

这是**源码续作及验证项目**，不是授权你立即部署。先读取原始交接包、`docs/BUILD.md`、`docs/DEPLOYMENT.md` 和本文件。不要把已有服务、网络、代理、容器、USB gadget、EDID 或内核当成可随意清空的环境。

目标是保留用户已经满意的 TigerVNC 使用方式，以独立实例复用 kvmd-vnc/auth/HID，并在 NanoPC-T6 LTS 的 RK3588 HDMI RX 上实现可验证的视频链路。目标原生 2560×1440@60，第一阶段先验证原生 1920×1080。**没有任何实机目标已经验收通过。**

## 本轮完成与没有完成

已写出生产路径源码，而不只是架构说明：V4L2/MPP worker、像素转换、跨语言帧协议、队列和丢帧恢复、kvmd 适配补丁生成器、认证后接管、状态／生命周期、只读预检、隔离管理脚本、systemd、配置和测试。

已在当前容器执行：54 项 Python 测试；C 核心测试与 ASan/UBSan；其他语法／构建探测结果见 `results/validation.json`。

**未完成**：真正的 pinned kvmd checkout 上应用全部补丁、完整 Python 依赖和配置导入验证、`native/capture.c` 对真实 MPP SDK 的编译链接、T6 摄像输入／硬编、真实 TigerVNC 解码、USB 枚举及键鼠、热插拔、性能与长稳验收。本环境无法解析 GitHub 域名进行源码下载，也没有 MPP 头文件／库或目标硬件；没有用伪造头文件、假硬编输出或虚构测试结果填补这些空白。

## 建议按以下顺序推进

### 1. 先在工作目录做纯构建，不碰系统服务

检查 `sources.lock.json` 的四个提交。用 `tools/fetch_sources.py` 先预览，再明确传 `--apply` 获取。不要换成 main 或在已有脏工作树上覆盖。

优先跑 `tools/patch_kvmd.py <pinned-kvmd>` 的 dry-run 并查看 diff；它只接受 `78ff181e95b14327831441d58f2f7f4cb2181cde`。本轮已修复 typed assignment 为 AnnAssign 的匹配问题；仍必须在实际源码上验证五个文件，而不是只相信 fixture 测试。

在 AArch64、Python 3.13 的构建环境，按 `docs/BUILD.md` 准备依赖并运行目标构建。遇到 API／宏／编译告警应修代码并补测试，不能通过关闭全局错误检查、引入假 MPP 头文件或把真实编码器换成生成视频来“通过”。

### 2. 在获得执行许可后，只读刷新 T6 实况

原始证据是快照：驱动没有枚举 2560×1440，读取时无信号，EDID 未证明原生 1440p 支持。**这并不单独证明硬件永远不支持，也不能据此直接刷 EDID 或内核。**

重新确认 `/dev/video0`、有效 DV timing、像素格式、每 plane 的 bytesperline/sizeimage/bytesused、MPP/DRM 权限、UDC、现有 gadget、5900 端口、可用内存和其他服务负载。只读工具见 `preflight.py` 和 `native/probe.c`。

### 3. 首先证明原生 1080p 链路

不做缩放。输入、编码帧头、真实解码输出应全部为 1920×1080。记录 MPP 确实被调用、GOP／参数集／IDR、输入／编码／发送／解码各自的帧率，不能拿配置的 `fps=60` 当成实测 60fps。

默认内部接口全部是 Unix socket，VNC 仅 127.0.0.1。端口、证书、客户端实际 H.264 编译支持必须验证；不能把常规发行版 TigerVNC 必然支持 H.264 当成前提。

### 4. 分开批准安装、设备权限、USB gadget 和服务启动

`admin.py install --apply` 不自动启动服务、不绑定 USB、不改设备权限。独立 `gadget.py` 只创建本项目两个 HID，发现任何现有 gadget 或 HID 节点就拒绝。MPP/DRM/V4L2 权限变更应先提交精确路径和备份方案，不得 chmod 777 或全局放开设备。

先运行配置检查，再创建独立 htpasswd 用户和证书。完成资源边界人工审查后才能创建与当前 release 绑定的 `hardware-reviewed.json` 并明确启动本项目两个 unit。不要自动 enable 启动项；首轮 USB gadget 也不自动随开机绑定。

### 5. 再验证原生 1440p，最后考虑缩放/零拷贝

切换到 `streamer-native1440-experimental.toml` 前备份专属配置。该配置强制输入必须真的是 2560×1440。要同时记录 QUERY_DV_TIMINGS、G_FMT、H.264 SPS／真实解码尺寸和客户端 framebuffer。出现 1920×1080 不得算作 2K 成功。

4K→1440p 和 RGA 尚未实现，禁止在文档、UI 或日志中宣称已支持。下一阶段实现前需要另行验证源 4K 是否可采集、RGA API 与驱动能力、色彩空间、步幅、DMA 同步、硬编吞吐及共享 SoC 资源影响。

## 风险优先检查清单

- `native/capture.c` 是首个实际编译重点：MPP ABI、配置项、packet 分区、缓存同步返回值、buffer 生命周期和 ioctl 错误路径。
- `tools/patch_kvmd.py` 不能对原始包里的“较新主线快照”应用；那不是本版锁定的 v4.120。
- VNC 丢帧有 broker、adapter 和最终发送侧多层恢复门控；要用真实解码器测试 IDR 恢复，不仅看 Python 单测。
- 接管必须先验密码再取消旧连接；错误密码不得踢掉旧控制端；旧 WebSocket 的迟到清理不得释放新端按键。
- kvmd v4.120 原验证器的码率上限为 20000 kbit/s、GOP 为 60。本版对外配置保留这些上限。独立 worker 较高上限不是 kvmd 可用参数的承诺。
- 备份只在 `/root/agent.backup/`，每个源项目最多保留两个本项目创建的备份；不要删除不属于本项目的文件。
- 源码包没有包含 x86 测试二进制或完整第三方 checkout。只有真实目标构建生成的 stage 才能传给 installer。

## 交付下一轮结果

保留完整编译输出、实际依赖版本、补丁 diff、硬件只读探测 JSON、真实 AU 元数据及解码结果、键鼠和接管实验日志。更新 `docs/ACCEPTANCE.md` 对应结果，不要把 NOT TESTED 批量改成 PASS。最后重新打源码包与接手指引。

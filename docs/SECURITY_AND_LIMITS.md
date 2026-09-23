# 安全边界与已知开发限制

本项目是可审查的开发源码，不是经安全审计的远程管理产品。KVM 具有主机控制权限；仅限自己的设备或已授权管理环境。

网络仅 VNC；内部 HTTP/WS 和视频采用独立 Unix socket。默认 VNC loopback，X509Plain 强制认证，无默认密码。TLS 证书必须通过可信方式核对，不能为了“连上”接受未知证书／明文回退。上游 max_clients 参数是 listen backlog，不能理解成防 DoS 的连接并发限制；本版 Owner 只限制一个已认证控制端，不是完整的预认证抗攻击层。

Unix self-auth 只授权专属 t6-kvm 进程；保留原 auth/check 的 allow_usc=False，不能让错误密码因为 Unix peer UID 而自动通过。认证及接管测试当前只是 fixture / 状态机，不等于真实 TLS/RFB 全链路审计。

脚本默认 dry-run，只有明确 --apply 才写入。gadget 再要求 --i-reviewed-usb。安装从验证过的 stage 取文件，拒绝路径越界、外部 symlink 和未清单文件；仍需要信任构建者和被审查的源码，文件 hash 不是发布者数字签名。

Installer、gadget、凭据工具的真实 root/systemd/configfs 路径本轮未执行。已测试的是部分纯文件安全函数与 fixture；它们不能保证所有断电／设备消失／系统状态组合都已覆盖。

V4L2 buffer 对齐、色彩矩阵与 CPU 占用是上板重点。原生代码使用同步 MPP Baseline 路径，尚未证明真无 B 帧／分区符合假设，必须检验输出。遇到非 8-bit SDR、未知矩阵、unsupported plane layout 会报错，不静默猜测。

原生 worker 对正在使用的捕获设备会执行捕获配置、STREAMON、QBUF 等 ioctl；这些当然是有副作用的。仅预检 probe 是只读，不能把“程序不写 EDID”解释为“运行采集器完全不改设备状态”。

本版没有全量传递依赖锁、完整目标编译、硬件实际采集、TigerVNC 解码、USB 输入、完整升级故障恢复与性能验收。当前结果不能作为生产就绪声明。

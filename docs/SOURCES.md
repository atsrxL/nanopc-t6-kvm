# 固定来源与核对范围（2026-09-23）

版本和完整 SHA 以 `sources.lock.json` 为准。以下都是官方项目源码／文档，不以第三方教程替代 API 契约。网页核对不等于容器实际获取到完整 checkout。

## kvmd

- https://github.com/pikvm/kvmd/releases/tag/v4.120
- https://raw.githubusercontent.com/pikvm/kvmd/v4.120/PKGBUILD
- https://raw.githubusercontent.com/pikvm/kvmd/v4.120/kvmd/apps/vnc/server.py
- https://raw.githubusercontent.com/pikvm/kvmd/v4.120/kvmd/apps/vnc/__init__.py
- https://raw.githubusercontent.com/pikvm/kvmd/v4.120/kvmd/apps/vnc/rfb/__init__.py
- https://raw.githubusercontent.com/pikvm/kvmd/v4.120/kvmd/clients/streamer.py
- https://raw.githubusercontent.com/pikvm/kvmd/v4.120/kvmd/apps/kvmd/api/auth.py
- https://raw.githubusercontent.com/pikvm/kvmd/v4.120/kvmd/apps/kvmd/streamer/__init__.py
- https://raw.githubusercontent.com/pikvm/kvmd/v4.120/kvmd/apps/_scheme.py
- https://raw.githubusercontent.com/pikvm/kvmd/v4.120/kvmd/validators/kvm.py
- https://raw.githubusercontent.com/pikvm/kvmd/v4.120/kvmd/plugins/hid/otg/__init__.py
- https://raw.githubusercontent.com/pikvm/kvmd/v4.120/kvmd/apps/otg/__init__.py
- https://docs.pikvm.org/vnc/

重点核对：Python 3.13 约束；streamers 是带类型注解的赋值；H.264 format ID；原始有限队列／拼帧行为；auth/check 排除 Unix socket credentials；参数单位、上限和 restart 生命周期；VeNCrypt 默认包含明文子类型，本项目补丁强制只保留 X509Plain。

## uStreamer 6.41（接口参考，未链接）

- https://github.com/pikvm/ustreamer/releases/tag/v6.41
- https://raw.githubusercontent.com/pikvm/ustreamer/v6.41/src/libs/memsink.h
- https://raw.githubusercontent.com/pikvm/ustreamer/v6.41/src/libs/memsink.c

用于核对 memsink ABI/version、单帧覆盖以及键帧请求。不把项目自定义 T6AU 协议误称为 ABI-compatible memsink。

## Rockchip MPP（需要真实目标构建）

- https://github.com/rockchip-linux/mpp/commit/0986d01294d5c2449c14cf13af9b740368c33967
- https://raw.githubusercontent.com/rockchip-linux/mpp/0986d01294d5c2449c14cf13af9b740368c33967/inc/rk_mpi.h
- https://raw.githubusercontent.com/rockchip-linux/mpp/0986d01294d5c2449c14cf13af9b740368c33967/inc/rk_venc_cfg.h
- https://raw.githubusercontent.com/rockchip-linux/mpp/0986d01294d5c2449c14cf13af9b740368c33967/inc/mpp_buffer.h
- https://raw.githubusercontent.com/rockchip-linux/mpp/0986d01294d5c2449c14cf13af9b740368c33967/test/mpi_enc_test.c
- https://raw.githubusercontent.com/rockchip-linux/mpp/0986d01294d5c2449c14cf13af9b740368c33967/mpp/base/mpp_enc_cfg.c

核对配置名与 s32/u32 类型、MPP packet 分区与 EOI、每 IDR 附带 header、缓存同步 API。不能用 API 存在代替实际硬件运行验证。

## librga（未实现的后续缩放参考）

- https://github.com/airockchip/librga/commit/2b32edcb97b601b25683e2941d888c8515da6d55
- https://github.com/airockchip/librga

该仓库包含供应商预编译库与头文件；不能误称为已经编译整套 RGA 实现。当前包不包含或调用这些二进制。

## 用户现场证据

原始交接 ZIP 和其中的 inventory、probe JSON、EDID、驱动参考及架构／验收说明是硬件边界来源，存于 `reference/`。它们只代表当时采样，不证明现在端口／gadget／权限仍保持相同状态。

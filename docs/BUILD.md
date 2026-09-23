# 构建说明与当前构建空白

## 1. 离线测试（不需要 T6、MPP 或完整 kvmd）

使用 Python 3.13，准备 aiohttp 与 PyYAML 测试依赖，以及 CMake、C 编译器、Linux UAPI 头文件。建议在独立 venv／构建环境准备，不覆盖宿主 Python。

```sh
cd t6-kvm-0.1.0
cmake -S . -B build-offline -DT6_BUILD_MPP=OFF -DT6_SANITIZERS=ON
cmake --build build-offline -j2
ctest --test-dir build-offline --output-on-failure
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

这只编译像素／帧协议／只读探针与 native-core 测试。**`-DT6_BUILD_MPP=OFF` 不会编译 capture.c，不能以此宣称视频编码器编译通过。** 当前交付记录了本路径通过，以及完整构建缺少 MPP SDK 的阻塞。

## 2. 固定上游

`source.lock` 的实际文件名为 `sources.lock.json`，包含：

| 项目 | 固定版本／提交 | 本版使用 |
|---|---|---|
| kvmd | v4.120 / 78ff181e95b14327831441d58f2f7f4cb2181cde | 修改后的 Python runtime |
| uStreamer | v6.41 / 05a5d3fed418503c49aa42916874c8a9a845c04b | 接口参考，不编译／链接 |
| MPP | 0986d01294d5c2449c14cf13af9b740368c33967 | 原生 runtime，必须实际构建 |
| librga | 1.10.6_[3] / 2b32edcb97b601b25683e2941d888c8515da6d55 | 参考，不链接；缩放未实现 |

选 v4.120 是为了固定 Python 3.13 兼容基线，不表示它是最新或完成安全审计的版本。不能直接使用上传交接包里较新主线的三份 kvmd 快照替代这个完整 checkout。

```sh
python3 tools/fetch_sources.py --directory "$PWD/deps"         # 只预览
python3 tools/fetch_sources.py --directory "$PWD/deps" --apply # 明确获取公开源码
python3 tools/patch_kvmd.py "$PWD/deps/kvmd" > patch-review.diff # 只生成 diff，不修改
```

获取工具只接受实际固定提交和干净工作树。不能自动 checkout/reset 掉用户已有改动。

## 3. AArch64 目标构建

构建脚本不会调用 apt、不会下载依赖、不会执行 upstream PKGBUILD、不会写 /usr、/etc、/boot。先在合适的 AArch64/Python 3.13 环境补齐依赖，再明确构建。`JOBS=2` 是默认构建并行度，不是性能设置；有其他服务共存时应谨慎。

系统构建依赖包括编译器、CMake、Git、pkg-config、Python venv/pip/setuptools、Linux 头文件与 MPP 所需的 DRM 开发依赖。Python 导入依赖以锁定版 `PKGBUILD` 及源文件导入为依据：yaml、ruamel.yaml、aiohttp、aiofiles、async_lru、passlib、pyotp、Pillow、evdev、gpiod 2.x、setproctitle、psutil、pyserial、serial_asyncio、spidev、systemd 等，以及对应动态库（如 libxkbcommon）。

**本轮尚未在 Debian 13 实际构建整个 kvmd 依赖集合，因此不提供虚构的“已验证 apt 一行安装清单”。** 先用发行版的包元数据核对模块和版本；缺少导入应在专属构建环境解决。不要为了满足 RPi/Janus/nginx 的整机发行版依赖，把这些整机服务及网络脚本装到 T6。

```sh
JOBS=2 PYTHON=python3 tools/build_target.sh \
  --apply --sources "$PWD/deps" --output "$PWD/stage-t6-001"
```

输出目录必须不存在，且不应是 `/opt/t6-kvm`。脚本要求 AArch64，使用构建目录内的 MPP 源码副本，避免上游 CMake 写坏原始 checkout。步骤依次是 MPP、native worker、guarded kvmd patch、专属 venv、完整相关模块导入、配置 schema 检查和环境记录。

只有这些步骤成功，末尾才生成 `release.json`、`stage-sha256.json`。中途失败的 stage 不可安装。构建日志是诊断结果，不会被修改成成功。stage 内 venv 使用 copies；本项目 wrapper 通过相对 release 路径调用 `venv/bin/python`，不依赖 pip console-script 的旧 staging shebang。不要直接依赖移动后 venv 中其他工具的 shebang。

## 4. 可复现性边界

四个上游提交已固定；尚未锁定所有系统包和 Python 传递依赖及下载哈希。构建输出保存 `python-environment.txt`、`debian-environment.txt`、`native-linkage.txt`、补丁 diff 和逐文件 hash。首个真实成功构建后应补成完整依赖锁定／构建记录，再考虑发布可安装二进制。

本次 x86 环境没有完整 upstream checkout，也无法解析 GitHub 域名进行下载；没有 MPP 头文件／库。网页层进行了源码接口核对，但这不等于完成实际 `git checkout`、编译链接或软件包导入。

## 2026-09-23 实际构建补充

在 MS-A2 VM 301 的 Debian trixie ARM64 容器（QEMU binfmt）完成固定 MPP 编译、t6-capture 链接、完整 kvmd 导入和配置检查，并在 NanoPC-T6 实机再次验证动态链接和服务启动。硬件视频验收仍须有效 HDMI 输入。

构建工具：build-essential、cmake、git、pkg-config、libdrm-dev、python3-dev、python3-pip、python3-setuptools、python3-wheel。运行依赖实际使用：

python3-venv python3-ruamel.yaml python3-aiohttp python3-aiofiles python3-async-lru python3-passlib python3-pyotp python3-pil python3-evdev python3-libgpiod python3-setproctitle python3-psutil python3-serial-asyncio python3-spidev python3-systemd python3-netifaces libxkbcommon0 python3-pygments python3-xlib python3-pyghmi python3-pam python3-dbus python3-dbus-next python3-zstandard python3-mako python3-hid python3-pyudev python3-usb

这份列表是本次通过环境的记录，不是所有可选 kvmd 插件的依赖承诺。Debian pyghmi 为 1.5.70；本项目不启用 IPMI，未验证该可选功能。未安装可选 OCR libtesseract，启动时会提示 OCR 不可用。

修复：C 测试目标在 Release 下保留断言；提供可重定位 t6-streamer wrapper 与 --version/--features；平台文件使用上游键值格式；专属 kvmd 补丁将 /bin/false 遥测视为未知，并修复 Python 3.13 TLS abort 后查询 SSL 信息的清理顺序。

JPEG compatibility requires PyAV 16.1.0 and Pillow 11.x in Python 3.13. Prepare before offline build (--no-deps). Live deployment uses the aarch64 PyAV wheel with bundled FFmpeg for software decoding. JPEG encoding uses Pillow.

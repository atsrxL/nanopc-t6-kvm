# 隔离部署、权限和回滚

**本文中的 apply／启动命令是供获得明确执行许可后的本地操作者使用。本次交付没有运行它们。**

## 资源边界

专属资源只有 `/opt/t6-kvm/`、`/etc/t6-kvm/`、`/var/lib/t6-kvm/`、`/run/t6-kvm/`、`/run/t6-kvm-otg/`、两个 `t6-kvmd*.service`、系统账号组 `t6-kvm` 及明确创建的 `usb_gadget/t6-kvm`。备份只进入 `/root/agent.backup/`。

不编辑现有 `/etc/kvmd`、nginx、代理、容器、网络、DNS、路由、iptables、系统内核／启动文件；不占用既有 gadget。目录／unit 已存在但不是本项目所有时拒绝覆盖。源码包不是已构建 stage，installer 会拒绝直接安装它。

## 安装与更新

```sh
python3 tools/admin.py install --stage "$PWD/stage-t6-001" --release dev001
sudo python3 tools/admin.py install --stage "$PWD/stage-t6-001" --release dev001 --apply
```

安装检查 stage hash、创建专属系统账号／组、只拷贝新 release、首次创建专属配置、写两个 unit 和原子 current 链接、daemon-reload。**不自动 enable/start/restart 服务，不改设备权限，不创建 gadget。**

升级需先明确停止本项目服务，使用新 release ID。配置不被覆盖；本地修改过 unit 会导致升级／卸载拒绝，需要人工合并。安装不是任意崩溃点都自动恢复的事务；中途失败应保留目录和日志，核对已完成步骤，不能递归清空 /opt、删除同名用户或关闭其他服务“修复”。

## 配置与凭据

在真实 stage 完整验证后，运行：

```sh
/opt/t6-kvm/current/venv/bin/python /opt/t6-kvm/current/tools/check_config.py
sudo /opt/t6-kvm/current/venv/bin/python /opt/t6-kvm/current/tools/credentials.py \
  operator --cert-name YOUR_T6_DNS_NAME --apply
```

`YOUR_T6_DNS_NAME` 换成客户端实际使用的 DNS 名或 IP。密码由原版 kvmd 工具交互输入，不在命令行／源码提供默认密码。修改已有用户需 `--replace-user`，替换证书需 `--rotate-cert`，都会保留范围内备份。空 htpasswd 表示没有允许登录的用户。

本版在原 VeNCrypt 协商点只保留 X509Plain，拒绝 Plain、None 和匿名 TLS 回退；客户端需验证／固定对应证书。TLS 在这里是 VNC 传输，不是新增网页 HTTPS 面板。默认监听 127.0.0.1，可在既有 SSH 通道上测试；直连内网地址要明确改 `vnc.server.host` 并验证证书和端口，不自动修改防火墙，不建议暴露公网。

## 只读预检与设备权限

只读探针只使用查询／枚举 ioctl，不 STREAMON、不写 EDID。可先构建无需 MPP 的 probe，然后：

```sh
PYTHONPATH=src python3 -m t6_kvm.preflight \
  --device /dev/video0 --port 5900 --probe "$PWD/build-offline/t6-probe" --strict \
  > preflight-current.json
```

root 读写权限不代表服务账号权限；需要分别核对。除了 `/dev/video0`、`/dev/mpp_service`，MPP 的实际 DRM 分配器还可能需要特定 `/dev/dri/*`／dma-heap 节点。不要猜测所有节点都要放行，不需要给未使用的 RGA 放权。

**设备 ACL／udev 变更不由本版 installer 自动执行。** 本地接手者先列出实际节点的 uid/gid/mode/ACL、占用者、拟新增的最小授权和精确恢复方式，经批准后执行。优先只为专属账户增加必要权限；不得 chmod 777、改变其他服务账号、使用全设备放权或 broad udev trigger。任何原有 ACL／规则的备份必须进入 `/root/agent.backup/`，每项最多两份，仅整理本项目备份。

## USB HID：单独批准的有副作用操作

```sh
sudo /opt/t6-kvm/current/venv/bin/python /opt/t6-kvm/current/tools/gadget.py start
sudo /opt/t6-kvm/current/venv/bin/python /opt/t6-kvm/current/tools/gadget.py \
  start --apply --i-reviewed-usb
```

先明确停止本项目服务。工具要求 configfs 已挂载、`fc000000.usb` 已可用且没有任何 gadget／hidg 节点；不会 modprobe、改变 USB role、卸载其他 gadget 或添加 USB 网卡。它使用固定 kvmd 的键盘与绝对鼠标描述符，创建两个函数；仅为它新建的 hidg0、hidg1 赋予专属组访问权限。

本版 gadget 名、UDC、HID 节点、序列号和函数数量是固定安全边界。不要只修改 main.yaml 这些字段期待 helper 自动跟随；确有硬件差异时应先修改 helper、配置与测试的一致性。普通视频 device/尺寸/VNC 端口等按配置支持修改。

owner.json 记录当前 boot、gadget inode、HID major/minor；停止只处理校验通过的本项目对象。发现函数／inode／链接异常则保留现场并报错。**不要绕过 helper 直接运行 kvmd-otg 来接管其他 gadget。**

## 人工审查标记与明确启动

`hardware-reviewed.json` 是安全审查记录，不是性能或功能验收。确认独立权限、端口、gadget、配置和资源共存后，用 root 在本项目目录创建下面内容，`release` 必须为 `readlink -f /opt/t6-kvm/current` 的实际值；文件 root:t6-kvm 0640：

```json
{"reviewed": true, "release": "/opt/t6-kvm/releases/dev001"}
```

然后才明确运行：

```sh
sudo systemctl start t6-kvmd.service t6-kvmd-vnc.service
sudo journalctl -u t6-kvmd -u t6-kvmd-vnc --since '5 minutes ago'
```

服务启动 gate 会检查当前 release、gadget ownership 和服务账号对基础节点的访问；通过 gate 不等于 MPP、HDMI 或 HID 已正常工作。首轮不要 `enable`，USB helper 也没有默认开机 unit；重启后需要重新检查并显式创建 gadget。

## 备份、回滚和卸载

修改专属配置前：

```sh
sudo python3 tools/admin.py backup --path /etc/t6-kvm/streamer.toml --apply
```

备份 JSON 存在 root 私有目录，含原始内容及 uid/gid/mode，**不是加密备份**。每个源文件只保留最近两份本项目记录，不删除其他文件。目录已有权限不安全时工具拒绝，不自动改掉整个目录权限。

二进制回滚不会恢复配置，先停止本项目服务：

```sh
sudo systemctl stop t6-kvmd-vnc.service t6-kvmd.service
sudo python3 tools/admin.py rollback --release dev001 --apply
```

配置需要单独 `admin.py restore --path /root/agent.backup/<实际备份>.json --apply`。不要照抄示例占位符。回滚后重新做配置／release 审查，工具不启动服务。

卸载前先停止服务，再明确停止自己的 gadget：

```sh
sudo /opt/t6-kvm/current/venv/bin/python /opt/t6-kvm/current/tools/gadget.py \
  stop --apply --i-reviewed-usb
sudo python3 tools/admin.py uninstall --apply
```

卸载只 disable 并删除未被修改的两个项目 unit 和 owned current 链接；**保留 releases、配置、账户、备份和证据**。设备 ACL／人工 udev 更改按操作者事先保存的精确恢复计划恢复；本工具不会猜测原权限或清理外部规则。

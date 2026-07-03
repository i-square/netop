![netop logo](https://raw.githubusercontent.com/i-square/netop/main/assets/logo.png)

------

# netop

[English README](https://github.com/i-square/netop/blob/main/README.md)

`netop` 是基于原 `tmd-top` 思路做的一次面向 Linux 日常网络排障的精简重构。
原仓库已经有一段时间没有持续演进，原实现把 GeoIP 查询、SQLite 快照表、
IP 封禁和 TUI 渲染放在一个应用里。本分支刻意收窄范围，只保留一个目标：
快速、只读、低开销的 Linux 终端网络监控。

![netop terminal UI](https://raw.githubusercontent.com/i-square/netop/main/assets/netop-screenshot.png)

## 设计目标

- 纯监控：移除 IP 封禁按钮，不写 iptables、nftables 或 firewalld。
- 无状态运行：不使用 SQLite，不保存历史流量数据。
- 移除 GeoIP：不携带 MMDB 数据库，不显示地区列，不做每个 IP 的地理查询。
- 低开销采样：通过 `ss`、`ps` 和 `/proc/net/dev` 读取数据，在内存中计算差值。
- 现代 Textual 路线：只使用公开 API，依赖改为 `textual>=8.2,<9`，不再锁死
  `textual==1.0.0`。

## 当前状态

这是早期重构分支。核心包名和命令行入口都已经改为 `netop`，不再兼容旧的
`tmd` / `tmd-top` 命令。

当前界面包含：

- 网卡流量
- 监听服务
- 外连进程
- 服务或进程对应的 TCP 连接详情
- 搜索、刷新模式、排序模式、权限状态和速率单位状态

## 环境要求

- Python >= 3.10
- Linux
- `iproute2`，用于提供 `ss`
- `procps`，用于提供 `ps`

## 安装

推荐直接从 PyPI 安装：

```shell
python -m pip install netop
```

如果你的默认 pip 源是内网镜像，且还没有同步 `netop`，可以显式使用官方
PyPI：

```shell
python -m pip install --index-url https://pypi.org/simple netop
```

本地开发时使用源码安装：

```shell
python -m pip install -e .
```

## 使用

如果安装在普通用户环境中，直接运行：

```shell
netop
```

普通用户模式下，`netop` 会在系统配置了免密 sudo 时尝试使用 `sudo -n ss`
读取更多 PID 和进程归属信息；TUI 内不会弹出 sudo 密码输入。

如果安装在 root 可见的环境中，或者你希望尽量完整地显示 socket 归属信息，
可以使用：

```shell
sudo netop
```

## 快捷键

| 快捷键 | 功能 |
| --- | --- |
| `q` | 退出 |
| `v` | 聚焦搜索 |
| `b` | 切换 bit/byte 速率单位 |
| `t` | 慢刷新，5 秒 |
| `y` | 快刷新，1 秒 |
| `r` | 按总流量排序 |
| `c` | 按连接数排序 |
| `i` | 按 IP 数排序 |
| `u` | 按上传排序 |
| `d` | 按下载排序 |
| `z` | 按 CPU 排序 |
| `x` | 按内存排序 |

单击或高亮左侧的监听服务、外连进程行后，右侧会显示对应 TCP 连接详情。

## 显示单位

默认使用 `Kb/s`、`Mb/s` 这类 bit 速率显示网络带宽。按 `b` 可以切换为
`KB/s`、`MB/s` 这类字节速率。

## 数据流

1. `ss -tniH state established` 读取 TCP socket 计数器。
2. `ss -tpanH` 读取监听 socket、已建立连接、PID 和可用的进程名。
3. `ps` 读取 PID 对应的轻量 CPU/内存元数据。
4. `/proc/net/dev` 读取网卡级计数器。
5. 采集器在内存中计算差值，并把不可变快照发送给 Textual UI。

## 相比 `tmd-top` 的变化

| 模块 | `netop` 取舍 |
| --- | --- |
| GeoIP | 移除 |
| SQLite | 移除 |
| IP 封禁 | 移除 |
| 包名 | `netop` |
| 命令行入口 | 只保留 `netop` |
| Textual 依赖 | `textual>=8.2,<9` |
| 运行模型 | 只读、内存快照 |

## 原仓库

原仓库 README：https://github.com/CDWEN0526/tmd-top

<img src="image/logo.png" alt="logo" style="zoom:100%;" />

------

# netop

[English README](README.md)

`netop` 是基于原 `tmd-top` 思路做的一次面向个人排障习惯的精简重构。
原仓库已经有一段时间没有持续演进，原实现把 GeoIP 查询、SQLite 快照表、
IP 封禁和 TUI 渲染放在一个应用里。本分支刻意收窄范围，只保留一个目标：
快速、只读、低开销的 Linux 终端网络监控。

## 重构设计

- 纯监控：移除 IP 封禁按钮，不写 iptables、nftables 或 firewalld。
- 无状态运行：不使用 SQLite，不保存历史流量数据。
- 移除 GeoIP：不携带 MMDB 数据库，不显示地区列，不做每个 IP 的地理查询。
- 轻量采样：通过 `ss` 读取 TCP socket 计数器，通过 `ps` 读取进程元数据，
  通过 `/proc/net/dev` 读取网卡计数器。
- 内存差值：仅保留上一轮和当前轮快照，使用 `time.monotonic()` 按真实采样
  间隔计算速率。
- 现代 Textual 路线：只使用公开 API，依赖改为 `textual>=8.2,<9`，不再锁死
  `textual==1.0.0`。

## 当前状态

这是早期重构分支。核心包名已经改为 `netop`，命令行入口只保留 `netop`，
不再兼容旧的 `tmd` / `tmd-top` 命令。

## 环境要求

- Python >= 3.10
- Linux
- `iproute2`，用于提供 `ss`
- `procps`，用于提供 `ps`

## 本地安装

```shell
python -m pip install -e .
```

## 使用

```shell
netop
```

## 快捷键

| 快捷键 | 功能 |
| --- | --- |
| `q` | 退出 |
| `v` | 聚焦搜索 |
| `b` | 切换 bit/byte 速率单位 |
| `t` | 慢刷新，5 秒 |
| `y` | 快刷新，1 秒 |
| `c` | 按连接数排序 |
| `i` | 按 IP 数排序 |
| `u` | 按上传排序 |
| `d` | 按下载排序 |
| `z` | 按 CPU 排序 |
| `x` | 按内存排序 |

## 显示单位

默认使用 `Kb/s`、`Mb/s` 这类 bit 速率显示网络带宽。按 `b` 可以切换为
`KB/s`、`MB/s` 这类字节速率。

## 数据流

1. `ss -tniH state established` 读取 TCP socket 计数器。
2. `ss -tpanH` 读取监听 socket、已建立连接、PID 和可用的进程名。
3. `ps` 读取 PID 对应的轻量 CPU/内存元数据。
4. `/proc/net/dev` 读取网卡级计数器。
5. 采集器在内存中计算差值，并把不可变快照发送给 Textual UI。

## 原仓库

原仓库 README：https://github.com/CDWEN0526/tmd-top

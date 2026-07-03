<img src="image/logo.png" alt="logo" style="zoom:100%;" />

------

# netop

[中文说明](README-CN.md)

`netop` is a focused rewrite of the original `tmd-top` idea for my own
day-to-day Linux network troubleshooting workflow. The upstream project has not
seen active feature work for a while, and its original design bundled GeoIP
lookup, SQLite snapshot tables, and firewall mutation into one TUI application.
This fork intentionally narrows the scope to one job: fast, read-only terminal
network monitoring.

## Refactor Design

- Pure monitoring: no IP ban button, no iptables/nftables/firewalld writes.
- Stateless runtime: no SQLite database and no persistent traffic history.
- No GeoIP: no bundled MMDB file, no location column, no per-IP lookup cost.
- Lightweight sampling: read TCP socket counters from `ss`, process metadata
  from `ps`, and interface counters from `/proc/net/dev`.
- In-memory deltas: keep only the previous and current snapshots, then calculate
  rates with `time.monotonic()` to account for real sampling intervals.
- Modern Textual path: use public Textual APIs and allow `textual>=8.2,<9`
  instead of pinning to `textual==1.0.0`.

## Current Status

This is an early refactor branch. The core package has been renamed to
`netop`, the CLI command is now only `netop`, and compatibility with the old
`tmd` / `tmd-top` command names is intentionally not preserved.

## Requirements

- Python >= 3.10
- Linux
- `iproute2` for `ss`
- `procps` for `ps`

## Install From Source

```shell
python -m pip install -e .
```

## Usage

```shell
netop
```

## Shortcuts

| Key | Action |
| --- | --- |
| `q` | Quit |
| `v` | Focus search |
| `b` | Toggle bit/byte rate mode |
| `t` | Slow refresh to 5 seconds |
| `y` | Restore refresh to 1 second |
| `c` | Sort by connections |
| `i` | Sort by unique IP count |
| `u` | Sort by upload |
| `d` | Sort by download |
| `z` | Sort by CPU |
| `x` | Sort by memory |

## Display Units

By default, `netop` displays network rates as bit rates such as `Kb/s` and
`Mb/s`. Press `b` to switch to byte-rate mode such as `KB/s` and `MB/s`.

## Data Flow

1. `ss -tniH state established` reads TCP socket counters.
2. `ss -tpanH` reads listening sockets, established sockets, PIDs, and process
   names when available.
3. `ps` provides lightweight CPU and memory metadata by PID.
4. `/proc/net/dev` provides interface-level counters.
5. The collector computes deltas in memory and sends immutable snapshots to the
   Textual UI.

## Original Project

Original repository README: https://github.com/CDWEN0526/tmd-top

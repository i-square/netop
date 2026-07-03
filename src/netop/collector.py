from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
import re
from shutil import which
import subprocess
import time
from pathlib import Path


LOCAL_BIND_IPS = {"0.0.0.0", "::", "*"}


@dataclass(frozen=True)
class ConnKey:
    local_ip: str
    local_port: str
    remote_ip: str
    remote_port: str


@dataclass(frozen=True)
class ConnCounters:
    key: ConnKey
    bytes_acked: int
    bytes_received: int


@dataclass(frozen=True)
class NetEntry:
    key: ConnKey
    state: str
    pid: str
    program: str


@dataclass(frozen=True)
class ProcInfo:
    pid: str
    cpu: float
    mem: float
    command: str


@dataclass(frozen=True)
class ConnRate:
    key: ConnKey
    upload: float
    download: float
    pid: str
    program: str


@dataclass(frozen=True)
class InterfaceRate:
    name: str
    upload: float
    download: float


@dataclass(frozen=True)
class ServiceSummary:
    row_id: str
    pid: str
    program: str
    bind_ip: str
    bind_port: str
    unique_ips: int
    connections: int
    upload: float
    download: float
    cpu: float
    mem: float


@dataclass(frozen=True)
class ProcessSummary:
    row_id: str
    pid: str
    program: str
    unique_ips: int
    connections: int
    upload: float
    download: float
    cpu: float
    mem: float


@dataclass(frozen=True)
class DetailSummary:
    row_id: str
    remote_ip: str
    remote_port: str
    upload: float
    download: float


@dataclass(frozen=True)
class MonitorSnapshot:
    interfaces: tuple[InterfaceRate, ...]
    services: tuple[ServiceSummary, ...]
    processes: tuple[ProcessSummary, ...]
    service_details: dict[str, tuple[DetailSummary, ...]]
    process_details: dict[str, tuple[DetailSummary, ...]]
    captured_at: float


def run_command(command: list[str]) -> str:
    executable = resolve_command(command[0])
    if executable is None:
        return ""
    command = [executable, *command[1:]]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout


@lru_cache(maxsize=16)
def resolve_command(name: str) -> str | None:
    resolved = which(name)
    if resolved:
        return resolved
    for parent in ("/usr/sbin", "/sbin", "/usr/bin", "/bin"):
        candidate = Path(parent) / name
        if candidate.exists():
            return str(candidate)
    return None


def split_endpoint(value: str) -> tuple[str, str]:
    value = value.strip()
    if value.startswith("[") and "]:" in value:
        ip, port = value[1:].rsplit("]:", 1)
    elif ":" in value:
        ip, port = value.rsplit(":", 1)
    else:
        return value, ""
    if ip.startswith("::ffff:"):
        ip = ip.removeprefix("::ffff:")
    return ip.strip("[]"), port


def parse_connection_counters(output: str) -> dict[ConnKey, ConnCounters]:
    counters: dict[ConnKey, ConnCounters] = {}
    pending_key: ConnKey | None = None

    for line in output.splitlines():
        if not line.strip():
            continue

        if line[:1].isspace():
            if pending_key is None:
                continue
            acked = _extract_int(line, "bytes_acked")
            received = _extract_int(line, "bytes_received")
            counters[pending_key] = ConnCounters(pending_key, acked, received)
            pending_key = None
            continue

        if pending_key is not None:
            counters[pending_key] = ConnCounters(pending_key, 0, 0)

        parts = line.split()
        if len(parts) < 4:
            pending_key = None
            continue
        local_ip, local_port = split_endpoint(parts[2])
        remote_ip, remote_port = split_endpoint(parts[3])
        if local_port and remote_port:
            pending_key = ConnKey(local_ip, local_port, remote_ip, remote_port)
        else:
            pending_key = None

    if pending_key is not None:
        counters[pending_key] = ConnCounters(pending_key, 0, 0)
    return counters


def parse_net_entries(output: str) -> tuple[NetEntry, ...]:
    entries: list[NetEntry] = []
    for line in output.splitlines():
        if not line.strip() or line[:1].isspace():
            continue

        parts = line.split(None, 5)
        if len(parts) < 5:
            continue

        state = "ESTABLISHED" if parts[0] == "ESTAB" else parts[0]
        local_ip, local_port = split_endpoint(parts[3])
        remote_ip, remote_port = split_endpoint(parts[4])
        process_text = parts[5] if len(parts) > 5 else ""
        program, pid = parse_process_field(process_text)
        if local_port:
            entries.append(
                NetEntry(
                    ConnKey(local_ip, local_port, remote_ip, remote_port),
                    state,
                    pid,
                    program,
                )
            )
    return tuple(entries)


def parse_process_field(value: str) -> tuple[str, str]:
    match = re.search(r'\("([^"]+)",pid=(\d+)', value)
    if match:
        return match.group(1), match.group(2)
    return "-", "-"


def read_process_table() -> dict[str, ProcInfo]:
    output = run_command(["ps", "-eo", "pid=,pcpu=,pmem=,comm="])
    processes: dict[str, ProcInfo] = {}
    for line in output.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 4:
            continue
        pid, cpu, mem, command = parts
        try:
            processes[pid] = ProcInfo(pid, float(cpu), float(mem), command)
        except ValueError:
            continue
    return processes


def read_interface_counters(path: Path = Path("/proc/net/dev")) -> dict[str, tuple[int, int]]:
    counters: dict[str, tuple[int, int]] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return counters

    for line in lines[2:]:
        if ":" not in line:
            continue
        name, raw_values = line.split(":", 1)
        values = raw_values.split()
        if len(values) < 16:
            continue
        receive_bytes = int(values[0])
        transmit_bytes = int(values[8])
        counters[name.strip()] = (transmit_bytes, receive_bytes)
    return counters


def format_rate(bytes_per_second: float, byte_mode: bool = False) -> str:
    if byte_mode:
        value = max(bytes_per_second, 0.0)
        units = ("B/s", "KB/s", "MB/s", "GB/s", "TB/s")
        factor = 1024.0
    else:
        value = max(bytes_per_second * 8.0, 0.0)
        units = ("b/s", "Kb/s", "Mb/s", "Gb/s", "Tb/s")
        factor = 1000.0

    for unit in units:
        if value < factor:
            return f"{value:.2f} {unit}"
        value /= factor
    return f"{value:.2f} {units[-1]}"


class NetCollector:
    def __init__(self) -> None:
        self._previous_connections: dict[ConnKey, ConnCounters] = {}
        self._previous_interfaces: dict[str, tuple[int, int]] = {}
        self._previous_time: float | None = None

    def collect(self) -> MonitorSnapshot:
        now = time.monotonic()
        current_connections = parse_connection_counters(
            run_command(["ss", "-tniH", "state", "established"])
        )
        net_entries = parse_net_entries(run_command(["ss", "-tpanH"]))
        processes = read_process_table()
        current_interfaces = read_interface_counters()

        interval = self._interval(now)
        connection_rates = self._connection_rates(
            current_connections,
            net_entries,
            processes,
            interval,
        )
        interface_rates = self._interface_rates(current_interfaces, interval)
        services, processes_summary, service_details, process_details = self._aggregate(
            connection_rates,
            net_entries,
            processes,
        )

        self._previous_connections = current_connections
        self._previous_interfaces = current_interfaces
        self._previous_time = now

        return MonitorSnapshot(
            interfaces=tuple(sorted(interface_rates, key=lambda item: item.name)),
            services=tuple(sorted(services, key=lambda item: item.upload + item.download, reverse=True)),
            processes=tuple(sorted(processes_summary, key=lambda item: item.upload + item.download, reverse=True)),
            service_details=service_details,
            process_details=process_details,
            captured_at=now,
        )

    def _interval(self, now: float) -> float | None:
        if self._previous_time is None:
            return None
        return max(now - self._previous_time, 0.001)

    def _connection_rates(
        self,
        current_connections: dict[ConnKey, ConnCounters],
        net_entries: tuple[NetEntry, ...],
        processes: dict[str, ProcInfo],
        interval: float | None,
    ) -> tuple[ConnRate, ...]:
        entry_by_key = {entry.key: entry for entry in net_entries if entry.state == "ESTABLISHED"}
        rates: list[ConnRate] = []

        for key, current in current_connections.items():
            previous = self._previous_connections.get(key)
            upload = 0.0
            download = 0.0
            if previous is not None and interval is not None:
                upload = max(current.bytes_acked - previous.bytes_acked, 0) / interval
                download = max(current.bytes_received - previous.bytes_received, 0) / interval

            entry = entry_by_key.get(key)
            pid = entry.pid if entry else "-"
            program = entry.program if entry else "-"
            if pid in processes and program == "-":
                program = processes[pid].command

            rates.append(ConnRate(key, upload, download, pid, program))
        return tuple(rates)

    def _interface_rates(
        self,
        current_interfaces: dict[str, tuple[int, int]],
        interval: float | None,
    ) -> tuple[InterfaceRate, ...]:
        rates: list[InterfaceRate] = []
        for name, (current_tx, current_rx) in current_interfaces.items():
            previous = self._previous_interfaces.get(name)
            upload = 0.0
            download = 0.0
            if previous is not None and interval is not None:
                previous_tx, previous_rx = previous
                upload = max(current_tx - previous_tx, 0) / interval
                download = max(current_rx - previous_rx, 0) / interval
            rates.append(InterfaceRate(name, upload, download))
        return tuple(rates)

    def _aggregate(
        self,
        connection_rates: tuple[ConnRate, ...],
        net_entries: tuple[NetEntry, ...],
        processes: dict[str, ProcInfo],
    ) -> tuple[
        list[ServiceSummary],
        list[ProcessSummary],
        dict[str, tuple[DetailSummary, ...]],
        dict[str, tuple[DetailSummary, ...]],
    ]:
        listen_entries = [entry for entry in net_entries if entry.state == "LISTEN"]
        listens_by_port: dict[str, list[NetEntry]] = defaultdict(list)
        for entry in listen_entries:
            listens_by_port[entry.key.local_port].append(entry)

        service_groups: dict[str, list[ConnRate]] = defaultdict(list)
        process_groups: dict[str, list[ConnRate]] = defaultdict(list)

        for rate in connection_rates:
            listen = match_listen(rate.key.local_ip, listens_by_port.get(rate.key.local_port, []))
            if listen:
                service_groups[service_row_id(listen)].append(rate)
            else:
                process_groups[rate.pid].append(rate)

        service_by_id = {service_row_id(entry): entry for entry in listen_entries}
        services = [
            build_service_summary(row_id, service_by_id[row_id], rates, processes)
            for row_id, rates in service_groups.items()
            if row_id in service_by_id
        ]
        processes_summary = [
            build_process_summary(pid, rates, processes)
            for pid, rates in process_groups.items()
        ]

        service_details = {
            row_id: build_details(rates)
            for row_id, rates in service_groups.items()
        }
        process_details = {
            pid: build_details(rates)
            for pid, rates in process_groups.items()
        }
        return services, processes_summary, service_details, process_details


def _extract_int(value: str, key: str) -> int:
    match = re.search(rf"\b{re.escape(key)}:(\d+)", value)
    if not match:
        return 0
    return int(match.group(1))


def match_listen(local_ip: str, candidates: list[NetEntry]) -> NetEntry | None:
    if not candidates:
        return None
    for entry in candidates:
        if entry.key.local_ip == local_ip:
            return entry
    for entry in candidates:
        if entry.key.local_ip in LOCAL_BIND_IPS:
            return entry
    return candidates[0]


def service_row_id(entry: NetEntry) -> str:
    return f"svc:{entry.pid}:{entry.key.local_ip}:{entry.key.local_port}"


def build_service_summary(
    row_id: str,
    entry: NetEntry,
    rates: list[ConnRate],
    processes: dict[str, ProcInfo],
) -> ServiceSummary:
    proc = processes.get(entry.pid)
    return ServiceSummary(
        row_id=row_id,
        pid=entry.pid,
        program=entry.program if entry.program != "-" else proc.command if proc else "-",
        bind_ip=entry.key.local_ip,
        bind_port=entry.key.local_port,
        unique_ips=len({rate.key.remote_ip for rate in rates}),
        connections=len(rates),
        upload=sum(rate.upload for rate in rates),
        download=sum(rate.download for rate in rates),
        cpu=proc.cpu if proc else 0.0,
        mem=proc.mem if proc else 0.0,
    )


def build_process_summary(
    pid: str,
    rates: list[ConnRate],
    processes: dict[str, ProcInfo],
) -> ProcessSummary:
    proc = processes.get(pid)
    program = proc.command if proc else next((rate.program for rate in rates if rate.program != "-"), "-")
    return ProcessSummary(
        row_id=pid,
        pid=pid,
        program=program,
        unique_ips=len({rate.key.remote_ip for rate in rates}),
        connections=len(rates),
        upload=sum(rate.upload for rate in rates),
        download=sum(rate.download for rate in rates),
        cpu=proc.cpu if proc else 0.0,
        mem=proc.mem if proc else 0.0,
    )


def build_details(rates: list[ConnRate]) -> tuple[DetailSummary, ...]:
    rows = [
        DetailSummary(
            row_id=f"{rate.key.remote_ip}:{rate.key.remote_port}:{index}",
            remote_ip=rate.key.remote_ip,
            remote_port=rate.key.remote_port,
            upload=rate.upload,
            download=rate.download,
        )
        for index, rate in enumerate(rates)
    ]
    return tuple(sorted(rows, key=lambda item: item.upload + item.download, reverse=True))

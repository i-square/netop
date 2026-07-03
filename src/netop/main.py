from __future__ import annotations

from enum import Enum

from textual import work
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Header, Input, Log, Static

from netop.collector import (
    DetailSummary,
    InterfaceRate,
    MonitorSnapshot,
    NetCollector,
    ProcessSummary,
    ServiceSummary,
    format_rate,
)


class SortKey(str, Enum):
    TRAFFIC = "traffic"
    CONNECTIONS = "connections"
    UNIQUE_IPS = "unique_ips"
    UPLOAD = "upload"
    DOWNLOAD = "download"
    CPU = "cpu"
    MEM = "mem"


class DetailMode(str, Enum):
    SERVICE = "service"
    PROCESS = "process"


class NetopApp(App):
    CSS = """
    Screen {
        layout: grid;
        grid-size: 4 3;
        grid-columns: 20% 40% 30% 10%;
        grid-rows: 45% 45% 10%;
    }

    Header {
        height: 1;
    }

    .box {
        height: 100%;
        border: solid #00BFFF;
        padding: 0 1;
    }

    .box:focus, #search:focus {
        border: solid green;
    }

    #network {
        width: 100%;
    }

    #services {
        row-span: 1;
    }

    #processes {
        row-span: 1;
    }

    #details {
        column-span: 2;
        row-span: 2;
    }

    #log {
        row-span: 1;
    }

    #status {
        row-span: 1;
    }

    #search {
        column-span: 3;
        height: 100%;
        border: solid #f36c21;
        padding: 0 1;
    }
    """

    BINDINGS = [
        ("q", "quit", "退出"),
        ("v", "focus_search", "搜索"),
        ("b", "toggle_rate_mode", "bit/byte"),
        ("t", "slow_refresh", "慢刷新"),
        ("y", "fast_refresh", "快刷新"),
        ("c", "sort_connections", "连接排序"),
        ("i", "sort_unique_ips", "IP排序"),
        ("u", "sort_upload", "上传排序"),
        ("d", "sort_download", "下载排序"),
        ("z", "sort_cpu", "CPU排序"),
        ("x", "sort_mem", "内存排序"),
    ]

    ENABLE_COMMAND_PALETTE = False

    def __init__(self) -> None:
        super().__init__()
        self.collector = NetCollector()
        self.snapshot: MonitorSnapshot | None = None
        self.selected_detail: tuple[DetailMode, str] | None = None
        self.sort_key = SortKey.TRAFFIC
        self.refresh_interval = 1.0
        self.byte_mode = False
        self._timer = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield DataTable(id="network", classes="box")
        yield DataTable(id="services", classes="box")
        yield DataTable(id="details", classes="box")
        yield Log(id="log", classes="box", highlight=True)
        yield DataTable(id="processes", classes="box")
        yield Static("", id="status", classes="box")
        yield Input(placeholder="搜索 PID、程序名、端口、IP", id="search")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "netop"
        self._setup_tables()
        self.query_one("#log", Log).write_line(
            "netop: 纯监控模式。默认显示 Kb/s、Mb/s，按 b 切换字节模式。"
        )
        self._timer = self.set_interval(self.refresh_interval, self.request_update)
        self.request_update()

    def _setup_tables(self) -> None:
        network = self.query_one("#network", DataTable)
        network.border_title = "网卡"
        network.cursor_type = "row"
        network.add_columns("网卡", "上传", "下载")

        services = self.query_one("#services", DataTable)
        services.border_title = "监听服务"
        services.cursor_type = "row"
        services.add_columns("PID", "服务", "监听IP", "端口", "IP数", "连接", "上传", "下载", "CPU", "MEM")

        processes = self.query_one("#processes", DataTable)
        processes.border_title = "外连进程"
        processes.cursor_type = "row"
        processes.add_columns("PID", "进程", "IP数", "连接", "上传", "下载", "CPU", "MEM")

        details = self.query_one("#details", DataTable)
        details.border_title = "详情"
        details.cursor_type = "row"
        details.add_columns("客户端IP", "端口", "上传", "下载")

        self.query_one("#status", Static).border_title = "状态"
        self.query_one("#search", Input).border_title = "搜索"

    @work(thread=True, exclusive=True)
    def collect_update(self) -> None:
        try:
            snapshot = self.collector.collect()
        except Exception as exc:
            self.call_from_thread(self.report_error, exc)
            return
        self.call_from_thread(self.apply_snapshot, snapshot)

    def request_update(self) -> None:
        self.collect_update()

    def apply_snapshot(self, snapshot: MonitorSnapshot) -> None:
        self.snapshot = snapshot
        self.refresh_tables()

    def report_error(self, exc: Exception) -> None:
        self.query_one("#log", Log).write_line(f"采集失败: {exc}")

    def refresh_tables(self) -> None:
        if self.snapshot is None:
            return

        search = self.query_one("#search", Input).value.strip().lower()
        services = self._filter_services(self.snapshot.services, search)
        processes = self._filter_processes(self.snapshot.processes, search)
        interfaces = self._filter_interfaces(self.snapshot.interfaces, search)

        self._replace_table(
            "#network",
            [(row.name, format_rate(row.upload, self.byte_mode), format_rate(row.download, self.byte_mode)) for row in interfaces],
            [row.name for row in interfaces],
        )
        self._replace_table("#services", [self._service_row(row) for row in services], [row.row_id for row in services])
        self._replace_table("#processes", [self._process_row(row) for row in processes], [row.row_id for row in processes])
        self._refresh_details(search)
        self._refresh_status(len(interfaces), len(services), len(processes))

    def _refresh_details(self, search: str) -> None:
        details: tuple[DetailSummary, ...] = ()
        title = "详情"
        if self.snapshot is not None and self.selected_detail is not None:
            mode, row_id = self.selected_detail
            if mode is DetailMode.SERVICE:
                details = self.snapshot.service_details.get(row_id, ())
                title = f"服务详情 {row_id}"
            else:
                details = self.snapshot.process_details.get(row_id, ())
                title = f"进程详情 PID {row_id}"
        filtered = self._filter_details(details, search)
        rows = [
            (row.remote_ip, row.remote_port, format_rate(row.upload, self.byte_mode), format_rate(row.download, self.byte_mode))
            for row in filtered
        ]
        self._replace_table("#details", rows, [row.row_id for row in filtered])
        self.query_one("#details", DataTable).border_title = title

    def _replace_table(self, selector: str, rows: list[tuple[str, ...]], row_keys: list[str]) -> None:
        table = self.query_one(selector, DataTable)
        table.clear()
        for row, row_key in zip(rows, row_keys):
            table.add_row(*row, key=row_key)
        table.border_subtitle = f"总数 {len(rows)}"

    def _service_row(self, row: ServiceSummary) -> tuple[str, ...]:
        return (
            row.pid,
            row.program,
            row.bind_ip,
            row.bind_port,
            str(row.unique_ips),
            str(row.connections),
            format_rate(row.upload, self.byte_mode),
            format_rate(row.download, self.byte_mode),
            f"{row.cpu:.1f}%",
            f"{row.mem:.1f}%",
        )

    def _process_row(self, row: ProcessSummary) -> tuple[str, ...]:
        return (
            row.pid,
            row.program,
            str(row.unique_ips),
            str(row.connections),
            format_rate(row.upload, self.byte_mode),
            format_rate(row.download, self.byte_mode),
            f"{row.cpu:.1f}%",
            f"{row.mem:.1f}%",
        )

    def _filter_interfaces(self, rows: tuple[InterfaceRate, ...], search: str) -> list[InterfaceRate]:
        filtered = [row for row in rows if not search or search in row.name.lower()]
        return sorted(filtered, key=lambda item: item.upload + item.download, reverse=True)

    def _filter_services(self, rows: tuple[ServiceSummary, ...], search: str) -> list[ServiceSummary]:
        filtered = [
            row
            for row in rows
            if not search
            or search in row.pid.lower()
            or search in row.program.lower()
            or search in row.bind_ip.lower()
            or search in row.bind_port.lower()
        ]
        return sorted(filtered, key=self._summary_sort_value, reverse=True)

    def _filter_processes(self, rows: tuple[ProcessSummary, ...], search: str) -> list[ProcessSummary]:
        filtered = [
            row
            for row in rows
            if not search
            or search in row.pid.lower()
            or search in row.program.lower()
        ]
        return sorted(filtered, key=self._summary_sort_value, reverse=True)

    def _filter_details(self, rows: tuple[DetailSummary, ...], search: str) -> list[DetailSummary]:
        filtered = [
            row
            for row in rows
            if not search
            or search in row.remote_ip.lower()
            or search in row.remote_port.lower()
        ]
        return sorted(filtered, key=lambda item: item.upload + item.download, reverse=True)

    def _summary_sort_value(self, row: ServiceSummary | ProcessSummary) -> float:
        if self.sort_key is SortKey.CONNECTIONS:
            return float(row.connections)
        if self.sort_key is SortKey.UNIQUE_IPS:
            return float(row.unique_ips)
        if self.sort_key is SortKey.UPLOAD:
            return row.upload
        if self.sort_key is SortKey.DOWNLOAD:
            return row.download
        if self.sort_key is SortKey.CPU:
            return row.cpu
        if self.sort_key is SortKey.MEM:
            return row.mem
        return row.upload + row.download

    def _refresh_status(self, interfaces: int, services: int, processes: int) -> None:
        mode = "字节" if self.byte_mode else "bit"
        status = (
            f"刷新 {self.refresh_interval:.0f}s | 单位 {mode} | 排序 {self.sort_key.value}\n"
            f"网卡 {interfaces} | 服务 {services} | 进程 {processes}"
        )
        self.query_one("#status", Static).update(status)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_key = str(getattr(event.row_key, "value", event.row_key))
        table_id = event.data_table.id
        if table_id == "services":
            self.selected_detail = (DetailMode.SERVICE, row_key)
        elif table_id == "processes":
            self.selected_detail = (DetailMode.PROCESS, row_key)
        self.refresh_tables()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self.refresh_tables()

    def action_quit(self) -> None:
        self.exit()

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_toggle_rate_mode(self) -> None:
        self.byte_mode = not self.byte_mode
        self.refresh_tables()

    def action_slow_refresh(self) -> None:
        self.refresh_interval = 5.0
        self._reset_timer()

    def action_fast_refresh(self) -> None:
        self.refresh_interval = 1.0
        self._reset_timer()

    def action_sort_connections(self) -> None:
        self._set_sort(SortKey.CONNECTIONS)

    def action_sort_unique_ips(self) -> None:
        self._set_sort(SortKey.UNIQUE_IPS)

    def action_sort_upload(self) -> None:
        self._set_sort(SortKey.UPLOAD)

    def action_sort_download(self) -> None:
        self._set_sort(SortKey.DOWNLOAD)

    def action_sort_cpu(self) -> None:
        self._set_sort(SortKey.CPU)

    def action_sort_mem(self) -> None:
        self._set_sort(SortKey.MEM)

    def _set_sort(self, sort_key: SortKey) -> None:
        self.sort_key = sort_key
        self.refresh_tables()

    def _reset_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
        self._timer = self.set_interval(self.refresh_interval, self.request_update)
        self.refresh_tables()


def main() -> None:
    NetopApp().run()


if __name__ == "__main__":
    main()

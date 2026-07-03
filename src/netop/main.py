from __future__ import annotations

from enum import Enum

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import DataTable, Footer, Header, Input, Static

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
        grid-size: 5 5;
        grid-columns: 1fr 1fr 1fr 1fr 1fr;
        grid-rows: 7 1fr 1fr 3 1;
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
        column-span: 4;
    }

    #processes {
        column-span: 3;
        row-span: 2;
    }

    #details_panel {
        column-span: 2;
        row-span: 3;
        height: 100%;
        layout: vertical;
        border: solid #00BFFF;
        padding: 0 1;
    }

    #details_hint {
        height: auto;
        text-wrap: wrap;
        color: $text-muted;
    }

    #details {
        height: 1fr;
    }

    #status {
        column-span: 5;
        height: 100%;
        padding: 0 1;
        text-wrap: nowrap;
        background: #4A3B16;
        color: #F4E7B0;
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
        ("r", "sort_traffic", "流量排序"),
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
        self._suppress_table_events = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield DataTable(id="network", classes="box")
        yield DataTable(id="services", classes="box")
        yield DataTable(id="processes", classes="box")
        with Container(id="details_panel"):
            yield Static("", id="details_hint")
            yield DataTable(id="details")
        yield Input(placeholder="搜索 PID、进程、端口、IP", id="search")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "netop"
        self._setup_tables()
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

        details_panel = self.query_one("#details_panel", Container)
        details_panel.border_title = "连接详情"
        details_panel.border_subtitle = "等待选择"

        details = self.query_one("#details", DataTable)
        details.cursor_type = "row"
        details.add_columns("客户端IP", "端口", "上传", "下载")

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
        self.query_one("#status", Static).update(f"采集失败: {exc}")

    def refresh_tables(self) -> None:
        if self.snapshot is None:
            return

        search = self.query_one("#search", Input).value.strip().lower()
        services = self._filter_services(self.snapshot.services, search)
        processes = self._filter_processes(self.snapshot.processes, search)
        interfaces = self._filter_interfaces(self.snapshot.interfaces, search)
        self._ensure_visible_selection(services, processes)

        self._suppress_table_events = True
        try:
            self._replace_table(
                "#network",
                [(row.name, format_rate(row.upload, self.byte_mode), format_rate(row.download, self.byte_mode)) for row in interfaces],
                [row.name for row in interfaces],
            )
            self._replace_table(
                "#services",
                [self._service_row(row) for row in services],
                [row.row_id for row in services],
                self._selected_row_key(DetailMode.SERVICE),
            )
            self._replace_table(
                "#processes",
                [self._process_row(row) for row in processes],
                [row.row_id for row in processes],
                self._selected_row_key(DetailMode.PROCESS),
            )
            self._refresh_details(search)
            self._refresh_status(len(interfaces), len(services), len(processes))
        finally:
            self.call_after_refresh(self._resume_table_events)

    def _ensure_visible_selection(self, services: list[ServiceSummary], processes: list[ProcessSummary]) -> None:
        if self.selected_detail is not None:
            mode, row_id = self.selected_detail
            if mode is DetailMode.SERVICE and any(row.row_id == row_id for row in services):
                return
            if mode is DetailMode.PROCESS and any(row.row_id == row_id for row in processes):
                return
        if processes:
            self.selected_detail = (DetailMode.PROCESS, processes[0].row_id)
        elif services:
            self.selected_detail = (DetailMode.SERVICE, services[0].row_id)
        else:
            self.selected_detail = None

    def _selected_row_key(self, mode: DetailMode) -> str | None:
        if self.selected_detail is None:
            return None
        selected_mode, row_id = self.selected_detail
        if selected_mode is not mode:
            return None
        return row_id

    def _refresh_details(self, search: str) -> None:
        details: tuple[DetailSummary, ...] = ()
        title = "连接详情"
        hint = "提示：单击或双击左侧服务/进程 PID 行查看连接详情。"
        if self.snapshot is not None and self.selected_detail is not None:
            mode, row_id = self.selected_detail
            if mode is DetailMode.SERVICE:
                details = self.snapshot.service_details.get(row_id, ())
                title = f"服务详情 {row_id}"
            else:
                details = self.snapshot.process_details.get(row_id, ())
                title = f"进程详情 PID {row_id}"
            hint = "当前选择暂无连接详情。"
        filtered = self._filter_details(details, search)
        if details and not filtered:
            hint = "当前选择没有匹配的连接详情，可调整搜索条件。"
        rows = [
            (row.remote_ip, row.remote_port, format_rate(row.upload, self.byte_mode), format_rate(row.download, self.byte_mode))
            for row in filtered
        ]
        self._replace_details_table(rows, [row.row_id for row in filtered], title, hint)

    def _replace_table(
        self,
        selector: str,
        rows: list[tuple[str, ...]],
        row_keys: list[str],
        selected_row_key: str | None = None,
    ) -> None:
        table = self.query_one(selector, DataTable)
        self._set_table_rows(table, rows, row_keys, selected_row_key)
        table.border_subtitle = f"总数 {len(rows)}"

    def _set_table_rows(
        self,
        table: DataTable,
        rows: list[tuple[str, ...]],
        row_keys: list[str],
        selected_row_key: str | None = None,
    ) -> None:
        cursor_row_key = selected_row_key or self._current_table_row_key(table)
        table.clear()
        for row, row_key in zip(rows, row_keys):
            table.add_row(*row, key=row_key)
        self._restore_table_cursor(table, cursor_row_key)

    def _current_table_row_key(self, table: DataTable) -> str | None:
        if table.row_count == 0 or not table.is_valid_row_index(table.cursor_row):
            return None
        row_keys = list(table.rows.keys())
        if table.cursor_row >= len(row_keys):
            return None
        row_key = row_keys[table.cursor_row]
        return str(getattr(row_key, "value", row_key))

    def _restore_table_cursor(self, table: DataTable, row_key: str | None) -> None:
        if row_key in table.rows:
            table.move_cursor(row=table.get_row_index(row_key), animate=False)

    def _replace_details_table(
        self,
        rows: list[tuple[str, ...]],
        row_keys: list[str],
        title: str,
        hint: str,
    ) -> None:
        table = self.query_one("#details", DataTable)
        self._set_table_rows(table, rows, row_keys)

        details_panel = self.query_one("#details_panel", Container)
        details_panel.border_title = title
        details_panel.border_subtitle = f"总数 {len(rows)}"

        details_hint = self.query_one("#details_hint", Static)
        details_hint.update(hint)
        details_hint.display = not rows

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
        mode = "byte" if self.byte_mode else "bit"
        privilege = "root/sudo" if self.snapshot and self.snapshot.privileged else "普通用户"
        permission_hint = ""
        if self.snapshot and self.snapshot.permission_limited:
            permission_hint = " | PID受限"
        status = (
            f"刷新 {self.refresh_interval:.0f}s | 单位 {mode} | 排序 {self.sort_key.value} | 权限 {privilege} | "
            f"网卡 {interfaces} | 服务 {services} | 进程 {processes}"
            f"{permission_hint}"
        )
        self.query_one("#status", Static).update(status)

    def _resume_table_events(self) -> None:
        self._suppress_table_events = False

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._update_selected_detail(event.data_table.id, event.row_key)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._update_selected_detail(event.data_table.id, event.row_key)

    def _update_selected_detail(self, table_id: str | None, row_key: object) -> None:
        if self._suppress_table_events:
            return
        if table_id not in {"services", "processes"}:
            return
        row_key = str(getattr(row_key, "value", row_key))
        if row_key == "None":
            return
        if table_id == "services":
            selected_detail = (DetailMode.SERVICE, row_key)
        else:
            selected_detail = (DetailMode.PROCESS, row_key)
        if self.selected_detail == selected_detail:
            return
        self.selected_detail = selected_detail
        search = self.query_one("#search", Input).value.strip().lower()
        self._refresh_details(search)

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

    def action_sort_traffic(self) -> None:
        self._set_sort(SortKey.TRAFFIC)

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

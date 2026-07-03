import unittest

from netop.collector import DetailSummary, InterfaceRate, MonitorSnapshot, ProcessSummary, ServiceSummary
from netop.main import DetailMode, NetopApp, SortKey


class TestNetopApp(NetopApp):
    def request_update(self) -> None:
        pass


def build_snapshot(upload_100: float = 300.0, upload_200: float = 100.0) -> MonitorSnapshot:
    return MonitorSnapshot(
        interfaces=(
            InterfaceRate("eth0", upload_100, 0.0),
            InterfaceRate("lo", upload_200, 0.0),
        ),
        services=(
            ServiceSummary("svc-100", "100", "nginx", "0.0.0.0", "443", 1, 1, upload_100, 0.0, 0.0, 0.0),
            ServiceSummary("svc-200", "200", "sshd", "0.0.0.0", "22", 1, 1, upload_200, 0.0, 0.0, 0.0),
        ),
        processes=(
            ProcessSummary("100", "100", "curl", 1, 1, upload_100, 0.0, 0.0, 0.0),
            ProcessSummary("200", "200", "ssh", 1, 1, upload_200, 0.0, 0.0, 0.0),
        ),
        service_details={
            "svc-100": (
                DetailSummary("10.0.1.1:443", "10.0.1.1", "443", upload_100, 0.0),
                DetailSummary("10.0.1.2:443", "10.0.1.2", "443", upload_200, 0.0),
            ),
            "svc-200": (
                DetailSummary("10.0.2.1:22", "10.0.2.1", "22", upload_100, 0.0),
                DetailSummary("10.0.2.2:22", "10.0.2.2", "22", upload_200, 0.0),
            ),
        },
        process_details={
            "100": (DetailSummary("10.0.0.1:443", "10.0.0.1", "443", upload_100, 0.0),),
            "200": (DetailSummary("10.0.0.2:443", "10.0.0.2", "443", upload_200, 0.0),),
        },
        captured_at=1.0,
        privileged=True,
        permission_limited=False,
    )


class MainUiTest(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_preserves_all_table_cursors(self) -> None:
        app = TestNetopApp()
        async with app.run_test(size=(120, 40)) as pilot:
            app.apply_snapshot(build_snapshot())
            await pilot.pause()

            network = app.query_one("#network")
            services = app.query_one("#services")
            processes = app.query_one("#processes")
            details = app.query_one("#details")

            network.move_cursor(row=network.get_row_index("lo"), animate=False)
            processes.move_cursor(row=processes.get_row_index("200"), animate=False)
            await pilot.pause()

            app._update_selected_detail("services", "svc-200")
            await pilot.pause()
            details.move_cursor(row=details.get_row_index("10.0.2.2:22"), animate=False)

            app.apply_snapshot(build_snapshot(upload_100=400.0, upload_200=200.0))
            await pilot.pause()

            self.assertEqual(app.selected_detail, (DetailMode.SERVICE, "svc-200"))
            self.assertEqual(network.cursor_row, network.get_row_index("lo"))
            self.assertEqual(services.cursor_row, services.get_row_index("svc-200"))
            self.assertEqual(processes.cursor_row, processes.get_row_index("200"))
            self.assertEqual(details.cursor_row, details.get_row_index("10.0.2.2:22"))
            self.assertEqual(app.query_one("#details_panel").border_title, "服务详情 svc-200")
            self.assertEqual(details.row_count, 2)

    async def test_status_is_single_line(self) -> None:
        app = TestNetopApp()
        async with app.run_test(size=(120, 40)) as pilot:
            app.apply_snapshot(build_snapshot())
            await pilot.pause()
            status = str(app.query_one("#status").render())

        self.assertNotIn("\n", str(status))
        self.assertIn("单位 bit", str(status))

    async def test_default_interface_is_first_network_row(self) -> None:
        app = TestNetopApp()
        snapshot = MonitorSnapshot(
            interfaces=(
                InterfaceRate("br-0b2", 900.0, 0.0),
                InterfaceRate("eno1", 100.0, 0.0),
            ),
            services=(),
            processes=(),
            service_details={},
            process_details={},
            captured_at=1.0,
            privileged=True,
            permission_limited=False,
            default_interface="eno1",
        )
        async with app.run_test(size=(120, 40)) as pilot:
            app.apply_snapshot(snapshot)
            await pilot.pause()

            network = app.query_one("#network")

        self.assertEqual(network.get_row_index("eno1"), 0)
        self.assertEqual(network.cursor_row, 0)

    async def test_network_row_height_has_minimum_and_scales(self) -> None:
        for height, expected_network_height in ((24, 7), (40, 7), (60, 9)):
            with self.subTest(height=height):
                app = TestNetopApp()
                async with app.run_test(size=(120, height)) as pilot:
                    await pilot.pause()
                    network = app.query_one("#network")

                    self.assertEqual(network.region.height, expected_network_height)

    async def test_sort_traffic_action_restores_default_sort(self) -> None:
        app = TestNetopApp()
        async with app.run_test(size=(120, 40)) as pilot:
            app.apply_snapshot(build_snapshot())
            await pilot.pause()

            app.action_sort_cpu()
            self.assertEqual(app.sort_key, SortKey.CPU)

            app.action_sort_traffic()
            await pilot.pause()

        self.assertEqual(app.sort_key, SortKey.TRAFFIC)


if __name__ == "__main__":
    unittest.main()

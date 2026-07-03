import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from netop.collector import (
    ConnKey,
    NetCollector,
    ProcInfo,
    build_command,
    format_rate,
    has_unknown_process_owner,
    parse_connection_counters,
    parse_net_entries,
    read_default_interface,
    split_endpoint,
)


class CollectorParsingTest(unittest.TestCase):
    def test_parse_connection_counters(self) -> None:
        output = """0 0 10.0.0.1:443 1.2.3.4:50000
     cubic bytes_acked:2048 bytes_received:1024
0 0 10.0.0.1:22 5.6.7.8:51000
     cubic bytes_acked:4096 bytes_received:2048
"""

        counters = parse_connection_counters(output)

        key = ConnKey("10.0.0.1", "443", "1.2.3.4", "50000")
        self.assertEqual(counters[key].bytes_acked, 2048)
        self.assertEqual(counters[key].bytes_received, 1024)

    def test_parse_net_entries(self) -> None:
        output = """LISTEN 0 511 0.0.0.0:443 0.0.0.0:* users:(("nginx",pid=100,fd=6))
ESTAB 0 0 10.0.0.1:443 1.2.3.4:50000 users:(("nginx",pid=100,fd=7))
"""

        entries = parse_net_entries(output)

        self.assertEqual(entries[0].state, "LISTEN")
        self.assertEqual(entries[0].pid, "100")
        self.assertEqual(entries[0].program, "nginx")
        self.assertEqual(entries[1].state, "ESTABLISHED")

    def test_split_endpoint_ipv6(self) -> None:
        self.assertEqual(split_endpoint("[::1]:8080"), ("::1", "8080"))
        self.assertEqual(split_endpoint("::ffff:127.0.0.1:8080"), ("127.0.0.1", "8080"))

    def test_format_rate_defaults_to_bits(self) -> None:
        self.assertEqual(format_rate(125000), "1.00 Mb/s")
        self.assertEqual(format_rate(1024, byte_mode=True), "1.00 KB/s")

    def test_build_command_adds_non_interactive_sudo(self) -> None:
        with (
            patch("netop.collector.os.geteuid", return_value=1000),
            patch("netop.collector.resolve_command", return_value="/usr/bin/sudo"),
        ):
            command = build_command("/usr/bin/ss", ["-tpanH"], use_sudo=True)

        self.assertEqual(command, ["/usr/bin/sudo", "-n", "/usr/bin/ss", "-tpanH"])

    def test_unknown_process_owner_is_permission_limited(self) -> None:
        entries = parse_net_entries("ESTAB 0 0 10.0.0.1:443 1.2.3.4:50000\n")

        self.assertTrue(has_unknown_process_owner(entries))

    def test_read_default_interface_uses_lowest_metric_default_route(self) -> None:
        content = """Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT
br-0b2 00000000 010011AC 0003 0 0 100 00000000 0 0 0
eno1 00000000 010011AC 0003 0 0 10 00000000 0 0 0
docker0 0011AC0A 00000000 0001 0 0 0 00FFFFFF 0 0 0
"""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "route"
            path.write_text(content, encoding="utf-8")

            self.assertEqual(read_default_interface(path), "eno1")

    def test_collector_uses_in_memory_deltas(self) -> None:
        ss_counters = [
            """0 0 10.0.0.1:443 1.2.3.4:50000
     cubic bytes_acked:1000 bytes_received:2000
""",
            """0 0 10.0.0.1:443 1.2.3.4:50000
     cubic bytes_acked:3000 bytes_received:5000
""",
        ]
        ss_net = """LISTEN 0 511 0.0.0.0:443 0.0.0.0:* users:(("nginx",pid=100,fd=6))
ESTAB 0 0 10.0.0.1:443 1.2.3.4:50000 users:(("nginx",pid=100,fd=7))
"""
        interfaces = [
            {"eth0": (1000, 2000)},
            {"eth0": (3000, 7000)},
        ]
        commands = [ss_counters[0], ss_net, ss_counters[1], ss_net]

        with (
            patch("netop.collector.run_command", side_effect=commands),
            patch("netop.collector.read_process_table", return_value={"100": ProcInfo("100", 1.0, 2.0, "nginx")}),
            patch("netop.collector.read_interface_counters", side_effect=interfaces),
            patch("netop.collector.time.monotonic", side_effect=[10.0, 12.0]),
            patch("netop.collector.os.geteuid", return_value=1000),
        ):
            collector = NetCollector(use_sudo=False)
            collector.collect()
            snapshot = collector.collect()

        self.assertEqual(len(snapshot.services), 1)
        self.assertEqual(snapshot.services[0].upload, 1000.0)
        self.assertEqual(snapshot.services[0].download, 1500.0)
        self.assertEqual(snapshot.interfaces[0].upload, 1000.0)
        self.assertEqual(snapshot.interfaces[0].download, 2500.0)
        self.assertFalse(snapshot.privileged)
        self.assertFalse(snapshot.permission_limited)


if __name__ == "__main__":
    unittest.main()

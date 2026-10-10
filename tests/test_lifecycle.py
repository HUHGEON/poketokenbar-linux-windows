"""A stopped daemon must recover, while an existing worker is left alone."""

import tempfile
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from poketokenbar import lifecycle
from poketokenbar.single_instance import SingleInstance


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        lifecycle._last_launch = float("-inf")
        self.addCleanup(setattr, lifecycle, "_last_launch", float("-inf"))

    def test_stopped_worker_starts_once_during_startup_grace_period(self):
        with patch.object(lifecycle, "SingleInstance") as instance, \
                patch.object(lifecycle, "launch_module") as launch:
            instance.return_value.acquire.return_value = True
            self.assertTrue(lifecycle.ensure_daemon())
            self.assertFalse(lifecycle.ensure_daemon())
            instance.return_value.release.assert_called_once()
            launch.assert_called_once_with("poketokenbar.daemon")

    def test_live_worker_lock_prevents_duplicate_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            suffix = uuid.uuid4().hex
            factory = lambda name: SingleInstance(name + suffix, system=sys.platform, directory=Path(directory))
            live = factory("daemon")
            self.assertTrue(live.acquire())
            try:
                with patch.object(lifecycle, "SingleInstance", side_effect=factory), \
                        patch.object(lifecycle, "launch_module") as launch:
                    self.assertFalse(lifecycle.ensure_daemon())
                    launch.assert_not_called()
                    live.release()
                    self.assertTrue(lifecycle.ensure_daemon())
                    launch.assert_called_once()
            finally:
                live.release()

    def test_refresh_queues_before_worker_recovery(self):
        calls = []
        with patch.object(lifecycle.commands, "enqueue", side_effect=lambda *args: calls.append("queue")), \
                patch.object(lifecycle, "ensure_daemon", side_effect=lambda: calls.append("recover")):
            lifecycle.refresh_data()
        self.assertEqual(calls, ["queue", "recover"])

    def test_worker_launch_keeps_errors_and_uses_current_package(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(lifecycle.platform_paths, "state_base", return_value=Path(directory)), \
                patch.object(lifecycle.subprocess, "Popen") as popen:
            lifecycle.launch_module("poketokenbar.daemon")
            args, kwargs = popen.call_args
            self.assertEqual(args[0][-2:], ["-m", "poketokenbar.daemon"])
            self.assertEqual(kwargs["env"]["PYTHONPATH"].split(lifecycle.os.pathsep)[0], str(kwargs["cwd"]))
            self.assertTrue((Path(directory) / "poketokenbar/daemon.stderr.log").exists())

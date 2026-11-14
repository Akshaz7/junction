"""Installer checks without requiring Xcode, network access, or an attached phone."""

from contextlib import redirect_stdout
import importlib.util
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("installer", Path(__file__).with_name("install_on_device.py"))
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def test_only_connected_paired_iphones_are_selected_in_both_json_formats(self):
        hardware = {"deviceType": "iPhone", "udid": "phone-udid"}
        connection = {"pairingState": "paired", "tunnelState": "connected"}
        old = {"hardwareProperties": hardware, "connectionProperties": connection,
               "deviceProperties": {"name": "Demo iPhone"}}
        new = {"properties": {"hardware": hardware, "connection": connection,
                              "device": {"name": "Demo iPhone"}}}
        for device in [old, new]:
            self.assertEqual(installer.connected_iphones({"result": {"devices": [device]}}),
                             [("phone-udid", "Demo iPhone")])
        offline = dict(old, connectionProperties=dict(connection, tunnelState="disconnected"),
                       properties={"state": {"availability": "unavailable"}})
        unpaired = dict(old, connectionProperties=dict(connection, pairingState="unpaired"))
        ipad = dict(old, hardwareProperties=dict(hardware, deviceType="iPad"))
        self.assertEqual(installer.connected_iphones({"result": {"devices": [offline, unpaired, ipad]}}), [])

    def test_saved_sample_selects_wifi_and_available_paired_phones_excluding_simulators(self):
        sample = json.loads((Path(__file__).parent / "fixtures/devices.json").read_text())
        self.assertEqual(installer.connected_iphones(sample), [
            ("00000000-0000000000000001", "Demo iPhone over Wi-Fi"),
            ("00000000-0000000000000002", "Demo available iPhone"),
        ])

    def test_discovery_reads_json_and_dry_run_reports_phone_without_building(self):
        sample = (Path(__file__).parent / "fixtures/devices.json").read_text()

        def device_list(command, **kwargs):
            self.assertEqual(command[:4], ["xcrun", "devicectl", "list", "devices"])
            Path(command[command.index("--json-output") + 1]).write_text(sample)
            return installer.subprocess.CompletedProcess(command, 0)

        output = StringIO()
        with patch.object(installer, "settings", return_value=("AAAAAAAAAA", "com.example.demo", None, None)), \
             patch.object(installer.subprocess, "run", side_effect=device_list) as commands, \
             patch.object(installer, "run") as run, redirect_stdout(output):
            self.assertEqual(installer.main(["--dry-run", "--device", "00000000-0000000000000001"]), 0)
            commands.assert_called_once()
            run.assert_not_called()
        self.assertIn("Connected paired iPhone: Demo iPhone over Wi-Fi", output.getvalue())
        self.assertIn("Destination: id=00000000-0000000000000001", output.getvalue())
        self.assertIn("no build, install, or launch performed", output.getvalue())

    def test_whitelist_reads_literals_without_executing_or_exposing_other_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text('UNRELATED_SECRET="private"\nexport WEB_URL="https://demo.test" # comment\n'
                            'API_URL="$(touch never-execute)"\n')
            self.assertEqual(installer.read_settings(path, installer.SETTING_KEYS),
                             {"WEB_URL": "https://demo.test", "API_URL": "$(touch never-execute)"})

    def test_no_phone_and_connected_dry_runs_never_build(self):
        with patch.object(installer, "settings", return_value=("AAAAAAAAAA", "com.example.demo", None, None)), \
             patch.object(installer, "run") as run, redirect_stdout(StringIO()):
            with patch.object(installer, "discover_device", return_value=([], True)):
                self.assertEqual(installer.main(["--dry-run"]), 0)
                self.assertEqual(installer.main([]), 1)
            with patch.object(installer, "discover_device", return_value=([("phone", "iPhone")], True)):
                self.assertEqual(installer.main(["--dry-run"]), 0)
            run.assert_not_called()

    def test_build_install_launch_use_same_device_and_launch_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            ios = Path(directory)
            (ios / "build/DerivedData/Build/Products/Debug-iphoneos/Hologram.app").mkdir(parents=True)
            with patch.object(installer, "IOS", ios), \
                 patch.object(installer, "settings", return_value=("AAAAAAAAAA", "com.example.demo", "http://10.0.0.2:4173", "http://10.0.0.2:8000")), \
                 patch.object(installer, "discover_device", return_value=([("phone-udid", "iPhone")], True)), \
                 patch.object(installer, "run") as run, redirect_stdout(StringIO()):
                self.assertEqual(installer.main([]), 0)
                generate, build, install, launch = [call.args[0] for call in run.call_args_list]
                self.assertEqual(generate[0], "xcodegen")
                self.assertEqual(build[:3], ["bash", installer.ROOT / "scripts/heavy.sh", "xcodebuild"])
                self.assertIn("id=phone-udid", build)
                self.assertIn("-allowProvisioningUpdates", build)
                self.assertIn("CODE_SIGN_STYLE=Automatic", build)
                self.assertEqual(install[6], "phone-udid")
                self.assertEqual(launch[-7:], ["--terminate-existing", "com.example.demo", "--", "-WEB_URL", "http://10.0.0.2:4173", "-API_URL", "http://10.0.0.2:8000"])

    def test_generic_build_does_not_require_device_or_lan(self):
        with patch.object(installer, "settings", return_value=("AAAAAAAAAA", "com.example.demo", None, None)), \
             patch.object(installer, "discover_device") as discover, \
             patch.object(installer, "run") as run, redirect_stdout(StringIO()):
            self.assertEqual(installer.main(["--build-only"]), 0)
            discover.assert_not_called()
            self.assertIn("generic/platform=iOS", run.call_args_list[-1].args[0])

    def test_deployed_and_lan_url_defaults_and_explicit_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ios/Config").mkdir(parents=True)
            (root / ".env").write_text('APPLE_TEAM_ID=AAAAAAAAAA\nDEPLOY_WEB_URL=https://web.example.test\nDEPLOY_API_URL=https://api.example.test\n')
            with patch.object(installer, "ROOT", root), patch.object(installer, "IOS", root / "ios"), \
                 patch.dict(installer.os.environ, {}, clear=True):
                self.assertEqual(installer.settings()[2:], ("https://web.example.test", "https://api.example.test"))
                (root / ".env").write_text('APPLE_TEAM_ID=AAAAAAAAAA\n')
                with patch.object(installer.subprocess, "run") as run:
                    run.return_value.returncode = 0
                    run.return_value.stdout = "10.0.0.2\n"
                    self.assertEqual(installer.settings()[2:], ("http://10.0.0.2:4173", "http://10.0.0.2:8000"))
                with patch.dict(installer.os.environ, {"WEB_URL": "https://web.override.test", "API_URL": "https://api.override.test"}):
                    self.assertEqual(installer.settings()[2:], ("https://web.override.test", "https://api.override.test"))


if __name__ == "__main__":
    unittest.main()

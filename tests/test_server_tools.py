import json
import os
import tempfile
import unittest
from unittest import mock

import numpy as np
import soundfile as sf

from MCP_Server import server


ROUTING_OPTIONS = [
    {"display_name": "Main", "identifier": "main"},
    {"display_name": "PREMASTER", "identifier": "premaster"},
]


class FakeAbleton:
    def __init__(self):
        self.tracks = [
            self._make_track(0, "Drums"),
            self._make_track(1, "Bass"),
            self._make_track(2, "Reference"),
        ]
        self.uri_names = {
            "query:AudioFx#Utility": "Utility",
            "query:AudioFx#EQ%20Eight": "EQ Eight",
            "query:AudioFx#Limiter": "Limiter",
        }
        self.meter_values = []

    def _make_track(self, index, name):
        return {
            "index": index,
            "name": name,
            "is_audio_track": True,
            "is_midi_track": False,
            "volume": 0.85,
            "panning": 0.0,
            "devices": [],
            "routing": {
                "current_output_routing_type": {"display_name": "Main", "identifier": "main"},
                "current_output_routing_channel": {"display_name": "Stereo", "identifier": "stereo"},
                "available_output_routing_types": [dict(option) for option in ROUTING_OPTIONS],
                "available_output_routing_channels": [
                    {"display_name": "Stereo", "identifier": "stereo"}
                ],
            },
        }

    def send_command(self, command_type, params=None):
        params = params or {}
        if command_type == "get_session_info":
            return {"track_count": len(self.tracks)}
        if command_type == "get_track_info":
            track = self.tracks[params["track_index"]]
            return {
                "index": track["index"],
                "name": track["name"],
                "is_audio_track": track["is_audio_track"],
                "is_midi_track": track["is_midi_track"],
                "volume": track["volume"],
                "panning": track["panning"],
                "devices": [dict(device) for device in track["devices"]],
                "routing": json.loads(json.dumps(track["routing"])),
            }
        if command_type == "create_audio_track":
            index = len(self.tracks)
            track = self._make_track(index, "Audio")
            self.tracks.append(track)
            return {"index": index, "name": "Audio"}
        if command_type == "set_track_name":
            track = self.tracks[params["track_index"]]
            track["name"] = params["name"]
            track["routing"]["available_output_routing_types"] = [
                {"display_name": "Main", "identifier": "main"},
                {"display_name": track["name"], "identifier": track["name"].lower()},
            ]
            for other in self.tracks:
                if other["index"] != track["index"]:
                    options = [
                        option for option in other["routing"]["available_output_routing_types"]
                        if option["display_name"] != track["name"]
                    ]
                    options.append({"display_name": track["name"], "identifier": track["name"].lower()})
                    other["routing"]["available_output_routing_types"] = options
            return {"name": track["name"]}
        if command_type == "set_track_output_routing":
            track = self.tracks[params["track_index"]]
            track["routing"]["current_output_routing_type"] = {
                "display_name": params["routing_type_name"],
                "identifier": params["routing_type_name"].lower(),
            }
            if params.get("routing_channel_name"):
                track["routing"]["current_output_routing_channel"] = {
                    "display_name": params["routing_channel_name"],
                    "identifier": params["routing_channel_name"].lower(),
                }
            return self.send_command("get_track_info", {"track_index": params["track_index"]})
        if command_type == "get_track_routing":
            track = self.tracks[params["track_index"]]
            return {
                "index": track["index"],
                "name": track["name"],
                "routing": json.loads(json.dumps(track["routing"])),
            }
        if command_type == "load_browser_item":
            track = self.tracks[params["track_index"]]
            name = self.uri_names[params["item_uri"]]
            track["devices"].append({"name": name, "index": len(track["devices"])})
            return {"loaded": True, "item_name": name}
        if command_type == "get_master_meter":
            if not self.meter_values:
                raise AssertionError("No meter values queued")
            return self.meter_values.pop(0)
        raise AssertionError("Unexpected command: {0}".format(command_type))


class ServerToolsTest(unittest.TestCase):
    def test_analyze_audio_file_returns_loudness_metrics(self):
        sample_rate = 48000
        signal = 0.1 * np.sin(2.0 * np.pi * 440.0 * np.arange(sample_rate * 4) / sample_rate)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            path = handle.name
        try:
            sf.write(path, signal.astype("float32"), sample_rate)
            result = server._analyze_audio_file_data(path)
            self.assertIn("lufs_i", result)
            self.assertIn("lufs_s_max", result)
            self.assertIn("lra", result)
            self.assertIn("true_peak_dbtp", result)
            self.assertIn("sample_peak_dbfs", result)
            self.assertEqual(result["sample_rate"], sample_rate)
        finally:
            os.unlink(path)

    def test_append_mastering_chain_appends_expected_devices(self):
        fake = FakeAbleton()
        with mock.patch.object(server, "get_ableton_connection", return_value=fake):
            payload = server.append_mastering_chain(None, 0, "MINIMAL_TOUCH")
        result = json.loads(payload)
        self.assertEqual(result["preset_name"], "MINIMAL_TOUCH")
        self.assertEqual(
            [device["name"] for device in result["final_devices"]],
            ["Utility", "EQ Eight", "Limiter"],
        )

    def test_sample_master_meter_reports_window_maxima(self):
        fake = FakeAbleton()
        fake.meter_values = [
            {"peak_linear": 0.5, "level_linear": 0.4, "is_clipping": False},
            {"peak_linear": 1.1, "level_linear": 0.9, "is_clipping": True},
            {"peak_linear": 0.9, "level_linear": 0.7, "is_clipping": False},
        ]
        with mock.patch.object(server, "get_ableton_connection", return_value=fake):
            with mock.patch("time.sleep", return_value=None):
                payload = server.sample_master_meter(None, duration_seconds=0.3, interval_ms=100)
        result = json.loads(payload)
        self.assertTrue(result["is_clipping"])
        self.assertAlmostEqual(result["max_peak_linear"], 1.1)
        self.assertEqual(result["sample_count"], 3)

    def test_create_premaster_routing_excludes_reference_tracks(self):
        fake = FakeAbleton()
        with mock.patch.object(server, "get_ableton_connection", return_value=fake):
            payload = server.create_premaster_routing(None)
        result = json.loads(payload)
        self.assertEqual(result["premaster_track_name"], "PREMASTER")
        self.assertIn(0, result["routed_track_indices"])
        self.assertIn(1, result["routed_track_indices"])
        self.assertIn(2, result["auto_reference_track_indices"])
        self.assertNotIn(2, result["routed_track_indices"])


if __name__ == "__main__":
    unittest.main()

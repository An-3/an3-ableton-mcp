import asyncio
import importlib
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
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
            self._make_track(0, "Drums", playing_slot_index=0),
            self._make_track(1, "Bass"),
            self._make_track(2, "Reference"),
        ]
        self.uri_names = {
            "query:AudioFx#Utility": "Utility",
            "query:AudioFx#EQ%20Eight": "EQ Eight",
            "query:AudioFx#Limiter": "Limiter",
        }
        self.meter_values = []
        self.transport_state = {
            "is_playing": False,
            "current_song_time": 0.0,
            "arrangement_state_known": True,
            "session_override_active": True,
            "session_override_detection": "direct",
            "back_to_arrangement_source": "song.back_to_arranger",
            "arrangement_export_ready": False,
        }

    def _make_track(self, index, name, playing_slot_index=-2, fired_slot_index=-1):
        return {
            "index": index,
            "name": name,
            "is_audio_track": True,
            "is_midi_track": False,
            "mute": False,
            "solo": False,
            "arm": False,
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
            "playback_state": {
                "playing_slot_index": playing_slot_index,
                "fired_slot_index": fired_slot_index,
                "has_playing_session_clip": playing_slot_index >= 0,
                "has_fired_session_clip": fired_slot_index >= 0,
                "arrangement_playing": playing_slot_index == -2,
                "track_stopped": playing_slot_index == -1,
            },
            "clip_slots": [
                {
                    "index": 0,
                    "has_clip": True,
                    "clip": {
                        "name": "{0} Clip".format(name),
                        "length": 16.0,
                        "is_playing": playing_slot_index == 0,
                        "is_recording": False,
                    },
                }
            ],
        }

    def _playing_clips_payload(self):
        playing_clips = []
        for track in self.tracks:
            playback = track["playback_state"]
            slot_index = playback["playing_slot_index"]
            if slot_index >= 0:
                playing_clips.append({
                    "track_index": track["index"],
                    "track_name": track["name"],
                    "slot_index": slot_index,
                    "clip_name": track["clip_slots"][slot_index]["clip"]["name"],
                    "has_clip": True,
                    "state": "playing",
                })
        return {
            "playing_clips": playing_clips,
            "count": len(playing_clips),
            "session_override_active": self.transport_state["session_override_active"],
            "arrangement_state_known": self.transport_state["arrangement_state_known"],
        }

    def send_command(self, command_type, params=None):
        params = params or {}
        if command_type == "get_session_info":
            return {"track_count": len(self.tracks)}
        if command_type == "get_track_summary":
            track = self.tracks[params["track_index"]]
            return {
                "index": track["index"],
                "name": track["name"],
                "is_audio_track": track["is_audio_track"],
                "is_midi_track": track["is_midi_track"],
                "mute": track["mute"],
                "solo": track["solo"],
                "arm": track["arm"],
                "volume": track["volume"],
                "panning": track["panning"],
                "device_count": len(track["devices"]),
                "clip_slot_count": len(track["clip_slots"]),
                "playback_state": json.loads(json.dumps(track["playback_state"])),
                "routing": {
                    "current_output_routing_type": json.loads(json.dumps(
                        track["routing"]["current_output_routing_type"]
                    )),
                    "current_output_routing_channel": json.loads(json.dumps(
                        track["routing"]["current_output_routing_channel"]
                    )),
                },
            }
        if command_type == "list_tracks_summary":
            return [
                self.send_command("get_track_summary", {"track_index": track["index"]})
                for track in self.tracks
            ]
        if command_type == "get_track_info":
            track = self.tracks[params["track_index"]]
            return {
                "index": track["index"],
                "name": track["name"],
                "is_audio_track": track["is_audio_track"],
                "is_midi_track": track["is_midi_track"],
                "mute": track["mute"],
                "solo": track["solo"],
                "arm": track["arm"],
                "volume": track["volume"],
                "panning": track["panning"],
                "devices": [dict(device) for device in track["devices"]],
                "routing": json.loads(json.dumps(track["routing"])),
                "playback_state": json.loads(json.dumps(track["playback_state"])),
                "clip_slots": json.loads(json.dumps(track["clip_slots"])),
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
        if command_type == "get_transport_state":
            payload = dict(self.transport_state)
            payload["playing_clip_count"] = self._playing_clips_payload()["count"]
            payload["playing_clips"] = self._playing_clips_payload()["playing_clips"]
            return payload
        if command_type == "list_playing_clips":
            return self._playing_clips_payload()
        if command_type == "stop_all_clips":
            count_before = self._playing_clips_payload()["count"]
            for track in self.tracks:
                track["playback_state"]["playing_slot_index"] = -1
                track["playback_state"]["fired_slot_index"] = -1
                track["playback_state"]["has_playing_session_clip"] = False
                track["playback_state"]["has_fired_session_clip"] = False
                track["playback_state"]["arrangement_playing"] = False
                track["playback_state"]["track_stopped"] = True
                if track["clip_slots"]:
                    track["clip_slots"][0]["clip"]["is_playing"] = False
            self.transport_state["session_override_active"] = True
            self.transport_state["arrangement_export_ready"] = False
            return {
                "method": "song.stop_all_clips",
                "playing_clip_count_before": count_before,
                "playing_clip_count_after": 0,
                "stopped": True,
                "transport_state": self.send_command("get_transport_state"),
            }
        if command_type == "back_to_arrangement":
            playing_before = self._playing_clips_payload()["playing_clips"]
            for track in self.tracks:
                track["playback_state"]["playing_slot_index"] = -2
                track["playback_state"]["fired_slot_index"] = -1
                track["playback_state"]["has_playing_session_clip"] = False
                track["playback_state"]["has_fired_session_clip"] = False
                track["playback_state"]["arrangement_playing"] = True
                track["playback_state"]["track_stopped"] = False
                if track["clip_slots"]:
                    track["clip_slots"][0]["clip"]["is_playing"] = False
            self.transport_state["session_override_active"] = False
            self.transport_state["arrangement_export_ready"] = True
            return {
                "method": "song.back_to_arranger",
                "action": "called",
                "fallback_used": False,
                "playing_clips_before": playing_before,
                "playing_clips_after": [],
                "arrangement_export_ready": True,
                "transport_state": self.send_command("get_transport_state"),
                "warning": None,
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


@contextmanager
def reloaded_server(tool_profile=None, response_profile=None):
    original_tool_profile = os.environ.get("ABLETON_MCP_TOOL_PROFILE")
    original_response_profile = os.environ.get("ABLETON_MCP_RESPONSE_PROFILE")
    try:
        if tool_profile is None:
            os.environ.pop("ABLETON_MCP_TOOL_PROFILE", None)
        else:
            os.environ["ABLETON_MCP_TOOL_PROFILE"] = tool_profile

        if response_profile is None:
            os.environ.pop("ABLETON_MCP_RESPONSE_PROFILE", None)
        else:
            os.environ["ABLETON_MCP_RESPONSE_PROFILE"] = response_profile

        module = importlib.reload(server)
        yield module
    finally:
        if original_tool_profile is None:
            os.environ.pop("ABLETON_MCP_TOOL_PROFILE", None)
        else:
            os.environ["ABLETON_MCP_TOOL_PROFILE"] = original_tool_profile

        if original_response_profile is None:
            os.environ.pop("ABLETON_MCP_RESPONSE_PROFILE", None)
        else:
            os.environ["ABLETON_MCP_RESPONSE_PROFILE"] = original_response_profile

        importlib.reload(server)


def serialized_tool_manifest(module):
    tools = asyncio.run(module.mcp.list_tools())
    payload = [tool.model_dump(by_alias=True, exclude_none=True) for tool in tools]
    return json.dumps(payload, separators=(",", ":"))


class ServerToolsTest(unittest.TestCase):
    def test_all_profile_tool_manifest_budget_and_whitelist(self):
        expected_tools = {
            "get_session_info",
            "get_track_info",
            "get_track_routing",
            "get_transport_state",
            "list_playing_clips",
            "list_tracks",
            "find_track_by_name",
            "find_reference_tracks",
            "get_master_meter",
            "sample_master_meter",
            "create_midi_track",
            "create_audio_track",
            "ensure_premaster_track",
            "set_track_name",
            "set_track_volume",
            "set_track_panning",
            "set_track_output_routing",
            "create_premaster_routing",
            "get_device_parameters",
            "set_device_parameter",
            "load_audio_clip",
            "append_browser_device",
            "append_mastering_chain",
            "place_clip_in_arrangement",
            "create_clip",
            "add_notes_to_clip",
            "set_clip_name",
            "set_tempo",
            "load_instrument_or_effect",
            "fire_clip",
            "stop_clip",
            "start_playback",
            "stop_playback",
            "stop_all_clips",
            "back_to_arrangement",
            "verify_arrangement_export_ready",
            "get_browser_tree",
            "get_browser_items_at_path",
            "load_drum_kit",
            "analyze_audio_file",
        }
        with reloaded_server(tool_profile="all") as module:
            tools = asyncio.run(module.mcp.list_tools())
            tool_names = {tool.name for tool in tools}
            manifest = serialized_tool_manifest(module)
        self.assertEqual(tool_names, expected_tools)
        self.assertLessEqual(len(manifest), 14000)

    def test_core_profile_tool_manifest_budget_and_whitelist(self):
        expected_tools = {
            "get_session_info",
            "list_tracks",
            "get_track_info",
            "create_midi_track",
            "create_audio_track",
            "set_track_name",
            "create_clip",
            "add_notes_to_clip",
            "set_tempo",
            "load_instrument_or_effect",
            "load_audio_clip",
            "fire_clip",
            "start_playback",
            "stop_playback",
        }
        with reloaded_server(tool_profile="core") as module:
            tools = asyncio.run(module.mcp.list_tools())
            tool_names = {tool.name for tool in tools}
            manifest = serialized_tool_manifest(module)
        self.assertEqual(tool_names, expected_tools)
        self.assertLessEqual(len(manifest), 6000)

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

    def test_compat_profile_preserves_existing_verbose_keys(self):
        fake = FakeAbleton()
        with reloaded_server(response_profile="compat") as module:
            with mock.patch.object(module, "get_ableton_connection", return_value=fake):
                track_payload = json.loads(module.get_track_info(None, 0))
                ready_payload = json.loads(module.verify_arrangement_export_ready(None))
                chain_payload = json.loads(module.append_mastering_chain(None, 0, "MINIMAL_TOUCH"))
                arrangement_payload = json.loads(module.back_to_arrangement(None))
        self.assertIn("clip_slots", track_payload)
        self.assertIn("devices", track_payload)
        self.assertIn("transport_state", ready_payload)
        self.assertIn("playing_clips", ready_payload)
        self.assertIn("steps", chain_payload)
        self.assertIn("final_devices", chain_payload)
        self.assertIn("transport_state", arrangement_payload)
        self.assertIn("playing_clips_before", arrangement_payload)

    def test_compact_profile_reduces_track_meter_and_arrangement_payloads(self):
        fake = FakeAbleton()
        compat_meter_values = [
            {"peak_linear": 0.5, "level_linear": 0.4, "is_clipping": False},
            {"peak_linear": 1.1, "level_linear": 0.9, "is_clipping": True},
            {"peak_linear": 0.9, "level_linear": 0.7, "is_clipping": False},
        ]
        compact_meter_values = json.loads(json.dumps(compat_meter_values))

        with reloaded_server(response_profile="compat") as module:
            fake.meter_values = json.loads(json.dumps(compat_meter_values))
            with mock.patch.object(module, "get_ableton_connection", return_value=fake):
                compat_track = module.get_track_info(None, 0)
                compat_ready = module.verify_arrangement_export_ready(None)
                compat_arrangement = module.back_to_arrangement(None)
                with mock.patch("time.sleep", return_value=None):
                    compat_meter = module.sample_master_meter(None, duration_seconds=0.3, interval_ms=100)

        fake = FakeAbleton()
        with reloaded_server(response_profile="compact") as module:
            fake.meter_values = json.loads(json.dumps(compact_meter_values))
            with mock.patch.object(module, "get_ableton_connection", return_value=fake):
                compact_track_raw = module.get_track_info(None, 0)
                compact_ready_raw = module.verify_arrangement_export_ready(None)
                compact_arrangement_raw = module.back_to_arrangement(None)
                with mock.patch("time.sleep", return_value=None):
                    compact_meter_raw = module.sample_master_meter(None, duration_seconds=0.3, interval_ms=100)

        compact_track = json.loads(compact_track_raw)
        compact_ready = json.loads(compact_ready_raw)
        compact_arrangement = json.loads(compact_arrangement_raw)
        compact_meter = json.loads(compact_meter_raw)

        self.assertLess(len(compact_track_raw), len(compat_track))
        self.assertLess(len(compact_ready_raw), len(compat_ready))
        self.assertLess(len(compact_arrangement_raw), len(compat_arrangement))
        self.assertLess(len(compact_meter_raw), len(compat_meter))

        self.assertNotIn("clip_slots", compact_track)
        self.assertNotIn("devices", compact_track)
        self.assertNotIn("available_output_routing_types", compact_track["routing"])
        self.assertNotIn("transport_state", compact_ready)
        self.assertNotIn("playing_clips", compact_ready)
        self.assertNotIn("transport_state", compact_arrangement)
        self.assertNotIn("playing_clips_before", compact_arrangement)
        self.assertNotIn("samples", compact_meter)

    def test_compact_profile_returns_compact_chain_and_track_list_payloads(self):
        fake = FakeAbleton()
        with reloaded_server(response_profile="compact") as module:
            with mock.patch.object(module, "get_ableton_connection", return_value=fake):
                chain_payload = json.loads(module.append_mastering_chain(None, 0, "MINIMAL_TOUCH"))
                track_list_payload = json.loads(module.list_tracks(None))
        self.assertEqual(chain_payload["loaded_count"], 3)
        self.assertEqual(chain_payload["final_device_count"], 3)
        self.assertNotIn("steps", chain_payload)
        self.assertNotIn("final_devices", chain_payload)
        self.assertIn("clip_slot_count", track_list_payload[0])
        self.assertIn("mute", track_list_payload[0])
        self.assertNotIn("available_output_routing_types", track_list_payload[0]["routing"])

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

    def test_verify_arrangement_export_ready_fails_when_session_override_is_active(self):
        fake = FakeAbleton()
        with mock.patch.object(server, "get_ableton_connection", return_value=fake):
            payload = server.verify_arrangement_export_ready(None)
        result = json.loads(payload)
        self.assertFalse(result["ready"])
        self.assertIn("active_session_clips", result["issues"])
        self.assertIn("session_override_active", result["issues"])

    def test_verify_arrangement_export_ready_requires_known_arrangement_state(self):
        fake = FakeAbleton()
        fake.transport_state["arrangement_state_known"] = False
        fake.transport_state["session_override_active"] = None
        fake.transport_state["arrangement_export_ready"] = False
        fake.tracks[0]["playback_state"]["playing_slot_index"] = -1
        fake.tracks[0]["playback_state"]["has_playing_session_clip"] = False
        fake.tracks[0]["clip_slots"][0]["clip"]["is_playing"] = False
        with mock.patch.object(server, "get_ableton_connection", return_value=fake):
            payload = server.verify_arrangement_export_ready(None)
        result = json.loads(payload)
        self.assertFalse(result["ready"])
        self.assertIn("arrangement_state_unverified", result["issues"])

    def test_back_to_arrangement_clears_export_guard(self):
        fake = FakeAbleton()
        with mock.patch.object(server, "get_ableton_connection", return_value=fake):
            payload = server.back_to_arrangement(None)
            result = json.loads(payload)
            readiness = json.loads(server.verify_arrangement_export_ready(None))
        self.assertTrue(result["arrangement_export_ready"])
        self.assertTrue(readiness["ready"])

    def test_list_tracks_includes_playback_state(self):
        fake = FakeAbleton()
        with mock.patch.object(server, "get_ableton_connection", return_value=fake):
            payload = server.list_tracks(None)
        result = json.loads(payload)
        self.assertIn("playback_state", result[0])
        self.assertEqual(result[0]["playback_state"]["playing_slot_index"], 0)


if __name__ == "__main__":
    unittest.main()

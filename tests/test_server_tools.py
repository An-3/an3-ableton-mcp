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
INPUT_ROUTING_OPTIONS = [
    {"display_name": "No Input", "identifier": "no-input"},
    {"display_name": "Ext. In", "identifier": "ext-in"},
]
ROUTING_CHANNEL_OPTIONS = [
    {"display_name": "Stereo", "identifier": "stereo"},
]
MONITOR_STATE_OPTIONS = [
    {"name": "in", "value": 0},
    {"name": "auto", "value": 1},
    {"name": "off", "value": 2},
]


class FakeAbleton:
    def __init__(self):
        self.tracks = [
            self._make_track(0, "Drums", playing_slot_index=0),
            self._make_track(1, "Bass"),
            self._make_track(2, "Reference"),
        ]
        self.return_tracks = [
            self._make_track(0, "Return A", track_scope="return", with_clip_slots=False),
        ]
        self.master_track = self._make_track(0, "Master", track_scope="master", with_clip_slots=False)
        self.uri_names = {
            "query:AudioFx#Utility": "Utility",
            "query:AudioFx#EQ%20Eight": "EQ Eight",
            "query:AudioFx#Limiter": "Limiter",
            "query:AudioFx#Glue%20Compressor": "Glue Compressor",
            "query:AudioFx#Saturator": "Saturator",
            "query:AudioFx#Compressor": "Compressor",
            "query:AudioFx#Multiband%20Dynamics": "Multiband Dynamics",
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
        self.song_length = 96.0
        self.file_path = "/Users/test/OpenSet.als"
        self.remote_script_info_supported = True
        self.remote_script_version = "2026.03.16.1"
        self.remote_script_protocol_version = 3
        self.remote_script_capabilities = [
            "get_remote_script_info",
            "get_arrangement_summary",
            "get_track_devices",
            "track_scope_master",
            "track_scope_return",
            "get_track_meter",
            "get_track_input_routing",
            "set_track_input_routing",
            "get_track_monitor_state",
            "set_track_monitor_state",
            "find_device_by_name",
            "delete_device",
        ]
        self.alias_master_scope_to_track = False
        self.break_master_track_info = False
        self._sync_track_routing_options()

    def _clone(self, value):
        return json.loads(json.dumps(value))

    def _make_device(self, name, index=0):
        return {
            "index": index,
            "name": name,
            "class_name": name,
            "type": "audio_effect",
            "parameters": [
                {
                    "index": 0,
                    "name": "Gain",
                    "value": 0.0,
                    "min": -12.0,
                    "max": 12.0,
                    "default": 0.0,
                    "is_quantized": False,
                    "display_value": "0.0 dB",
                }
            ],
        }

    def _make_track(
        self,
        index,
        name,
        playing_slot_index=-2,
        fired_slot_index=-1,
        track_scope="track",
        with_clip_slots=True,
    ):
        clip_slots = [
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
        ] if with_clip_slots else []
        arrangement_clips = [
            {
                "index": 0,
                "name": "{0} Arrangement".format(name),
                "start_time": 0.0,
                "length": 16.0,
                "end_time": 16.0,
            }
        ] if track_scope == "track" else []
        return {
            "track_scope": track_scope,
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
                "current_input_routing_type": {"display_name": "No Input", "identifier": "no-input"},
                "current_input_routing_channel": {"display_name": "Stereo", "identifier": "stereo"},
                "available_input_routing_types": self._clone(INPUT_ROUTING_OPTIONS),
                "available_input_routing_channels": self._clone(ROUTING_CHANNEL_OPTIONS),
                "current_output_routing_type": {"display_name": "Main", "identifier": "main"},
                "current_output_routing_channel": {"display_name": "Stereo", "identifier": "stereo"},
                "available_output_routing_types": self._clone(ROUTING_OPTIONS),
                "available_output_routing_channels": self._clone(ROUTING_CHANNEL_OPTIONS),
            },
            "current_monitoring_state": 1,
            "available_monitoring_states": self._clone(MONITOR_STATE_OPTIONS),
            "playback_state": {
                "playing_slot_index": playing_slot_index,
                "fired_slot_index": fired_slot_index,
                "has_playing_session_clip": playing_slot_index >= 0,
                "has_fired_session_clip": fired_slot_index >= 0,
                "arrangement_playing": playing_slot_index == -2,
                "track_stopped": playing_slot_index == -1,
            },
            "clip_slots": clip_slots,
            "arrangement_clips": arrangement_clips,
            "meter": {
                "left_linear": 0.5,
                "right_linear": 0.5,
                "level_linear": 0.45,
                "peak_linear": 0.5,
                "left_db": -6.0,
                "right_db": -6.0,
                "level_db": -6.94,
                "peak_db": -6.0,
                "is_clipping": False,
                "clip_threshold_linear": 1.0,
            },
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

    def _sync_track_routing_options(self):
        track_targets = [
            {"display_name": "Main", "identifier": "main"}
        ]
        for track in self.tracks:
            track_targets.append({
                "display_name": track["name"],
                "identifier": track["name"].lower(),
            })
        for track in self.tracks:
            track["routing"]["available_output_routing_types"] = self._clone(track_targets)

    def _resolve_track(self, params):
        track_scope = params.get("track_scope", "track")
        if track_scope == "master":
            if self.alias_master_scope_to_track:
                return self.tracks[params["track_index"]]
            return self.master_track
        if track_scope == "return":
            return self.return_tracks[params["track_index"]]
        return self.tracks[params["track_index"]]

    def _track_summary_payload(self, track):
        track_flags = self._stable_track_flags(track)
        return {
            "track_scope": track["track_scope"],
            "index": track["index"],
            "name": track["name"],
            "is_audio_track": track["is_audio_track"],
            "is_midi_track": track["is_midi_track"],
            "mute": track_flags["mute"],
            "solo": track_flags["solo"],
            "arm": track_flags["arm"],
            "volume": track["volume"],
            "panning": track["panning"],
            "device_count": len(track["devices"]),
            "clip_slot_count": len(track["clip_slots"]),
            "playback_state": self._clone(track["playback_state"]),
            "routing": {
                "current_input_routing_type": self._clone(track["routing"]["current_input_routing_type"]),
                "current_input_routing_channel": self._clone(track["routing"]["current_input_routing_channel"]),
                "current_output_routing_type": self._clone(track["routing"]["current_output_routing_type"]),
                "current_output_routing_channel": self._clone(track["routing"]["current_output_routing_channel"]),
            },
        }

    def _track_info_payload(self, track):
        track_flags = self._stable_track_flags(track)
        return {
            "track_scope": track["track_scope"],
            "index": track["index"],
            "name": track["name"],
            "is_audio_track": track["is_audio_track"],
            "is_midi_track": track["is_midi_track"],
            "mute": track_flags["mute"],
            "solo": track_flags["solo"],
            "arm": track_flags["arm"],
            "volume": track["volume"],
            "panning": track["panning"],
            "devices": [
                {
                    "index": device["index"],
                    "name": device["name"],
                    "class_name": device["class_name"],
                    "type": device["type"],
                }
                for device in track["devices"]
            ],
            "routing": self._clone(track["routing"]),
            "playback_state": self._clone(track["playback_state"]),
            "clip_slots": self._clone(track["clip_slots"]),
        }

    def _track_devices_payload(self, track):
        return {
            "track_scope": track["track_scope"],
            "index": track["index"],
            "name": track["name"],
            "devices": [
                {
                    "index": device["index"],
                    "name": device["name"],
                    "class_name": device["class_name"],
                    "type": device["type"],
                }
                for device in track["devices"]
            ],
        }

    def _stable_track_flags(self, track):
        if track["track_scope"] == "master":
            return {"mute": None, "solo": None, "arm": None}
        return {
            "mute": track["mute"],
            "solo": track["solo"],
            "arm": track["arm"],
        }

    def _refresh_device_indexes(self, track):
        for device_index, device in enumerate(track["devices"]):
            device["index"] = device_index

    def send_command(self, command_type, params=None, timeout_seconds=None):
        params = params or {}
        if command_type == "get_remote_script_info":
            if not self.remote_script_info_supported:
                raise Exception("Unknown command: get_remote_script_info")
            return {
                "script_name": "AbletonMCP",
                "script_version": self.remote_script_version,
                "protocol_version": self.remote_script_protocol_version,
                "capabilities": self._clone(self.remote_script_capabilities),
            }
        if command_type == "get_session_info":
            return {
                "track_count": len(self.tracks),
                "return_track_count": len(self.return_tracks),
                "song_length": self.song_length,
                "file_path": self.file_path,
            }
        if command_type == "get_track_summary":
            return self._track_summary_payload(self.tracks[params["track_index"]])
        if command_type == "list_tracks_summary":
            return [
                self.send_command("get_track_summary", {"track_index": track["index"]})
                for track in self.tracks
            ]
        if command_type == "get_track_info":
            track = self._resolve_track(params)
            if self.break_master_track_info and track["track_scope"] == "master":
                raise Exception("Main track has no 'mute' property!")
            return self._track_info_payload(track)
        if command_type == "get_track_devices":
            return self._track_devices_payload(self._resolve_track(params))
        if command_type == "create_audio_track":
            index = len(self.tracks)
            track = self._make_track(index, "Audio")
            self.tracks.append(track)
            self._sync_track_routing_options()
            return {"index": index, "name": "Audio"}
        if command_type == "set_track_name":
            track = self.tracks[params["track_index"]]
            track["name"] = params["name"]
            if track["clip_slots"]:
                track["clip_slots"][0]["clip"]["name"] = "{0} Clip".format(track["name"])
            self._sync_track_routing_options()
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
            return self._track_info_payload(track)
        if command_type == "get_track_routing":
            track = self._resolve_track(params)
            return {
                "track_scope": track["track_scope"],
                "index": track["index"],
                "name": track["name"],
                "routing": self._clone(track["routing"]),
            }
        if command_type == "get_track_input_routing":
            track = self.tracks[params["track_index"]]
            return {
                "track_scope": "track",
                "index": track["index"],
                "name": track["name"],
                "routing": {
                    "current_input_routing_type": self._clone(track["routing"]["current_input_routing_type"]),
                    "current_input_routing_channel": self._clone(track["routing"]["current_input_routing_channel"]),
                    "available_input_routing_types": self._clone(track["routing"]["available_input_routing_types"]),
                    "available_input_routing_channels": self._clone(track["routing"]["available_input_routing_channels"]),
                },
            }
        if command_type == "set_track_input_routing":
            track = self.tracks[params["track_index"]]
            track["routing"]["current_input_routing_type"] = {
                "display_name": params["routing_type_name"],
                "identifier": params["routing_type_name"].lower(),
            }
            if params.get("routing_channel_name"):
                track["routing"]["current_input_routing_channel"] = {
                    "display_name": params["routing_channel_name"],
                    "identifier": params["routing_channel_name"].lower(),
                }
            return self.send_command("get_track_input_routing", {"track_index": params["track_index"]})
        if command_type == "get_track_monitor_state":
            track = self.tracks[params["track_index"]]
            current_value = track["current_monitoring_state"]
            current_name = next(
                option["name"] for option in MONITOR_STATE_OPTIONS if option["value"] == current_value
            )
            return {
                "track_scope": "track",
                "index": track["index"],
                "name": track["name"],
                "current_monitoring_state": current_value,
                "current_monitoring_state_name": current_name,
                "available_monitoring_states": self._clone(track["available_monitoring_states"]),
            }
        if command_type == "set_track_monitor_state":
            track = self.tracks[params["track_index"]]
            if params.get("state_value") is not None:
                track["current_monitoring_state"] = int(params["state_value"])
            else:
                name = params["state_name"].strip().lower()
                mapping = {option["name"]: option["value"] for option in MONITOR_STATE_OPTIONS}
                track["current_monitoring_state"] = mapping[name]
            return self.send_command("get_track_monitor_state", {"track_index": params["track_index"]})
        if command_type == "get_track_meter":
            track = self._resolve_track(params)
            meter = self._clone(track["meter"])
            meter.update({
                "track_scope": track["track_scope"],
                "index": track["index"],
                "name": track["name"],
            })
            return meter
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
            track = self._resolve_track(params)
            name = self.uri_names[params["item_uri"]]
            track["devices"].append(self._make_device(name, len(track["devices"])))
            return {
                "loaded": True,
                "item_name": name,
                "track_scope": track["track_scope"],
                "track_index": track["index"],
            }
        if command_type == "get_device_parameters":
            track = self._resolve_track(params)
            device = track["devices"][params["device_index"]]
            return {
                "track_scope": track["track_scope"],
                "track_index": track["index"],
                "device_name": device["name"],
                "class_name": device["class_name"],
                "device_index": device["index"],
                "parameters": self._clone(device["parameters"]),
            }
        if command_type == "set_device_parameter":
            track = self._resolve_track(params)
            device = track["devices"][params["device_index"]]
            parameter = device["parameters"][params["parameter_index"]]
            parameter["value"] = params["value"]
            parameter["display_value"] = "{0:.1f} dB".format(parameter["value"])
            return {
                "track_scope": track["track_scope"],
                "track_index": track["index"],
                "device": device["name"],
                "device_index": device["index"],
                "parameter": parameter["name"],
                "parameter_index": parameter["index"],
                "value": parameter["value"],
                "display_value": parameter["display_value"],
                "min": parameter["min"],
                "max": parameter["max"],
            }
        if command_type == "find_device_by_name":
            track = self._resolve_track(params)
            wanted = params["name"].strip().lower()
            exact = bool(params.get("exact", True))
            matches = []
            for device in track["devices"]:
                candidate = device["name"].strip().lower()
                matched = candidate == wanted if exact else wanted in candidate
                if matched:
                    matches.append({
                        "index": device["index"],
                        "name": device["name"],
                        "class_name": device["class_name"],
                        "type": device["type"],
                    })
            return {
                "track_scope": track["track_scope"],
                "track_index": track["index"],
                "track_name": track["name"],
                "name": params["name"],
                "exact": exact,
                "matches": matches,
            }
        if command_type == "delete_device":
            track = self._resolve_track(params)
            device = track["devices"].pop(params["device_index"])
            self._refresh_device_indexes(track)
            return {
                "track_scope": track["track_scope"],
                "track_index": track["index"],
                "track_name": track["name"],
                "deleted_device_index": params["device_index"],
                "deleted_device_name": device["name"],
                "remaining_devices": [entry["name"] for entry in track["devices"]],
            }
        if command_type == "get_arrangement_summary":
            detail_level = (params.get("detail_level", "basic") or "basic").strip().lower()
            result = {
                "detail_level": detail_level,
                "song_length": self.song_length,
                "current_song_time": self.transport_state["current_song_time"],
                "is_playing": self.transport_state["is_playing"],
                "file_path": self.file_path,
                "track_count": len(self.tracks),
            }
            if detail_level == "basic":
                return result
            tracks = []
            first_clip_start = None
            last_clip_end = None
            include_clips = detail_level == "clips"
            for track in self.tracks:
                clip_count = len(track["arrangement_clips"])
                first_track_start = track["arrangement_clips"][0]["start_time"] if clip_count else None
                last_track_end = track["arrangement_clips"][-1]["end_time"] if clip_count else None
                if first_track_start is not None:
                    first_clip_start = first_track_start if first_clip_start is None else min(first_clip_start, first_track_start)
                if last_track_end is not None:
                    last_clip_end = last_track_end if last_clip_end is None else max(last_clip_end, last_track_end)
                track_payload = {
                    "index": track["index"],
                    "name": track["name"],
                    "arrangement_clip_count": clip_count,
                    "first_clip_start_time": first_track_start,
                    "last_clip_end_time": last_track_end,
                }
                if include_clips:
                    track_payload["clips"] = self._clone(track["arrangement_clips"])
                tracks.append(track_payload)
            result.update({
                "first_clip_start_time": first_clip_start,
                "last_clip_end_time": last_clip_end,
                "tracks": tracks,
            })
            return result
        if command_type == "get_master_meter":
            if self.meter_values:
                return self.meter_values.pop(0)
            return self._clone(self.master_track["meter"])
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
            "get_track_input_routing",
            "set_track_input_routing",
            "get_track_monitor_state",
            "set_track_monitor_state",
            "get_transport_state",
            "list_playing_clips",
            "list_tracks",
            "find_track_by_name",
            "find_reference_tracks",
            "get_master_meter",
            "get_track_meter",
            "sample_track_meter",
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
            "find_device_by_name",
            "delete_device",
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
            "get_track_devices",
            "get_arrangement_summary",
            "verify_arrangement_export_ready",
            "resolve_mastering_source",
            "export_audio_macos",
            "master_and_export_opened_set",
            "diagnose_remote_script_install",
            "get_browser_tree",
            "get_browser_items_at_path",
            "load_drum_kit",
            "analyze_audio_file",
            "validate_audio_export",
        }
        with reloaded_server(tool_profile="all") as module:
            tools = asyncio.run(module.mcp.list_tools())
            tool_names = {tool.name for tool in tools}
            manifest = serialized_tool_manifest(module)
        self.assertEqual(tool_names, expected_tools)
        self.assertLessEqual(len(manifest), 21500)

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

    def test_resolve_mastering_source_prefers_opened_live_set(self):
        fake = FakeAbleton()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            path = handle.name
        try:
            sf.write(path, np.zeros(48000, dtype="float32"), 48000)
            with mock.patch.object(server, "get_ableton_connection", return_value=fake):
                result = server._resolve_mastering_source_data(
                    requested_source="opened-live-set",
                    file_path=path,
                    allow_file_fallback=False,
                )
            self.assertEqual(result["state"], "source-ready")
            self.assertEqual(result["actual_source_used"], "opened-live-set")
            self.assertFalse(result["fallback_used"])
            self.assertEqual(result["ignored_file_candidate_path"], path)
        finally:
            os.unlink(path)

    def test_resolve_mastering_source_uses_explicit_file(self):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            path = handle.name
        try:
            sf.write(path, np.zeros(48000, dtype="float32"), 48000)
            result = server._resolve_mastering_source_data(
                requested_source="file",
                file_path=path,
            )
            self.assertEqual(result["state"], "source-ready")
            self.assertEqual(result["actual_source_used"], path)
            self.assertEqual(result["actual_source_type"], "file")
            self.assertTrue(result["source_timestamp_available"])
            self.assertFalse(result["fallback_used"])
        finally:
            os.unlink(path)

    def test_resolve_mastering_source_blocks_implicit_file_fallback(self):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            path = handle.name
        try:
            sf.write(path, np.zeros(48000, dtype="float32"), 48000)
            with mock.patch.object(server, "get_ableton_connection", side_effect=RuntimeError("Live unavailable")):
                result = server._resolve_mastering_source_data(
                    requested_source="opened-live-set",
                    file_path=path,
                    allow_file_fallback=False,
                )
            self.assertEqual(result["state"], "export-blocked")
            self.assertFalse(result["fallback_used"])
            self.assertEqual(result["blocked_fallback_file_path"], path)
        finally:
            os.unlink(path)

    def test_validate_audio_export_passes_for_audible_file(self):
        sample_rate = 48000
        signal = 0.1 * np.sin(2.0 * np.pi * 440.0 * np.arange(sample_rate * 3) / sample_rate)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            path = handle.name
        try:
            sf.write(path, signal.astype("float32"), sample_rate)
            resolved = {
                "requested_file_path": path,
                "resolved_file_path": path,
                "path_normalized": False,
                "resolved_size_bytes": os.path.getsize(path),
                "resolved_mtime": os.path.getmtime(path),
                "candidate_paths": [path],
            }
            preview = {"attempted": True, "status": "played"}
            with mock.patch.object(server, "_wait_for_stable_export_file", return_value=resolved):
                with mock.patch.object(server, "_play_audio_preview", return_value=preview):
                    result = server._validate_audio_export_data(
                        path,
                        expected_duration_seconds=3.0,
                    )
            self.assertEqual(result["state"], "export-validated")
            self.assertEqual(result["preview"]["status"], "played")
            self.assertEqual(result["export_validation"]["failed_checks"], [])
            self.assertGreater(result["export_validation"]["sample_peak_dbfs"], -80.0)
        finally:
            os.unlink(path)

    def test_validate_audio_export_fails_for_effectively_silent_file(self):
        sample_rate = 48000
        signal = np.full((sample_rate * 2, 2), np.finfo("float32").eps, dtype="float32")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            path = handle.name
        try:
            sf.write(path, signal, sample_rate)
            resolved = {
                "requested_file_path": path,
                "resolved_file_path": path,
                "path_normalized": False,
                "resolved_size_bytes": os.path.getsize(path),
                "resolved_mtime": os.path.getmtime(path),
                "candidate_paths": [path],
            }
            preview = {"attempted": True, "status": "played"}
            with mock.patch.object(server, "_wait_for_stable_export_file", return_value=resolved):
                with mock.patch.object(server, "_play_audio_preview", return_value=preview):
                    result = server._validate_audio_export_data(
                        path,
                        expected_duration_seconds=2.0,
                    )
            self.assertEqual(result["state"], "export-failed")
            self.assertIn("non_finite_lufs", result["export_validation"]["failed_checks"])
            self.assertIn("sample_peak_below_threshold", result["export_validation"]["failed_checks"])
            self.assertIn("all_window_peaks_below_threshold", result["export_validation"]["failed_checks"])
        finally:
            os.unlink(path)

    def test_validate_audio_export_keeps_success_when_preview_fails(self):
        sample_rate = 48000
        signal = 0.1 * np.sin(2.0 * np.pi * 220.0 * np.arange(sample_rate * 2) / sample_rate)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            path = handle.name
        try:
            sf.write(path, signal.astype("float32"), sample_rate)
            resolved = {
                "requested_file_path": path,
                "resolved_file_path": path,
                "path_normalized": False,
                "resolved_size_bytes": os.path.getsize(path),
                "resolved_mtime": os.path.getmtime(path),
                "candidate_paths": [path],
            }
            preview = {"attempted": True, "status": "failed", "reason": "afplay unavailable"}
            with mock.patch.object(server, "_wait_for_stable_export_file", return_value=resolved):
                with mock.patch.object(server, "_play_audio_preview", return_value=preview):
                    result = server._validate_audio_export_data(path, expected_duration_seconds=2.0)
            self.assertEqual(result["state"], "export-validated")
            self.assertEqual(result["preview"]["status"], "failed")
        finally:
            os.unlink(path)

    def test_validate_audio_export_detects_late_first_audible_vs_reference(self):
        sample_rate = 48000
        tone = 0.1 * np.sin(2.0 * np.pi * 440.0 * np.arange(sample_rate * 12) / sample_rate)
        delayed = np.concatenate([np.zeros(sample_rate * 6, dtype="float32"), tone.astype("float32")])
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as reference_handle:
            reference_path = reference_handle.name
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as output_handle:
            output_path = output_handle.name
        try:
            sf.write(reference_path, tone.astype("float32"), sample_rate)
            sf.write(output_path, delayed, sample_rate)
            resolved = {
                "requested_file_path": output_path,
                "resolved_file_path": output_path,
                "path_normalized": False,
                "resolved_size_bytes": os.path.getsize(output_path),
                "resolved_mtime": os.path.getmtime(output_path),
                "candidate_paths": [output_path],
            }
            preview = {"attempted": True, "status": "played"}
            with mock.patch.object(server, "_wait_for_stable_export_file", return_value=resolved):
                with mock.patch.object(server, "_play_audio_preview", return_value=preview):
                    result = server._validate_audio_export_data(
                        output_path,
                        reference_file_path=reference_path,
                        max_first_audible_delta_seconds=1.0,
                        max_first_audible_seconds=None,
                        section_seconds=6.0,
                    )
            self.assertEqual(result["state"], "export-failed")
            self.assertIn("first_audible_late_vs_reference", result["export_validation"]["failed_checks"])
        finally:
            os.unlink(reference_path)
            os.unlink(output_path)

    def test_validate_audio_export_detects_reference_content_drop(self):
        sample_rate = 48000
        seconds = 30
        t = np.arange(sample_rate * seconds) / sample_rate
        full_band = (
            0.08 * np.sin(2.0 * np.pi * 80.0 * t) +
            0.06 * np.sin(2.0 * np.pi * 1000.0 * t) +
            0.04 * np.sin(2.0 * np.pi * 8000.0 * t)
        ).astype("float32")
        dropped = full_band.copy()
        mid_start = sample_rate * 10
        mid_end = sample_rate * 20
        dropped[mid_start:mid_end] = (
            0.08 * np.sin(2.0 * np.pi * 80.0 * t[: mid_end - mid_start])
        ).astype("float32")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as reference_handle:
            reference_path = reference_handle.name
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as output_handle:
            output_path = output_handle.name
        try:
            sf.write(reference_path, full_band, sample_rate)
            sf.write(output_path, dropped, sample_rate)
            resolved = {
                "requested_file_path": output_path,
                "resolved_file_path": output_path,
                "path_normalized": False,
                "resolved_size_bytes": os.path.getsize(output_path),
                "resolved_mtime": os.path.getmtime(output_path),
                "candidate_paths": [output_path],
            }
            preview = {"attempted": True, "status": "played"}
            with mock.patch.object(server, "_wait_for_stable_export_file", return_value=resolved):
                with mock.patch.object(server, "_play_audio_preview", return_value=preview):
                    result = server._validate_audio_export_data(
                        output_path,
                        reference_file_path=reference_path,
                        max_first_audible_seconds=None,
                        section_seconds=10.0,
                        reference_drop_threshold_db=8.0,
                    )
            self.assertEqual(result["state"], "export-failed")
            self.assertIn("reference_content_drop_detected", result["export_validation"]["failed_checks"])
            self.assertEqual(result["export_validation"]["content_presence"]["flagged_sections"][0]["index"], 1)
        finally:
            os.unlink(reference_path)
            os.unlink(output_path)

    def test_validate_audio_export_passes_reference_comparison_for_uniform_gain_change(self):
        sample_rate = 48000
        signal = 0.12 * np.sin(2.0 * np.pi * 440.0 * np.arange(sample_rate * 8) / sample_rate)
        output_signal = 0.6 * signal
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as reference_handle:
            reference_path = reference_handle.name
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as output_handle:
            output_path = output_handle.name
        try:
            sf.write(reference_path, signal.astype("float32"), sample_rate)
            sf.write(output_path, output_signal.astype("float32"), sample_rate)
            resolved = {
                "requested_file_path": output_path,
                "resolved_file_path": output_path,
                "path_normalized": False,
                "resolved_size_bytes": os.path.getsize(output_path),
                "resolved_mtime": os.path.getmtime(output_path),
                "candidate_paths": [output_path],
            }
            preview = {"attempted": True, "status": "played"}
            with mock.patch.object(server, "_wait_for_stable_export_file", return_value=resolved):
                with mock.patch.object(server, "_play_audio_preview", return_value=preview):
                    result = server._validate_audio_export_data(
                        output_path,
                        reference_file_path=reference_path,
                        max_first_audible_seconds=None,
                        section_seconds=4.0,
                        reference_drop_threshold_db=8.0,
                    )
            self.assertEqual(result["state"], "export-validated")
            self.assertEqual(result["export_validation"]["content_presence"]["flagged_sections"], [])
        finally:
            os.unlink(reference_path)
            os.unlink(output_path)

    def test_play_audio_preview_reports_success_when_afplay_runs(self):
        sample_rate = 48000
        signal = 0.1 * np.sin(2.0 * np.pi * 330.0 * np.arange(sample_rate * 2) / sample_rate)
        with mock.patch.object(server.shutil, "which", return_value="/usr/bin/afplay"):
            with mock.patch.object(server.subprocess, "run") as run_mock:
                preview = server._play_audio_preview(signal.astype("float32"), sample_rate, preview_seconds=1.0)
        self.assertTrue(preview["attempted"])
        self.assertEqual(preview["status"], "played")
        run_mock.assert_called_once()

    def test_wait_for_stable_export_file_prefers_fresh_double_extension_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            requested_path = os.path.join(temp_dir, "render.wav")
            doubled_path = requested_path + ".wav"
            sf.write(requested_path, np.zeros(100, dtype="float32"), 48000)
            old_time = os.path.getmtime(requested_path) - 30.0
            os.utime(requested_path, (old_time, old_time))
            sf.write(doubled_path, 0.1 * np.ones(100, dtype="float32"), 48000)
            result = server._wait_for_stable_export_file(
                requested_path,
                timeout_seconds=0.1,
                poll_interval_seconds=0.05,
                stable_polls=1,
            )
        self.assertEqual(result["resolved_file_path"], doubled_path)
        self.assertTrue(result["path_normalized"])

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

    def test_track_scope_supports_master_bus_device_chain_and_parameters(self):
        fake = FakeAbleton()
        with mock.patch.object(server, "get_ableton_connection", return_value=fake):
            append_payload = json.loads(server.append_browser_device(None, 0, "query:AudioFx#Utility", track_scope="master"))
            track_payload = json.loads(server.get_track_info(None, 0, track_scope="master"))
            devices_payload = json.loads(server.get_track_devices(None, 0, track_scope="master"))
            parameter_payload = json.loads(server.get_device_parameters(None, 0, 0, track_scope="master"))
            set_payload = json.loads(server.set_device_parameter(None, 0, 0, 0, -1.0, track_scope="master"))
        self.assertEqual(append_payload["track_scope"], "master")
        self.assertEqual(track_payload["track_scope"], "master")
        self.assertEqual(devices_payload["track_scope"], "master")
        self.assertEqual(parameter_payload["track_scope"], "master")
        self.assertEqual(set_payload["track_scope"], "master")
        self.assertEqual(track_payload["devices"][0]["name"], "Utility")
        self.assertIsNone(track_payload["mute"])
        self.assertIsNone(track_payload["solo"])
        self.assertIsNone(track_payload["arm"])
        self.assertEqual(set_payload["display_value"], "-1.0 dB")

    def test_append_mastering_chain_blocks_on_legacy_remote_script(self):
        fake = FakeAbleton()
        fake.remote_script_info_supported = False
        diagnostic = {
            "running_live_version": "12.3.6",
            "repo_script_path": "/repo/AbletonMCP_Remote_Script/__init__.py",
            "installed_script_path": "/Users/test/Library/Preferences/Ableton/Live 12.3.6/User Remote Scripts/AbletonMCP/__init__.py",
            "repo_sha256": "repo",
            "installed_sha256": "installed",
            "matches_repo": False,
            "discovered_install_paths": [],
        }
        with mock.patch.object(server, "_local_remote_script_install_data", return_value=diagnostic):
            with mock.patch.object(server, "get_ableton_connection", return_value=fake):
                payload = json.loads(server.append_mastering_chain(None, 0, "MINIMAL_TOUCH", track_scope="master"))
        self.assertEqual(payload["state"], "mastering-blocked")
        self.assertEqual(payload["failure_code"], "stale_remote_script")
        self.assertIn("track_scope_master", payload["missing_capabilities"])
        self.assertIn("ableton-mcp-install-remote-script", payload["reason"])

    def test_append_mastering_chain_blocks_when_capability_is_missing(self):
        fake = FakeAbleton()
        fake.remote_script_capabilities = [
            capability for capability in fake.remote_script_capabilities
            if capability != "track_scope_master"
        ]
        diagnostic = {
            "running_live_version": "12.3.6",
            "repo_script_path": "/repo/AbletonMCP_Remote_Script/__init__.py",
            "installed_script_path": "/Users/test/Library/Preferences/Ableton/Live 12.3.6/User Remote Scripts/AbletonMCP/__init__.py",
            "repo_sha256": "repo",
            "installed_sha256": "installed",
            "matches_repo": False,
            "discovered_install_paths": [],
        }
        with mock.patch.object(server, "_local_remote_script_install_data", return_value=diagnostic):
            with mock.patch.object(server, "get_ableton_connection", return_value=fake):
                payload = json.loads(server.append_mastering_chain(None, 0, "MINIMAL_TOUCH", track_scope="master"))
        self.assertEqual(payload["state"], "mastering-blocked")
        self.assertIn("track_scope_master", payload["missing_capabilities"])

    def test_append_mastering_chain_blocks_when_master_scope_aliases_to_track_zero(self):
        fake = FakeAbleton()
        fake.alias_master_scope_to_track = True
        diagnostic = {
            "running_live_version": "12.3.6",
            "repo_script_path": "/repo/AbletonMCP_Remote_Script/__init__.py",
            "installed_script_path": "/Users/test/Library/Preferences/Ableton/Live 12.3.6/User Remote Scripts/AbletonMCP/__init__.py",
            "repo_sha256": "repo",
            "installed_sha256": "installed",
            "matches_repo": False,
            "discovered_install_paths": [],
        }
        with mock.patch.object(server, "_local_remote_script_install_data", return_value=diagnostic):
            with mock.patch.object(server, "get_ableton_connection", return_value=fake):
                payload = json.loads(server.append_mastering_chain(None, 0, "MINIMAL_TOUCH", track_scope="master"))
        self.assertEqual(payload["state"], "mastering-blocked")
        self.assertEqual(payload["failure_code"], "stale_remote_script")
        self.assertIn("track_scope_master", payload["missing_capabilities"])
        self.assertEqual(
            payload["remote_script_probe"]["behavior_checks"][0]["result_track_name"],
            "Drums",
        )

    def test_track_input_and_monitor_tools_round_trip(self):
        fake = FakeAbleton()
        with mock.patch.object(server, "get_ableton_connection", return_value=fake):
            before_routing = json.loads(server.get_track_input_routing(None, 1))
            after_routing = json.loads(server.set_track_input_routing(None, 1, "Ext. In", "Stereo"))
            before_monitor = json.loads(server.get_track_monitor_state(None, 1))
            after_monitor = json.loads(server.set_track_monitor_state(None, 1, state_name="in"))
        self.assertEqual(before_routing["routing"]["current_input_routing_type"]["display_name"], "No Input")
        self.assertEqual(after_routing["routing"]["current_input_routing_type"]["display_name"], "Ext. In")
        self.assertEqual(before_monitor["current_monitoring_state_name"], "auto")
        self.assertEqual(after_monitor["current_monitoring_state_name"], "in")

    def test_find_delete_device_and_arrangement_summary_tools(self):
        fake = FakeAbleton()
        with mock.patch.object(server, "get_ableton_connection", return_value=fake):
            json.loads(server.append_browser_device(None, 0, "query:AudioFx#Utility"))
            json.loads(server.append_browser_device(None, 0, "query:AudioFx#Limiter"))
            match_payload = json.loads(server.find_device_by_name(None, 0, "Limiter"))
            delete_payload = json.loads(server.delete_device(None, 0, 1))
            arrangement_payload = json.loads(server.get_arrangement_summary(None))
        self.assertEqual(match_payload["matches"][0]["name"], "Limiter")
        self.assertEqual(delete_payload["deleted_device_name"], "Limiter")
        self.assertEqual(arrangement_payload["file_path"], fake.file_path)
        self.assertEqual(arrangement_payload["detail_level"], "basic")
        self.assertEqual(arrangement_payload["track_count"], len(fake.tracks))
        self.assertNotIn("tracks", arrangement_payload)

    def test_get_arrangement_summary_detail_levels(self):
        fake = FakeAbleton()
        with mock.patch.object(server, "get_ableton_connection", return_value=fake):
            basic_payload = json.loads(server.get_arrangement_summary(None))
            extents_payload = json.loads(server.get_arrangement_summary(None, detail_level="track_extents"))
            clips_payload = json.loads(server.get_arrangement_summary(None, detail_level="clips"))
        self.assertEqual(basic_payload["detail_level"], "basic")
        self.assertNotIn("tracks", basic_payload)
        self.assertEqual(extents_payload["detail_level"], "track_extents")
        self.assertIn("tracks", extents_payload)
        self.assertNotIn("clips", extents_payload["tracks"][0])
        self.assertEqual(clips_payload["detail_level"], "clips")
        self.assertIn("clips", clips_payload["tracks"][0])

    def test_master_scope_probe_avoids_get_track_info(self):
        fake = FakeAbleton()
        fake.break_master_track_info = True
        probe = server._probe_remote_script_capabilities_data(
            fake,
            required_capabilities=list(server.REMOTE_SCRIPT_MASTERING_REQUIRED_CAPABILITIES),
            verify_master_scope=True,
        )
        self.assertTrue(probe["ok"])
        self.assertEqual(probe["behavior_checks"][0]["result_track_scope"], "master")

    def test_append_browser_device_on_master_avoids_get_track_info(self):
        fake = FakeAbleton()
        fake.break_master_track_info = True
        with mock.patch.object(server, "get_ableton_connection", return_value=fake):
            payload = json.loads(server.append_browser_device(None, 0, "query:AudioFx#Utility", track_scope="master"))
        self.assertTrue(payload["loaded"])
        self.assertEqual(payload["appended_devices"], ["Utility"])

    def test_get_arrangement_summary_reports_timeout_structuredly(self):
        fake = mock.Mock()
        fake.send_command.side_effect = Exception("Timeout waiting for Ableton response")
        with mock.patch.object(server, "get_ableton_connection", return_value=fake):
            payload = json.loads(server.get_arrangement_summary(None, detail_level="track_extents", timeout_seconds=0.1))
        self.assertEqual(payload["state"], "failed")
        self.assertEqual(payload["failure_code"], "command_timeout")
        self.assertEqual(payload["detail_level"], "track_extents")

    def test_create_premaster_routing_verifies_bus_controls_and_unblocks(self):
        fake = FakeAbleton()
        with mock.patch.object(server, "get_ableton_connection", return_value=fake):
            payload = server.create_premaster_routing(None)
        result = json.loads(payload)
        self.assertFalse(result["blocked"])
        self.assertEqual(result["state"], "export-ready")
        self.assertEqual(result["premaster_track_name"], "PREMASTER")
        self.assertEqual(result["premaster_monitor_state"]["current_monitoring_state_name"], "in")
        self.assertEqual(result["routing_safety"]["probe_failures"], [])

    def test_create_premaster_routing_blocks_on_legacy_remote_script(self):
        fake = FakeAbleton()
        fake.remote_script_info_supported = False
        diagnostic = {
            "running_live_version": "12.3.6",
            "repo_script_path": "/repo/AbletonMCP_Remote_Script/__init__.py",
            "installed_script_path": "/Users/test/Library/Preferences/Ableton/Live 12.3.6/User Remote Scripts/AbletonMCP/__init__.py",
            "repo_sha256": "repo",
            "installed_sha256": "installed",
            "matches_repo": False,
            "discovered_install_paths": [],
        }
        with mock.patch.object(server, "_local_remote_script_install_data", return_value=diagnostic):
            with mock.patch.object(server, "get_ableton_connection", return_value=fake):
                payload = json.loads(server.create_premaster_routing(None))
        self.assertTrue(payload["blocked"])
        self.assertEqual(payload["state"], "export-blocked")
        self.assertEqual(payload["failure_code"], "stale_remote_script")
        self.assertIn("ableton-mcp-install-remote-script", payload["reason"])

    def test_sample_track_meter_supports_return_scope(self):
        fake = FakeAbleton()
        with mock.patch.object(server, "get_ableton_connection", return_value=fake):
            with mock.patch("time.sleep", return_value=None):
                payload = json.loads(server.sample_track_meter(None, 0, track_scope="return", duration_seconds=0.2, interval_ms=100))
        self.assertEqual(payload["track_scope"], "return")
        self.assertEqual(payload["sample_count"], 2)

    def test_export_audio_macos_blocks_on_preflight_failure(self):
        export_payload = {
            "state": "export-blocked",
            "requested_file_path": "/tmp/codex-export-tests/Test EXPORT.wav",
            "preflight": {
                "ok": False,
                "failure_code": "accessibility_unavailable",
                "reason": "UI scripting is disabled.",
            },
            "ui_automation": {
                "ok": False,
                "failure_code": "accessibility_unavailable",
                "reason": "UI scripting is disabled.",
                "stages": [],
            },
            "reason": "UI scripting is disabled.",
        }
        with mock.patch.object(server.macos_export, "run_export_audio_ui", return_value=export_payload):
            result = json.loads(server.export_audio_macos(None, "/tmp/codex-export-tests", "Test EXPORT.wav"))
        self.assertEqual(result["state"], "export-blocked")
        self.assertEqual(result["failure_code"], "accessibility_unavailable")
        self.assertEqual(result["preflight"]["failure_code"], "accessibility_unavailable")

    def test_export_audio_macos_fails_when_post_export_validation_fails(self):
        export_ready = {
            "state": "export-ready",
            "requested_file_path": "/tmp/codex-export-tests/Test EXPORT.wav",
            "preflight": {"ok": True, "failure_code": None},
            "ui_automation": {"ok": True, "failure_code": None, "stages": []},
        }
        validation_failed = {
            "state": "export-failed",
            "requested_file_path": "/tmp/codex-export-tests/Test EXPORT.wav",
            "resolved_file_path": "/tmp/codex-export-tests/Test EXPORT.wav",
            "reason": "Export validation failed.",
            "export_validation": {"failed_checks": ["sample_peak_below_threshold"]},
            "preview": {"attempted": True, "status": "failed"},
        }
        with mock.patch.object(server.macos_export, "run_export_audio_ui", return_value=export_ready):
            with mock.patch.object(server, "_validate_audio_export_data", return_value=validation_failed):
                result = json.loads(server.export_audio_macos(None, "/tmp/codex-export-tests", "Test EXPORT.wav"))
        self.assertEqual(result["state"], "export-failed")
        self.assertEqual(result["failure_code"], "post_export_validation_failed")
        self.assertIn("sample_peak_below_threshold", result["export_validation"]["failed_checks"])

    def test_master_and_export_opened_set_refuses_implicit_file_fallback(self):
        with mock.patch.object(server, "get_ableton_connection", side_effect=RuntimeError("Live unavailable")):
            with mock.patch.object(server.macos_export, "run_export_audio_ui") as export_mock:
                result = json.loads(server.master_and_export_opened_set(None, "/tmp/codex-export-tests", "Test EXPORT.wav"))
        self.assertEqual(result["state"], "export-blocked")
        self.assertEqual(result["source_provenance"]["state"], "export-blocked")
        export_mock.assert_not_called()

    def test_master_and_export_opened_set_blocks_on_stale_remote_script(self):
        fake = FakeAbleton()
        fake.remote_script_info_supported = False
        diagnostic = {
            "running_live_version": "12.3.6",
            "repo_script_path": "/repo/AbletonMCP_Remote_Script/__init__.py",
            "installed_script_path": "/Users/test/Library/Preferences/Ableton/Live 12.3.6/User Remote Scripts/AbletonMCP/__init__.py",
            "repo_sha256": "repo",
            "installed_sha256": "installed",
            "matches_repo": False,
            "discovered_install_paths": [],
        }
        with mock.patch.object(server, "_local_remote_script_install_data", return_value=diagnostic):
            with mock.patch.object(server, "get_ableton_connection", return_value=fake):
                with mock.patch.object(server.macos_export, "run_export_audio_ui") as export_mock:
                    result = json.loads(server.master_and_export_opened_set(None, "/tmp/codex-export-tests", "Test EXPORT.wav"))
        self.assertEqual(result["state"], "export-blocked")
        self.assertEqual(result["failure_code"], "stale_remote_script")
        self.assertEqual(result["remote_script_probe"]["legacy_remote_script"], True)
        export_mock.assert_not_called()

    def test_master_and_export_opened_set_surfaces_provenance_and_validation(self):
        fake = FakeAbleton()
        export_ready = {"state": "export-ready", "preflight": {"ok": True, "failure_code": None}, "ui_automation": {"ok": True, "failure_code": None, "stages": []}}
        analysis_validation = {
            "state": "export-validated",
            "requested_file_path": "/tmp/analysis/Test.__analysis__.wav",
            "resolved_file_path": "/tmp/analysis/Test.__analysis__.wav",
            "export_validation": {"failed_checks": [], "duration_seconds": 16.0, "lufs_i": -12.0, "true_peak_dbtp": -0.2},
            "preview": {"attempted": False, "status": "skipped"},
        }
        final_validation = {
            "state": "export-validated",
            "requested_file_path": "/tmp/codex-export-tests/Test EXPORT.wav",
            "resolved_file_path": "/tmp/codex-export-tests/Test EXPORT.wav",
            "export_validation": {"failed_checks": [], "duration_seconds": 16.0, "lufs_i": -14.0, "true_peak_dbtp": -1.0},
            "preview": {"attempted": True, "status": "played"},
        }
        with mock.patch.object(server, "get_ableton_connection", return_value=fake):
            with mock.patch.object(server.macos_export, "run_export_audio_ui", side_effect=[
                dict(export_ready, requested_file_path="/tmp/analysis/Test.__analysis__.wav"),
                dict(export_ready, requested_file_path="/tmp/codex-export-tests/Test EXPORT.wav"),
            ]):
                with mock.patch.object(server, "_validate_audio_export_data", side_effect=[analysis_validation, final_validation]):
                    result = json.loads(
                        server.master_and_export_opened_set(
                            None,
                            "/tmp/codex-export-tests",
                            "Test EXPORT.wav",
                            preset_name="MINIMAL_TOUCH",
                        )
                    )
        self.assertEqual(result["state"], "export-validated")
        self.assertEqual(result["source_provenance"]["actual_source_used"], "opened-live-set")
        self.assertEqual(result["mastering"]["preset_name"], "MINIMAL_TOUCH")
        self.assertEqual(result["measurement_mode"], "offline_render")
        self.assertEqual(result["resolved_file_path"], "/tmp/codex-export-tests/Test EXPORT.wav")
        self.assertEqual(result["export_validation"]["failed_checks"], [])
        self.assertEqual(result["analysis_render"]["resolved_file_path"], "/tmp/analysis/Test.__analysis__.wav")

    def test_diagnose_remote_script_install_reports_hashes_and_capabilities(self):
        fake = FakeAbleton()
        diagnostic = {
            "running_live_version": "12.3.6",
            "repo_script_path": "/repo/AbletonMCP_Remote_Script/__init__.py",
            "installed_script_path": "/Users/test/Library/Preferences/Ableton/Live 12.3.6/User Remote Scripts/AbletonMCP/__init__.py",
            "repo_sha256": "repohash",
            "installed_sha256": "repohash",
            "matches_repo": True,
            "discovered_install_paths": [
                "/Users/test/Library/Preferences/Ableton/Live 12.3.6/User Remote Scripts/AbletonMCP/__init__.py"
            ],
        }
        with mock.patch.object(server, "_local_remote_script_install_data", return_value=diagnostic):
            with mock.patch.object(server, "get_ableton_connection", return_value=fake):
                result = json.loads(server.diagnose_remote_script_install(None))
        self.assertEqual(result["running_live_version"], "12.3.6")
        self.assertTrue(result["matches_repo"])
        self.assertEqual(result["remote_script_connection_state"], "available")
        self.assertEqual(result["remote_script_info"]["script_name"], "AbletonMCP")

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

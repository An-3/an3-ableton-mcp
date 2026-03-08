# ableton_mcp_server.py
from mcp.server.fastmcp import FastMCP, Context
import math
import os
import socket
import json
import logging
from dataclasses import dataclass
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any, List, Optional, Union

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AbletonMCPServer")

VALID_TOOL_PROFILES = {"all", "core"}
VALID_RESPONSE_PROFILES = {"compat", "compact"}
DEFAULT_TOOL_PROFILE = "all"
DEFAULT_RESPONSE_PROFILE = "compat"
CORE_TOOL_NAMES = {
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
TOOL_DESCRIPTIONS = {
    "get_session_info": "Get the current session tempo, signature, and track counts.",
    "get_track_info": "Get detailed information about one track.",
    "get_track_routing": "Get the current output routing for one track.",
    "get_transport_state": "Get transport state and arrangement export readiness.",
    "list_playing_clips": "List the session clips that are currently active.",
    "list_tracks": "List tracks with stable metadata.",
    "find_track_by_name": "Find a track by exact name.",
    "find_reference_tracks": "Find tracks whose names look like references.",
    "get_master_meter": "Get the current master output meter values.",
    "sample_master_meter": "Sample the master meter and report peak values.",
    "create_midi_track": "Create a MIDI track.",
    "create_audio_track": "Create an audio track.",
    "ensure_premaster_track": "Create or reuse a premaster track.",
    "set_track_name": "Rename a track.",
    "set_track_volume": "Set a track volume value.",
    "set_track_panning": "Set a track pan value.",
    "set_track_output_routing": "Set a track output routing target.",
    "create_premaster_routing": "Route tracks through a premaster track.",
    "get_device_parameters": "List parameters for a device on a track.",
    "set_device_parameter": "Set a device parameter value.",
    "load_audio_clip": "Load an audio file into a clip slot.",
    "append_browser_device": "Append a browser item to a track device chain.",
    "append_mastering_chain": "Append a stock mastering chain to a track.",
    "place_clip_in_arrangement": "Place a session clip into the arrangement.",
    "create_clip": "Create a MIDI clip in a clip slot.",
    "add_notes_to_clip": "Add notes to a MIDI clip.",
    "set_clip_name": "Rename a clip.",
    "set_tempo": "Set the session tempo.",
    "load_instrument_or_effect": "Load a browser item onto a track.",
    "fire_clip": "Start a clip.",
    "stop_clip": "Stop a clip.",
    "start_playback": "Start session playback.",
    "stop_playback": "Stop session playback.",
    "stop_all_clips": "Stop all session clips.",
    "back_to_arrangement": "Return playback to the arrangement.",
    "verify_arrangement_export_ready": "Check whether arrangement export is safe.",
    "get_browser_tree": "Browse the top-level Ableton browser tree.",
    "get_browser_items_at_path": "List browser items at a specific path.",
    "load_drum_kit": "Load a drum rack and a drum kit.",
    "analyze_audio_file": "Analyze a rendered audio file for loudness and peaks.",
}


def _normalize_profile(value: Optional[str], allowed: set[str], default: str, env_name: str) -> str:
    normalized = (value or default).strip().lower()
    if normalized in allowed:
        return normalized
    logger.warning("Invalid %s value '%s'; defaulting to '%s'", env_name, value, default)
    return default


def _active_tool_profile() -> str:
    return _normalize_profile(
        os.getenv("ABLETON_MCP_TOOL_PROFILE"),
        VALID_TOOL_PROFILES,
        DEFAULT_TOOL_PROFILE,
        "ABLETON_MCP_TOOL_PROFILE",
    )


def _active_response_profile() -> str:
    return _normalize_profile(
        os.getenv("ABLETON_MCP_RESPONSE_PROFILE"),
        VALID_RESPONSE_PROFILES,
        DEFAULT_RESPONSE_PROFILE,
        "ABLETON_MCP_RESPONSE_PROFILE",
    )


def _compact_response_enabled() -> bool:
    return _active_response_profile() == "compact"


def _should_register_tool(tool_name: str) -> bool:
    profile = _active_tool_profile()
    return profile == "all" or tool_name in CORE_TOOL_NAMES


def _tool_description(tool_name: str, explicit: Optional[str], docstring: Optional[str]) -> str:
    if explicit:
        return explicit.strip()
    if tool_name in TOOL_DESCRIPTIONS:
        return TOOL_DESCRIPTIONS[tool_name]
    if docstring:
        return docstring.strip().splitlines()[0]
    return tool_name.replace("_", " ")


class AbletonFastMCP(FastMCP):
    def tool(
        self,
        name: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        annotations=None,
        icons=None,
        meta: Optional[Dict[str, Any]] = None,
        structured_output: Optional[bool] = None,
    ):
        if callable(name):
            raise TypeError(
                "The @tool decorator was used incorrectly. Use @tool() instead of @tool."
            )

        def decorator(fn):
            tool_name = name or fn.__name__
            if not _should_register_tool(tool_name):
                return fn
            self.add_tool(
                fn,
                name=name,
                title=title,
                description=_tool_description(tool_name, description, fn.__doc__),
                annotations=annotations,
                icons=icons,
                meta=meta,
                structured_output=False if structured_output is None else structured_output,
            )
            return fn

        return decorator

@dataclass
class AbletonConnection:
    host: str
    port: int
    sock: socket.socket = None
    
    def connect(self) -> bool:
        """Connect to the Ableton Remote Script socket server"""
        if self.sock:
            return True
            
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            logger.info(f"Connected to Ableton at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Ableton: {str(e)}")
            self.sock = None
            return False
    
    def disconnect(self):
        """Disconnect from the Ableton Remote Script"""
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logger.error(f"Error disconnecting from Ableton: {str(e)}")
            finally:
                self.sock = None

    def receive_full_response(self, sock, buffer_size=8192):
        """Receive the complete response, potentially in multiple chunks"""
        chunks = []
        sock.settimeout(15.0)  # Increased timeout for operations that might take longer
        
        try:
            while True:
                try:
                    chunk = sock.recv(buffer_size)
                    if not chunk:
                        if not chunks:
                            raise Exception("Connection closed before receiving any data")
                        break
                    
                    chunks.append(chunk)
                    
                    # Check if we've received a complete JSON object
                    try:
                        data = b''.join(chunks)
                        json.loads(data.decode('utf-8'))
                        logger.info(f"Received complete response ({len(data)} bytes)")
                        return data
                    except json.JSONDecodeError:
                        # Incomplete JSON, continue receiving
                        continue
                except socket.timeout:
                    logger.warning("Socket timeout during chunked receive")
                    break
                except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
                    logger.error(f"Socket connection error during receive: {str(e)}")
                    raise
        except Exception as e:
            logger.error(f"Error during receive: {str(e)}")
            raise
            
        # If we get here, we either timed out or broke out of the loop
        if chunks:
            data = b''.join(chunks)
            logger.info(f"Returning data after receive completion ({len(data)} bytes)")
            try:
                json.loads(data.decode('utf-8'))
                return data
            except json.JSONDecodeError:
                raise Exception("Incomplete JSON response received")
        else:
            raise Exception("No data received")

    def send_command(self, command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Send a command to Ableton and return the response"""
        if not self.sock and not self.connect():
            raise ConnectionError("Not connected to Ableton")
        
        command = {
            "type": command_type,
            "params": params or {}
        }
        
        # Check if this is a state-modifying command
        is_modifying_command = command_type in [
            "create_midi_track", "create_audio_track", "set_track_name",
            "set_track_volume", "set_track_panning", "create_clip",
            "add_notes_to_clip", "set_clip_name", "set_tempo", "fire_clip",
            "stop_clip", "set_device_parameter", "start_playback",
            "stop_playback", "load_instrument_or_effect", "load_browser_item",
            "load_audio_clip", "place_clip_in_arrangement",
            "set_track_output_routing", "stop_all_clips",
            "back_to_arrangement"
        ]
        
        try:
            logger.info(f"Sending command: {command_type} with params: {params}")
            
            # Send the command
            self.sock.sendall(json.dumps(command).encode('utf-8'))
            logger.info(f"Command sent, waiting for response...")
            
            # For state-modifying commands, add a small delay to give Ableton time to process
            if is_modifying_command:
                import time
                time.sleep(0.1)  # 100ms delay
            
            # Set timeout based on command type
            timeout = 15.0 if is_modifying_command else 10.0
            self.sock.settimeout(timeout)
            
            # Receive the response
            response_data = self.receive_full_response(self.sock)
            logger.info(f"Received {len(response_data)} bytes of data")
            
            # Parse the response
            response = json.loads(response_data.decode('utf-8'))
            logger.info(f"Response parsed, status: {response.get('status', 'unknown')}")
            
            if response.get("status") == "error":
                logger.error(f"Ableton error: {response.get('message')}")
                raise Exception(response.get("message", "Unknown error from Ableton"))
            
            # For state-modifying commands, add another small delay after receiving response
            if is_modifying_command:
                import time
                time.sleep(0.1)  # 100ms delay
            
            return response.get("result", {})
        except socket.timeout:
            logger.error("Socket timeout while waiting for response from Ableton")
            self.sock = None
            raise Exception("Timeout waiting for Ableton response")
        except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
            logger.error(f"Socket connection error: {str(e)}")
            self.sock = None
            raise Exception(f"Connection to Ableton lost: {str(e)}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON response from Ableton: {str(e)}")
            if 'response_data' in locals() and response_data:
                logger.error(f"Raw response (first 200 bytes): {response_data[:200]}")
            self.sock = None
            raise Exception(f"Invalid response from Ableton: {str(e)}")
        except Exception as e:
            logger.error(f"Error communicating with Ableton: {str(e)}")
            self.sock = None
            raise Exception(f"Communication error with Ableton: {str(e)}")

@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """Manage server startup and shutdown lifecycle"""
    try:
        logger.info("AbletonMCP server starting up")
        
        try:
            ableton = get_ableton_connection()
            logger.info("Successfully connected to Ableton on startup")
        except Exception as e:
            logger.warning(f"Could not connect to Ableton on startup: {str(e)}")
            logger.warning("Make sure the Ableton Remote Script is running")
        
        yield {}
    finally:
        global _ableton_connection
        if _ableton_connection:
            logger.info("Disconnecting from Ableton on shutdown")
            _ableton_connection.disconnect()
            _ableton_connection = None
        logger.info("AbletonMCP server shut down")

# Create the MCP server with lifespan support
mcp = AbletonFastMCP(
    "AbletonMCP",
    instructions="Ableton Live integration through the Model Context Protocol",
    lifespan=server_lifespan
)

# Global connection for resources
_ableton_connection = None

MASTERING_PRESET_DEVICE_URIS = {
    "STREAM_SAFE_TRANSPARENT": [
        "query:AudioFx#Utility",
        "query:AudioFx#EQ%20Eight",
        "query:AudioFx#Glue%20Compressor",
        "query:AudioFx#Saturator",
        "query:AudioFx#Limiter",
    ],
    "STREAM_LOUD_CONTROLLED": [
        "query:AudioFx#Utility",
        "query:AudioFx#EQ%20Eight",
        "query:AudioFx#Compressor",
        "query:AudioFx#Multiband%20Dynamics",
        "query:AudioFx#Limiter",
    ],
    "CLUB_IMPACT": [
        "query:AudioFx#Utility",
        "query:AudioFx#EQ%20Eight",
        "query:AudioFx#Glue%20Compressor",
        "query:AudioFx#Saturator",
        "query:AudioFx#Limiter",
    ],
    "SUB_TIGHT": [
        "query:AudioFx#Utility",
        "query:AudioFx#EQ%20Eight",
        "query:AudioFx#Multiband%20Dynamics",
        "query:AudioFx#Saturator",
        "query:AudioFx#Limiter",
    ],
    "VOCAL_FORWARD": [
        "query:AudioFx#Utility",
        "query:AudioFx#EQ%20Eight",
        "query:AudioFx#Glue%20Compressor",
        "query:AudioFx#Limiter",
    ],
    "HARSH_SOFTENER": [
        "query:AudioFx#Utility",
        "query:AudioFx#EQ%20Eight",
        "query:AudioFx#Multiband%20Dynamics",
        "query:AudioFx#Limiter",
    ],
    "WIDE_TOPS": [
        "query:AudioFx#Utility",
        "query:AudioFx#EQ%20Eight",
        "query:AudioFx#Saturator",
        "query:AudioFx#Limiter",
    ],
    "MINIMAL_TOUCH": [
        "query:AudioFx#Utility",
        "query:AudioFx#EQ%20Eight",
        "query:AudioFx#Limiter",
    ],
}

REFERENCE_TRACK_KEYWORDS = ("reference", "ref", "a/b", "ab")
MAIN_ROUTING_CANDIDATES = ("Main", "Master")

def get_ableton_connection():
    """Get or create a persistent Ableton connection"""
    global _ableton_connection
    
    if _ableton_connection is not None:
        try:
            # Test the connection with a simple ping
            # We'll try to send an empty message, which should fail if the connection is dead
            # but won't affect Ableton if it's alive
            _ableton_connection.sock.settimeout(1.0)
            _ableton_connection.sock.sendall(b'')
            return _ableton_connection
        except Exception as e:
            logger.warning(f"Existing connection is no longer valid: {str(e)}")
            try:
                _ableton_connection.disconnect()
            except:
                pass
            _ableton_connection = None
    
    # Connection doesn't exist or is invalid, create a new one
    if _ableton_connection is None:
        # Try to connect up to 3 times with a short delay between attempts
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(f"Connecting to Ableton (attempt {attempt}/{max_attempts})...")
                _ableton_connection = AbletonConnection(host="localhost", port=9877)
                if _ableton_connection.connect():
                    logger.info("Created new persistent connection to Ableton")
                    
                    # Validate connection with a simple command
                    try:
                        # Get session info as a test
                        _ableton_connection.send_command("get_session_info")
                        logger.info("Connection validated successfully")
                        return _ableton_connection
                    except Exception as e:
                        logger.error(f"Connection validation failed: {str(e)}")
                        _ableton_connection.disconnect()
                        _ableton_connection = None
                        # Continue to next attempt
                else:
                    _ableton_connection = None
            except Exception as e:
                logger.error(f"Connection attempt {attempt} failed: {str(e)}")
                if _ableton_connection:
                    _ableton_connection.disconnect()
                    _ableton_connection = None
            
            # Wait before trying again, but only if we have more attempts left
            if attempt < max_attempts:
                import time
                time.sleep(1.0)
        
        # If we get here, all connection attempts failed
        if _ableton_connection is None:
            logger.error("Failed to connect to Ableton after multiple attempts")
            raise Exception("Could not connect to Ableton. Make sure the Remote Script is running.")
    
    return _ableton_connection


def _linear_to_db(value: float) -> float:
    if value <= 0.0:
        return -120.0
    return 20.0 * math.log10(value)


def _json_response(data: Any) -> str:
    return json.dumps(data, separators=(",", ":"), ensure_ascii=True)


def _current_routing_payload(routing: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    routing = routing or {}
    return {
        "current_output_routing_type": routing.get("current_output_routing_type"),
        "current_output_routing_channel": routing.get("current_output_routing_channel"),
    }


def _compact_routing_payload(track_routing: Dict[str, Any]) -> Dict[str, Any]:
    routing = track_routing.get("routing", {}) or {}
    return {
        "index": track_routing.get("index"),
        "name": track_routing.get("name"),
        "routing": {
            **_current_routing_payload(routing),
            "available_output_routing_type_count": len(routing.get("available_output_routing_types", []) or []),
            "available_output_routing_channel_count": len(routing.get("available_output_routing_channels", []) or []),
        },
    }


def _compact_track_summary(track: Dict[str, Any]) -> Dict[str, Any]:
    playback_state = track.get("playback_state", {}) or {}
    clip_slots = track.get("clip_slots", []) or []
    devices = track.get("devices", []) or []
    return {
        "index": track.get("index"),
        "name": track.get("name"),
        "is_audio_track": track.get("is_audio_track"),
        "is_midi_track": track.get("is_midi_track"),
        "mute": track.get("mute"),
        "solo": track.get("solo"),
        "arm": track.get("arm"),
        "volume": track.get("volume"),
        "panning": track.get("panning"),
        "device_count": track.get("device_count", len(devices)),
        "clip_slot_count": track.get("clip_slot_count", len(clip_slots)),
        "playback_state": {
            "playing_slot_index": playback_state.get("playing_slot_index"),
            "fired_slot_index": playback_state.get("fired_slot_index"),
            "arrangement_playing": playback_state.get("arrangement_playing"),
            "track_stopped": playback_state.get("track_stopped"),
        },
        "routing": _current_routing_payload(track.get("routing")),
    }


def _compact_transport_summary(transport_state: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "is_playing": transport_state.get("is_playing"),
        "current_song_time": transport_state.get("current_song_time"),
        "playing_clip_count": transport_state.get("playing_clip_count"),
        "arrangement_state_known": transport_state.get("arrangement_state_known"),
        "session_override_active": transport_state.get("session_override_active"),
        "session_override_detection": transport_state.get("session_override_detection"),
        "back_to_arrangement_source": transport_state.get("back_to_arrangement_source"),
        "arrangement_export_ready": transport_state.get("arrangement_export_ready"),
    }


def _compact_stop_all_clips_result(result: Dict[str, Any]) -> Dict[str, Any]:
    transport_state = result.get("transport_state", {}) or {}
    return {
        "method": result.get("method"),
        "stopped": result.get("stopped"),
        "playing_clip_count_before": result.get("playing_clip_count_before"),
        "playing_clip_count_after": result.get("playing_clip_count_after"),
        "session_override_active": transport_state.get("session_override_active"),
        "arrangement_export_ready": transport_state.get("arrangement_export_ready"),
    }


def _compact_back_to_arrangement_result(result: Dict[str, Any]) -> Dict[str, Any]:
    compact = {
        "method": result.get("method"),
        "action": result.get("action"),
        "fallback_used": result.get("fallback_used"),
        "playing_clip_count_before": len(result.get("playing_clips_before", []) or []),
        "playing_clip_count_after": len(result.get("playing_clips_after", []) or []),
        "arrangement_export_ready": result.get("arrangement_export_ready"),
    }
    if result.get("warning"):
        compact["warning"] = result.get("warning")
    return compact


def _compact_browser_items_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    items = result.get("items", []) or []
    capped_items = items[:25]
    return {
        "path": result.get("path"),
        "name": result.get("name"),
        "uri": result.get("uri"),
        "is_folder": result.get("is_folder"),
        "is_device": result.get("is_device"),
        "is_loadable": result.get("is_loadable"),
        "total_items": len(items),
        "truncated": len(capped_items) < len(items),
        "items": capped_items,
    }


def _compact_append_browser_device_result(result: Dict[str, Any]) -> Dict[str, Any]:
    appended_names = result.get("appended_devices", []) or []
    final_names = result.get("devices_after", []) or []
    return {
        "track_index": result.get("track_index"),
        "item_uri": result.get("item_uri"),
        "loaded": result.get("loaded"),
        "item_name": result.get("item_name"),
        "appended_device_names": appended_names,
        "final_device_count": len(final_names),
    }


def _compact_append_mastering_chain_result(result: Dict[str, Any]) -> Dict[str, Any]:
    steps = result.get("steps", []) or []
    appended_device_names = []
    loaded_count = 0
    for step in steps:
        if step.get("loaded"):
            loaded_count += 1
        appended_device_names.extend(step.get("appended_devices", []) or [])
    return {
        "track_index": result.get("track_index"),
        "preset_name": result.get("preset_name"),
        "loaded_count": loaded_count,
        "appended_device_names": appended_device_names,
        "final_device_count": len(result.get("final_devices", []) or []),
    }


def _track_payload_for_response(track: Dict[str, Any]) -> Dict[str, Any]:
    if _compact_response_enabled():
        return _compact_track_summary(track)
    return track


def _tracks_payload_for_response(tracks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if _compact_response_enabled():
        return [_compact_track_summary(track) for track in tracks]
    result = []
    for track in tracks:
        result.append({
            "index": track.get("index"),
            "name": track.get("name"),
            "is_audio_track": track.get("is_audio_track"),
            "is_midi_track": track.get("is_midi_track"),
            "volume": track.get("volume"),
            "panning": track.get("panning"),
            "device_count": len(track.get("devices", [])),
            "routing": track.get("routing"),
            "playback_state": track.get("playback_state"),
        })
    return result


def _list_tracks_data(ableton: AbletonConnection) -> List[Dict[str, Any]]:
    session = ableton.send_command("get_session_info")
    track_count = int(session.get("track_count", 0))
    tracks = []
    for track_index in range(track_count):
        tracks.append(ableton.send_command("get_track_info", {"track_index": track_index}))
    return tracks


def _list_track_summaries_data(ableton: AbletonConnection) -> List[Dict[str, Any]]:
    result = ableton.send_command("list_tracks_summary")
    return result or []


def _get_track_data(ableton: AbletonConnection, track_index: int, summary: bool = False) -> Dict[str, Any]:
    command_type = "get_track_summary" if summary else "get_track_info"
    return ableton.send_command(command_type, {"track_index": track_index})


def _get_transport_state_data(ableton: AbletonConnection) -> Dict[str, Any]:
    return ableton.send_command("get_transport_state")


def _list_playing_clips_data(ableton: AbletonConnection) -> Dict[str, Any]:
    result = ableton.send_command("list_playing_clips")
    if isinstance(result, dict):
        result.setdefault("playing_clips", [])
        result.setdefault("count", len(result.get("playing_clips", [])))
        return result
    return {
        "playing_clips": result or [],
        "count": len(result or []),
    }


def _verify_arrangement_export_ready_data(ableton: AbletonConnection) -> Dict[str, Any]:
    transport_state = _get_transport_state_data(ableton)
    playing_payload = _list_playing_clips_data(ableton)
    playing_clips = playing_payload.get("playing_clips", [])
    session_override_active = transport_state.get("session_override_active")
    arrangement_state_known = bool(transport_state.get("arrangement_state_known"))

    issues = []
    recommended_action = "Arrangement playback is safe to export."
    verification_level = "verified" if arrangement_state_known else "best_effort"
    ready = bool(
        arrangement_state_known and
        session_override_active is False and
        not playing_clips
    )

    if playing_clips:
        issues.append("active_session_clips")
    if session_override_active is True:
        issues.append("session_override_active")
    if not arrangement_state_known:
        issues.append("arrangement_state_unverified")

    if not ready:
        if "active_session_clips" in issues or "session_override_active" in issues:
            recommended_action = "Call back_to_arrangement() and verify again before export."
        else:
            recommended_action = (
                "Restore Arrangement playback manually with Back to Arrangement, "
                "confirm clips are no longer gray, then verify again before export."
            )

    return {
        "ready": ready,
        "issues": issues,
        "verification_level": verification_level,
        "recommended_action": recommended_action,
        "transport_state": transport_state,
        "playing_clips": playing_clips,
    }


def _find_track_by_name_data(tracks: List[Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
    wanted = name.strip().lower()
    for track in tracks:
        if track.get("name", "").strip().lower() == wanted:
            return track
    return None


def _find_reference_tracks_data(tracks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    matches = []
    for track in tracks:
        track_name = track.get("name", "").strip().lower()
        if any(keyword in track_name for keyword in REFERENCE_TRACK_KEYWORDS):
            matches.append(track)
    return matches


def _ensure_premaster_track_data(
    ableton: AbletonConnection,
    premaster_name: str = "PREMASTER"
) -> Dict[str, Any]:
    use_summary = _compact_response_enabled()
    tracks = _list_track_summaries_data(ableton) if use_summary else _list_tracks_data(ableton)
    existing = _find_track_by_name_data(tracks, premaster_name)
    if existing:
        return {"created": False, "track": existing}

    created = ableton.send_command("create_audio_track", {"index": -1})
    track_index = created.get("index")
    if track_index is None:
        raise Exception("create_audio_track did not return an index")

    ableton.send_command("set_track_name", {
        "track_index": track_index,
        "name": premaster_name,
    })
    track = _get_track_data(ableton, track_index, summary=use_summary)
    return {"created": True, "track": track}


def _append_browser_device_data(
    ableton: AbletonConnection,
    track_index: int,
    item_uri: str
) -> Dict[str, Any]:
    before = ableton.send_command("get_track_info", {"track_index": track_index})
    before_names = [device.get("name", "") for device in before.get("devices", [])]

    load_result = ableton.send_command("load_browser_item", {
        "track_index": track_index,
        "item_uri": item_uri,
    })

    after = ableton.send_command("get_track_info", {"track_index": track_index})
    after_names = [device.get("name", "") for device in after.get("devices", [])]
    appended = after_names[len(before_names):] if len(after_names) >= len(before_names) else []

    return {
        "track_index": track_index,
        "item_uri": item_uri,
        "loaded": load_result.get("loaded", False),
        "item_name": load_result.get("item_name", ""),
        "devices_before": before_names,
        "devices_after": after_names,
        "appended_devices": appended,
    }


def _resolve_main_routing_name(routing_options: List[Dict[str, Any]]) -> Optional[str]:
    for candidate in MAIN_ROUTING_CANDIDATES:
        for option in routing_options:
            if option.get("display_name", "") == candidate:
                return candidate
    return routing_options[0].get("display_name") if routing_options else None


def _short_term_loudness_max(data, rate: int) -> Optional[float]:
    import numpy as np
    import pyloudnorm as pyln

    if data.ndim == 1:
        data = data[:, np.newaxis]

    total_samples = data.shape[0]
    window_samples = int(rate * 3.0)
    hop_samples = int(rate * 1.0)
    meter = pyln.Meter(rate)

    if total_samples <= window_samples:
        value = meter.integrated_loudness(data)
        return float(value) if np.isfinite(value) else None

    values = []
    for start in range(0, total_samples - window_samples + 1, hop_samples):
        window = data[start:start + window_samples]
        loudness = meter.integrated_loudness(window)
        if np.isfinite(loudness):
            values.append(float(loudness))

    if not values:
        return None
    return max(values)


def _true_peak_linear(data) -> float:
    import numpy as np
    from scipy.signal import resample_poly

    if data.ndim == 1:
        data = data[:, np.newaxis]

    peak = 0.0
    for channel_index in range(data.shape[1]):
        oversampled = resample_poly(data[:, channel_index], 4, 1)
        if oversampled.size:
            peak = max(peak, float(np.max(np.abs(oversampled))))
    return peak


def _analyze_audio_file_data(file_path: str) -> Dict[str, Any]:
    import numpy as np
    import pyloudnorm as pyln
    import soundfile as sf

    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(abs_path)

    data, rate = sf.read(abs_path, always_2d=True)
    duration_seconds = float(len(data) / float(rate)) if rate else 0.0
    meter = pyln.Meter(rate)

    lufs_i = float(meter.integrated_loudness(data))
    lra = float(meter.loudness_range(data))
    lufs_s_max = _short_term_loudness_max(data, rate)

    sample_peak_linear = float(np.max(np.abs(data))) if data.size else 0.0
    true_peak_linear = _true_peak_linear(data)

    return {
        "file_path": abs_path,
        "sample_rate": int(rate),
        "channels": int(data.shape[1]) if data.ndim > 1 else 1,
        "duration_seconds": duration_seconds,
        "lufs_i": lufs_i,
        "lufs_s_max": lufs_s_max,
        "lra": lra,
        "true_peak_dbtp": _linear_to_db(true_peak_linear),
        "sample_peak_dbfs": _linear_to_db(sample_peak_linear),
    }


# Core Tool endpoints

@mcp.tool()
def get_session_info(ctx: Context) -> str:
    """Get detailed information about the current Ableton session"""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_session_info")
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error getting session info from Ableton: {str(e)}")
        return f"Error getting session info: {str(e)}"

@mcp.tool()
def get_track_info(ctx: Context, track_index: int) -> str:
    """
    Get detailed information about a specific track in Ableton.
    
    Parameters:
    - track_index: The index of the track to get information about
    """
    try:
        ableton = get_ableton_connection()
        result = _get_track_data(ableton, track_index, summary=_compact_response_enabled())
        return _json_response(_track_payload_for_response(result))
    except Exception as e:
        logger.error(f"Error getting track info from Ableton: {str(e)}")
        return f"Error getting track info: {str(e)}"


@mcp.tool()
def get_track_routing(ctx: Context, track_index: int) -> str:
    """
    Get output routing information for a specific track.

    Parameters:
    - track_index: The index of the track to inspect
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_track_routing", {"track_index": track_index})
        if _compact_response_enabled():
            return _json_response(_compact_routing_payload(result))
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error getting track routing from Ableton: {str(e)}")
        return f"Error getting track routing: {str(e)}"


@mcp.tool()
def get_transport_state(ctx: Context) -> str:
    """Get transport status and Arrangement export-safety information."""
    try:
        ableton = get_ableton_connection()
        result = _get_transport_state_data(ableton)
        if _compact_response_enabled():
            return _json_response(_compact_transport_summary(result))
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error getting transport state: {str(e)}")
        return f"Error getting transport state: {str(e)}"


@mcp.tool()
def list_playing_clips(ctx: Context) -> str:
    """List the Session clips that are currently playing or fired."""
    try:
        ableton = get_ableton_connection()
        result = _list_playing_clips_data(ableton)
        if _compact_response_enabled():
            return _json_response({
                "count": result.get("count", 0),
                "playing_clips": result.get("playing_clips", []),
            })
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error listing playing clips: {str(e)}")
        return f"Error listing playing clips: {str(e)}"


@mcp.tool()
def list_tracks(ctx: Context) -> str:
    """List the current tracks with stable metadata."""
    try:
        ableton = get_ableton_connection()
        tracks = _list_track_summaries_data(ableton) if _compact_response_enabled() else _list_tracks_data(ableton)
        return _json_response(_tracks_payload_for_response(tracks))
    except Exception as e:
        logger.error(f"Error listing tracks: {str(e)}")
        return f"Error listing tracks: {str(e)}"


@mcp.tool()
def find_track_by_name(ctx: Context, name: str) -> str:
    """
    Find a track by case-insensitive exact name.

    Parameters:
    - name: Track name to search for
    """
    try:
        ableton = get_ableton_connection()
        tracks = _list_track_summaries_data(ableton) if _compact_response_enabled() else _list_tracks_data(ableton)
        match = _find_track_by_name_data(tracks, name)
        if match is None:
            return f"No track found with name '{name}'"
        return _json_response(_track_payload_for_response(match))
    except Exception as e:
        logger.error(f"Error finding track by name: {str(e)}")
        return f"Error finding track by name: {str(e)}"


@mcp.tool()
def find_reference_tracks(ctx: Context) -> str:
    """Find tracks whose names suggest they are references."""
    try:
        ableton = get_ableton_connection()
        tracks = _list_track_summaries_data(ableton) if _compact_response_enabled() else _list_tracks_data(ableton)
        matches = _find_reference_tracks_data(tracks)
        return _json_response([_track_payload_for_response(track) for track in matches])
    except Exception as e:
        logger.error(f"Error finding reference tracks: {str(e)}")
        return f"Error finding reference tracks: {str(e)}"

@mcp.tool()
def get_master_meter(ctx: Context) -> str:
    """
    Get real-time master output meter values and clipping status.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_master_meter")
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error getting master meter from Ableton: {str(e)}")
        return f"Error getting master meter: {str(e)}"


@mcp.tool()
def sample_master_meter(ctx: Context, duration_seconds: float = 5.0, interval_ms: int = 250) -> str:
    """
    Sample the master meter over a time window and report the maximum observed values.

    Parameters:
    - duration_seconds: Total duration to sample
    - interval_ms: Sampling interval in milliseconds
    """
    try:
        import time

        ableton = get_ableton_connection()
        interval_seconds = max(0.05, float(interval_ms) / 1000.0)
        duration_seconds = max(interval_seconds, float(duration_seconds))
        sample_count = max(1, int(math.ceil(duration_seconds / interval_seconds)))

        samples = []
        for _ in range(sample_count):
            samples.append(ableton.send_command("get_master_meter"))
            time.sleep(interval_seconds)

        peak_linear = max(sample.get("peak_linear") or 0.0 for sample in samples)
        level_linear = max(sample.get("level_linear") or 0.0 for sample in samples)
        result = {
            "duration_seconds": duration_seconds,
            "interval_ms": interval_ms,
            "sample_count": sample_count,
            "max_peak_linear": peak_linear,
            "max_peak_db": _linear_to_db(peak_linear),
            "max_level_linear": level_linear,
            "max_level_db": _linear_to_db(level_linear),
            "is_clipping": any(bool(sample.get("is_clipping")) for sample in samples),
            "samples": samples,
        }
        if _compact_response_enabled():
            result = {
                "duration_seconds": result["duration_seconds"],
                "interval_ms": result["interval_ms"],
                "sample_count": result["sample_count"],
                "max_peak_linear": result["max_peak_linear"],
                "max_peak_db": result["max_peak_db"],
                "max_level_linear": result["max_level_linear"],
                "max_level_db": result["max_level_db"],
                "is_clipping": result["is_clipping"],
            }
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error sampling master meter: {str(e)}")
        return f"Error sampling master meter: {str(e)}"

@mcp.tool()
def create_midi_track(ctx: Context, index: int = -1) -> str:
    """
    Create a new MIDI track in the Ableton session.
    
    Parameters:
    - index: The index to insert the track at (-1 = end of list)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_midi_track", {"index": index})
        return f"Created new MIDI track: {result.get('name', 'unknown')}"
    except Exception as e:
        logger.error(f"Error creating MIDI track: {str(e)}")
        return f"Error creating MIDI track: {str(e)}"


@mcp.tool()
def create_audio_track(ctx: Context, index: int = -1) -> str:
    """
    Create a new audio track in the Ableton session.

    Parameters:
    - index: The index to insert the track at (-1 = end of list)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_audio_track", {"index": index})
        return f"Created new audio track: {result.get('name', 'unknown')}"
    except Exception as e:
        logger.error(f"Error creating audio track: {str(e)}")
        return f"Error creating audio track: {str(e)}"


@mcp.tool()
def ensure_premaster_track(ctx: Context, name: str = "PREMASTER") -> str:
    """
    Ensure an audio track exists for mastering and return its metadata.

    Parameters:
    - name: Name of the premaster track
    """
    try:
        ableton = get_ableton_connection()
        result = _ensure_premaster_track_data(ableton, name)
        if _compact_response_enabled():
            result = {
                "created": result.get("created"),
                "track": _compact_track_summary(result.get("track", {})),
            }
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error ensuring premaster track: {str(e)}")
        return f"Error ensuring premaster track: {str(e)}"


@mcp.tool()
def set_track_name(ctx: Context, track_index: int, name: str) -> str:
    """
    Set the name of a track.
    
    Parameters:
    - track_index: The index of the track to rename
    - name: The new name for the track
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_name", {"track_index": track_index, "name": name})
        return f"Renamed track to: {result.get('name', name)}"
    except Exception as e:
        logger.error(f"Error setting track name: {str(e)}")
        return f"Error setting track name: {str(e)}"

@mcp.tool()
def set_track_volume(ctx: Context, track_index: int, volume: float) -> str:
    """
    Set the volume of a track.

    Parameters:
    - track_index: The index of the track
    - volume: Volume level from 0.0 to 1.0
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_volume", {"track_index": track_index, "volume": volume})
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error setting track volume: {str(e)}")
        return f"Error setting track volume: {str(e)}"

@mcp.tool()
def set_track_panning(ctx: Context, track_index: int, panning: float) -> str:
    """
    Set the panning of a track.

    Parameters:
    - track_index: The index of the track
    - panning: Panning from -1.0 (full left) to 1.0 (full right), 0.0 is center
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_panning", {"track_index": track_index, "panning": panning})
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error setting track panning: {str(e)}")
        return f"Error setting track panning: {str(e)}"


@mcp.tool()
def set_track_output_routing(
    ctx: Context,
    track_index: int,
    routing_type_name: str,
    routing_channel_name: Optional[str] = None
) -> str:
    """
    Set the output routing type and optional routing channel for a track.

    Parameters:
    - track_index: The index of the track
    - routing_type_name: Name of the routing target, such as PREMASTER or Main
    - routing_channel_name: Optional routing channel name, such as Stereo
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_output_routing", {
            "track_index": track_index,
            "routing_type_name": routing_type_name,
            "routing_channel_name": routing_channel_name,
        })
        if _compact_response_enabled():
            return _json_response(_compact_routing_payload(result))
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error setting track output routing: {str(e)}")
        return f"Error setting track output routing: {str(e)}"


@mcp.tool()
def create_premaster_routing(
    ctx: Context,
    premaster_name: str = "PREMASTER",
    source_track_indices: Optional[List[int]] = None,
    exclude_track_indices: Optional[List[int]] = None
) -> str:
    """
    Create or reuse a PREMASTER track and route the selected tracks into it.

    Parameters:
    - premaster_name: Name of the premaster track
    - source_track_indices: Optional explicit list of source track indices
    - exclude_track_indices: Optional list of track indices to keep out of PREMASTER
    """
    try:
        ableton = get_ableton_connection()
        premaster_result = _ensure_premaster_track_data(ableton, premaster_name)
        premaster_track = premaster_result["track"]
        premaster_index = premaster_track["index"]

        tracks = _list_track_summaries_data(ableton)
        exclude_indices = set(exclude_track_indices or [])
        exclude_indices.add(premaster_index)

        auto_reference_tracks = _find_reference_tracks_data(tracks)
        auto_reference_indices = {track["index"] for track in auto_reference_tracks}

        if source_track_indices is None:
            candidate_indices = [
                track["index"]
                for track in tracks
                if track["index"] not in exclude_indices and track["index"] not in auto_reference_indices
            ]
        else:
            candidate_indices = [
                track_index for track_index in source_track_indices
                if track_index not in exclude_indices
            ]

        routed_tracks = []
        for track_index in candidate_indices:
            ableton.send_command("set_track_output_routing", {
                "track_index": track_index,
                "routing_type_name": premaster_name,
            })
            routed_tracks.append(track_index)

        routing_info = ableton.send_command("get_track_routing", {"track_index": premaster_index})
        available_outputs = routing_info.get("routing", {}).get("available_output_routing_types", [])
        main_output_name = _resolve_main_routing_name(available_outputs)
        if main_output_name:
            ableton.send_command("set_track_output_routing", {
                "track_index": premaster_index,
                "routing_type_name": main_output_name,
            })

        result = {
            "premaster_created": premaster_result["created"],
            "premaster_track_index": premaster_index,
            "premaster_track_name": premaster_track["name"],
            "routed_track_indices": routed_tracks,
            "excluded_track_indices": sorted(exclude_indices),
            "auto_reference_track_indices": sorted(auto_reference_indices),
            "premaster_output_target": main_output_name,
        }
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error creating premaster routing: {str(e)}")
        return f"Error creating premaster routing: {str(e)}"

@mcp.tool()
def get_device_parameters(ctx: Context, track_index: int, device_index: int) -> str:
    """
    Get all parameters of a device on a track.

    Parameters:
    - track_index: The index of the track containing the device
    - device_index: The index of the device on the track
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_device_parameters", {
            "track_index": track_index, "device_index": device_index
        })
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error getting device parameters: {str(e)}")
        return f"Error getting device parameters: {str(e)}"

@mcp.tool()
def set_device_parameter(ctx: Context, track_index: int, device_index: int, parameter_index: int, value: float) -> str:
    """
    Set a specific parameter on a device.

    Parameters:
    - track_index: The index of the track containing the device
    - device_index: The index of the device on the track
    - parameter_index: The index of the parameter to set
    - value: The value to set the parameter to (will be clamped to valid range)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_device_parameter", {
            "track_index": track_index, "device_index": device_index,
            "parameter_index": parameter_index, "value": value
        })
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error setting device parameter: {str(e)}")
        return f"Error setting device parameter: {str(e)}"


@mcp.tool()
def load_audio_clip(ctx: Context, track_index: int, clip_index: int, file_path: str) -> str:
    """
    Load an audio file into a clip slot on an audio track.

    Parameters:
    - track_index: The index of the destination track
    - clip_index: The destination clip slot index
    - file_path: Absolute path to the source audio file
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("load_audio_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
            "file_path": file_path
        })
        if result.get("loaded", False):
            return (
                f"Loaded audio clip '{result.get('clip_name', '')}' from "
                f"'{result.get('file', file_path)}' into track {track_index}, slot {clip_index}"
            )
        return f"Failed to load audio clip from '{file_path}'"
    except Exception as e:
        logger.error(f"Error loading audio clip: {str(e)}")
        return f"Error loading audio clip: {str(e)}"


@mcp.tool()
def append_browser_device(ctx: Context, track_index: int, item_uri: str) -> str:
    """
    Append a stock device or browser item to the end of a track's device chain.

    Parameters:
    - track_index: The destination track index
    - item_uri: Browser URI, such as query:AudioFx#Utility
    """
    try:
        ableton = get_ableton_connection()
        result = _append_browser_device_data(ableton, track_index, item_uri)
        if _compact_response_enabled():
            return _json_response(_compact_append_browser_device_result(result))
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error appending browser device: {str(e)}")
        return f"Error appending browser device: {str(e)}"


@mcp.tool()
def append_mastering_chain(ctx: Context, track_index: int, preset_name: str) -> str:
    """
    Append a stock-device mastering chain to a track.

    Parameters:
    - track_index: The destination track index
    - preset_name: One of the DnB mastering preset names
    """
    try:
        ableton = get_ableton_connection()
        normalized_preset = preset_name.strip().upper()
        chain = MASTERING_PRESET_DEVICE_URIS.get(normalized_preset)
        if chain is None:
            available = ", ".join(sorted(MASTERING_PRESET_DEVICE_URIS.keys()))
            return f"Unknown preset '{preset_name}'. Available presets: {available}"

        appended = []
        for item_uri in chain:
            appended.append(_append_browser_device_data(ableton, track_index, item_uri))

        final_track = ableton.send_command("get_track_info", {"track_index": track_index})
        result = {
            "track_index": track_index,
            "preset_name": normalized_preset,
            "steps": appended,
            "final_devices": final_track.get("devices", []),
        }
        if _compact_response_enabled():
            return _json_response(_compact_append_mastering_chain_result(result))
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error appending mastering chain: {str(e)}")
        return f"Error appending mastering chain: {str(e)}"


@mcp.tool()
def place_clip_in_arrangement(ctx: Context, track_index: int, arrangement_time: float) -> str:
    """
    Place the audio clip from session slot 0 onto the arrangement timeline.

    Parameters:
    - track_index: The index of the source track
    - arrangement_time: Start time in beats for arrangement placement
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("place_clip_in_arrangement", {
            "track_index": track_index,
            "arrangement_time": arrangement_time
        })
        if result.get("placed", False):
            return (
                f"Placed clip from track {track_index} into arrangement at "
                f"{result.get('time')} beats"
            )
        return f"Failed to place clip from track {track_index} into arrangement"
    except Exception as e:
        logger.error(f"Error placing clip in arrangement: {str(e)}")
        return f"Error placing clip in arrangement: {str(e)}"


@mcp.tool()
def create_clip(ctx: Context, track_index: int, clip_index: int, length: float = 4.0) -> str:
    """
    Create a new MIDI clip in the specified track and clip slot.

    Parameters:
    - track_index: The index of the track to create the clip in
    - clip_index: The index of the clip slot to create the clip in
    - length: The length of the clip in beats (default: 4.0)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_clip", {
            "track_index": track_index, 
            "clip_index": clip_index, 
            "length": length
        })
        return f"Created new clip at track {track_index}, slot {clip_index} with length {length} beats"
    except Exception as e:
        logger.error(f"Error creating clip: {str(e)}")
        return f"Error creating clip: {str(e)}"

@mcp.tool()
def add_notes_to_clip(
    ctx: Context, 
    track_index: int, 
    clip_index: int, 
    notes: List[Dict[str, Union[int, float, bool]]]
) -> str:
    """
    Add MIDI notes to a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - notes: List of note dictionaries, each with pitch, start_time, duration, velocity, and mute
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("add_notes_to_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
            "notes": notes
        })
        return f"Added {len(notes)} notes to clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error adding notes to clip: {str(e)}")
        return f"Error adding notes to clip: {str(e)}"

@mcp.tool()
def set_clip_name(ctx: Context, track_index: int, clip_index: int, name: str) -> str:
    """
    Set the name of a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - name: The new name for the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_name", {
            "track_index": track_index,
            "clip_index": clip_index,
            "name": name
        })
        return f"Renamed clip at track {track_index}, slot {clip_index} to '{name}'"
    except Exception as e:
        logger.error(f"Error setting clip name: {str(e)}")
        return f"Error setting clip name: {str(e)}"

@mcp.tool()
def set_tempo(ctx: Context, tempo: float) -> str:
    """
    Set the tempo of the Ableton session.
    
    Parameters:
    - tempo: The new tempo in BPM
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_tempo", {"tempo": tempo})
        return f"Set tempo to {tempo} BPM"
    except Exception as e:
        logger.error(f"Error setting tempo: {str(e)}")
        return f"Error setting tempo: {str(e)}"


@mcp.tool()
def load_instrument_or_effect(ctx: Context, track_index: int, uri: str) -> str:
    """
    Load an instrument or effect onto a track using its URI.
    
    Parameters:
    - track_index: The index of the track to load the instrument on
    - uri: The URI of the instrument or effect to load (e.g., 'query:Synths#Instrument%20Rack:Bass:FileId_5116')
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": uri
        })
        
        # Check if the instrument was loaded successfully
        if result.get("loaded", False):
            new_devices = result.get("new_devices", [])
            if new_devices:
                return f"Loaded instrument with URI '{uri}' on track {track_index}. New devices: {', '.join(new_devices)}"
            else:
                devices = result.get("devices_after", [])
                return f"Loaded instrument with URI '{uri}' on track {track_index}. Devices on track: {', '.join(devices)}"
        else:
            return f"Failed to load instrument with URI '{uri}'"
    except Exception as e:
        logger.error(f"Error loading instrument by URI: {str(e)}")
        return f"Error loading instrument by URI: {str(e)}"

@mcp.tool()
def fire_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Start playing a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("fire_clip", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return f"Started playing clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error firing clip: {str(e)}")
        return f"Error firing clip: {str(e)}"

@mcp.tool()
def stop_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Stop playing a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("stop_clip", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return f"Stopped clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error stopping clip: {str(e)}")
        return f"Error stopping clip: {str(e)}"

@mcp.tool()
def start_playback(ctx: Context) -> str:
    """Start playing the Ableton session."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("start_playback")
        return "Started playback"
    except Exception as e:
        logger.error(f"Error starting playback: {str(e)}")
        return f"Error starting playback: {str(e)}"

@mcp.tool()
def stop_playback(ctx: Context) -> str:
    """Stop playing the Ableton session."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("stop_playback")
        return "Stopped playback"
    except Exception as e:
        logger.error(f"Error stopping playback: {str(e)}")
        return f"Error stopping playback: {str(e)}"


@mcp.tool()
def stop_all_clips(ctx: Context) -> str:
    """Stop all Session clips and report the resulting playback state."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("stop_all_clips")
        if _compact_response_enabled():
            return _json_response(_compact_stop_all_clips_result(result))
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error stopping all clips: {str(e)}")
        return f"Error stopping all clips: {str(e)}"


@mcp.tool()
def back_to_arrangement(ctx: Context) -> str:
    """Return playback to Arrangement mode and report whether that was verified."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("back_to_arrangement")
        if _compact_response_enabled():
            return _json_response(_compact_back_to_arrangement_result(result))
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error restoring Arrangement playback: {str(e)}")
        return f"Error restoring Arrangement playback: {str(e)}"


@mcp.tool()
def verify_arrangement_export_ready(ctx: Context) -> str:
    """Confirm that the set is safe to export from Arrangement playback."""
    try:
        ableton = get_ableton_connection()
        result = _verify_arrangement_export_ready_data(ableton)
        if _compact_response_enabled():
            result = {
                "ready": result.get("ready"),
                "issues": result.get("issues", []),
                "verification_level": result.get("verification_level"),
                "recommended_action": result.get("recommended_action"),
            }
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error verifying Arrangement export readiness: {str(e)}")
        return f"Error verifying Arrangement export readiness: {str(e)}"

@mcp.tool()
def get_browser_tree(ctx: Context, category_type: str = "all") -> str:
    """
    Get a hierarchical tree of browser categories from Ableton.
    
    Parameters:
    - category_type: Type of categories to get ('all', 'instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects')
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_browser_tree", {
            "category_type": category_type
        })
        
        # Check if we got any categories
        if "available_categories" in result and len(result.get("categories", [])) == 0:
            available_cats = result.get("available_categories", [])
            return (f"No categories found for '{category_type}'. "
                   f"Available browser categories: {', '.join(available_cats)}")
        
        # Format the tree in a more readable way
        total_folders = result.get("total_folders", 0)
        formatted_output = f"Browser tree for '{category_type}' (showing {total_folders} folders):\n\n"
        
        def format_tree(item, indent=0):
            output = ""
            if item:
                prefix = "  " * indent
                name = item.get("name", "Unknown")
                path = item.get("path", "")
                has_more = item.get("has_more", False)
                
                # Add this item
                output += f"{prefix}• {name}"
                if path:
                    output += f" (path: {path})"
                if has_more:
                    output += " [...]"
                output += "\n"
                
                # Add children
                for child in item.get("children", []):
                    output += format_tree(child, indent + 1)
            return output
        
        # Format each category
        for category in result.get("categories", []):
            formatted_output += format_tree(category)
            formatted_output += "\n"
        
        return formatted_output
    except Exception as e:
        error_msg = str(e)
        if "Browser is not available" in error_msg:
            logger.error(f"Browser is not available in Ableton: {error_msg}")
            return f"Error: The Ableton browser is not available. Make sure Ableton Live is fully loaded and try again."
        elif "Could not access Live application" in error_msg:
            logger.error(f"Could not access Live application: {error_msg}")
            return f"Error: Could not access the Ableton Live application. Make sure Ableton Live is running and the Remote Script is loaded."
        else:
            logger.error(f"Error getting browser tree: {error_msg}")
            return f"Error getting browser tree: {error_msg}"

@mcp.tool()
def get_browser_items_at_path(ctx: Context, path: str) -> str:
    """
    Get browser items at a specific path in Ableton's browser.
    
    Parameters:
    - path: Path in the format "category/folder/subfolder"
            where category is one of the available browser categories in Ableton
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_browser_items_at_path", {
            "path": path
        })
        
        # Check if there was an error with available categories
        if "error" in result and "available_categories" in result:
            error = result.get("error", "")
            available_cats = result.get("available_categories", [])
            return (f"Error: {error}\n"
                   f"Available browser categories: {', '.join(available_cats)}")

        if _compact_response_enabled():
            return _json_response(_compact_browser_items_payload(result))
        return _json_response(result)
    except Exception as e:
        error_msg = str(e)
        if "Browser is not available" in error_msg:
            logger.error(f"Browser is not available in Ableton: {error_msg}")
            return f"Error: The Ableton browser is not available. Make sure Ableton Live is fully loaded and try again."
        elif "Could not access Live application" in error_msg:
            logger.error(f"Could not access Live application: {error_msg}")
            return f"Error: Could not access the Ableton Live application. Make sure Ableton Live is running and the Remote Script is loaded."
        elif "Unknown or unavailable category" in error_msg:
            logger.error(f"Invalid browser category: {error_msg}")
            return f"Error: {error_msg}. Please check the available categories using get_browser_tree."
        elif "Path part" in error_msg and "not found" in error_msg:
            logger.error(f"Path not found: {error_msg}")
            return f"Error: {error_msg}. Please check the path and try again."
        else:
            logger.error(f"Error getting browser items at path: {error_msg}")
            return f"Error getting browser items at path: {error_msg}"

@mcp.tool()
def load_drum_kit(ctx: Context, track_index: int, rack_uri: str, kit_path: str) -> str:
    """
    Load a drum rack and then load a specific drum kit into it.
    
    Parameters:
    - track_index: The index of the track to load on
    - rack_uri: The URI of the drum rack to load (e.g., 'Drums/Drum Rack')
    - kit_path: Path to the drum kit inside the browser (e.g., 'drums/acoustic/kit1')
    """
    try:
        ableton = get_ableton_connection()
        
        # Step 1: Load the drum rack
        result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": rack_uri
        })
        
        if not result.get("loaded", False):
            return f"Failed to load drum rack with URI '{rack_uri}'"
        
        # Step 2: Get the drum kit items at the specified path
        kit_result = ableton.send_command("get_browser_items_at_path", {
            "path": kit_path
        })
        
        if "error" in kit_result:
            return f"Loaded drum rack but failed to find drum kit: {kit_result.get('error')}"
        
        # Step 3: Find a loadable drum kit
        kit_items = kit_result.get("items", [])
        loadable_kits = [item for item in kit_items if item.get("is_loadable", False)]
        
        if not loadable_kits:
            return f"Loaded drum rack but no loadable drum kits found at '{kit_path}'"
        
        # Step 4: Load the first loadable kit
        kit_uri = loadable_kits[0].get("uri")
        load_result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": kit_uri
        })
        
        return f"Loaded drum rack and kit '{loadable_kits[0].get('name')}' on track {track_index}"
    except Exception as e:
        logger.error(f"Error loading drum kit: {str(e)}")
        return f"Error loading drum kit: {str(e)}"


@mcp.tool()
def analyze_audio_file(ctx: Context, file_path: str) -> str:
    """
    Analyze a rendered audio file for loudness and peak metrics.

    Parameters:
    - file_path: Absolute path to a rendered audio file
    """
    try:
        result = _analyze_audio_file_data(file_path)
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error analyzing audio file: {str(e)}")
        return f"Error analyzing audio file: {str(e)}"

# Main execution
def main():
    """Run the MCP server"""
    mcp.run()

if __name__ == "__main__":
    main()

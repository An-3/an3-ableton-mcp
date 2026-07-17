# ableton_mcp_server.py
from mcp.server.fastmcp import FastMCP, Context
import math
import os
import shutil
import socket
import json
import logging
import subprocess
import tempfile
import time
from dataclasses import dataclass
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Dict, Any, List, Optional, Union

from MCP_Server import install_remote_script, macos_export

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
    "get_track_info": "Get detailed information about one track, return, or the master bus.",
    "get_track_devices": "Get lightweight device metadata for one track, return, or the master bus.",
    "get_track_routing": "Get the current routing for one track-like bus.",
    "get_track_input_routing": "Get the current input routing for a regular track.",
    "set_track_input_routing": "Set a track input routing target.",
    "get_track_monitor_state": "Get the current monitoring state for a regular track.",
    "set_track_monitor_state": "Set the monitoring state for a regular track.",
    "get_transport_state": "Get transport state and arrangement export readiness.",
    "list_playing_clips": "List the session clips that are currently active.",
    "list_tracks": "List tracks with stable metadata.",
    "find_track_by_name": "Find a track by exact name.",
    "find_reference_tracks": "Find tracks whose names look like references.",
    "get_master_meter": "Get the current master output meter values.",
    "get_track_meter": "Get the current output meter values for a track-like bus.",
    "sample_track_meter": "Sample a track, return, or master meter and report peak values.",
    "sample_master_meter": "Sample the master meter and report peak values.",
    "create_midi_track": "Create a MIDI track.",
    "create_audio_track": "Create an audio track.",
    "ensure_premaster_track": "Create or reuse a premaster track.",
    "set_track_name": "Rename a track.",
    "set_track_volume": "Set a track volume value.",
    "set_track_panning": "Set a track pan value.",
    "set_track_output_routing": "Set a track output routing target.",
    "create_premaster_routing": "Route tracks through a premaster track when the bus can be verified safely.",
    "get_device_parameters": "List parameters for a device on a track.",
    "set_device_parameter": "Set a device parameter value.",
    "find_device_by_name": "Find devices on a track-like bus by name.",
    "delete_device": "Delete a device from a track-like bus.",
    "load_audio_clip": "Load an audio file into a clip slot.",
    "append_browser_device": "Append a browser item to a track-like device chain.",
    "append_mastering_chain": "Append a stock mastering chain to a track-like bus.",
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
    "resolve_mastering_source": "Resolve the permitted mastering source and report source provenance.",
    "get_arrangement_summary": "Summarize arrangement clip extents and song length.",
    "diagnose_remote_script_install": "Compare the repo Remote Script, the installed Ableton script, and the live socket capabilities.",
    "export_audio_macos": "Render the opened Ableton set through the macOS export dialog and validate the file.",
    "master_and_export_opened_set": "Apply a stock mastering chain to the opened set, export it on macOS, and validate the result.",
    "get_browser_tree": "Browse the top-level Ableton browser tree.",
    "get_browser_items_at_path": "List browser items at a specific path.",
    "load_drum_kit": "Load a drum rack and a drum kit.",
    "analyze_audio_file": "Analyze a rendered audio file for loudness and peaks.",
    "validate_audio_export": "Wait for a rendered audio file, validate that it contains audible program material, and preview the loudest section.",
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

    def receive_full_response(self, sock, buffer_size=8192, timeout_seconds=15.0):
        """Receive the complete response, potentially in multiple chunks"""
        chunks = []
        sock.settimeout(timeout_seconds)
        
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

    def send_command(
        self,
        command_type: str,
        params: Dict[str, Any] = None,
        timeout_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
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
            timeout = timeout_seconds if timeout_seconds is not None else (15.0 if is_modifying_command else 10.0)
            self.sock.settimeout(timeout)
            
            # Receive the response
            response_data = self.receive_full_response(self.sock, timeout_seconds=timeout)
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
PREMASTER_ROUTING_REQUIRED_TOOLS = (
    "get_track_input_routing",
    "set_track_input_routing",
    "get_track_monitor_state",
    "set_track_monitor_state",
)
REMOTE_SCRIPT_INFO_COMMAND = "get_remote_script_info"
REMOTE_SCRIPT_MASTERING_REQUIRED_CAPABILITIES = (
    "get_arrangement_summary",
    "get_track_devices",
    "track_scope_master",
    "find_device_by_name",
    "delete_device",
    "get_track_meter",
)
REMOTE_SCRIPT_PREMASTER_REQUIRED_CAPABILITIES = (
    "get_track_input_routing",
    "set_track_input_routing",
    "get_track_monitor_state",
    "set_track_monitor_state",
)
EXPORT_AUDIO_EXTENSIONS = (".wav", ".aif", ".aiff", ".flac", ".mp3")
DEFAULT_EXPORT_SILENCE_THRESHOLD_DBFS = -80.0
DEFAULT_FIRST_AUDIBLE_THRESHOLD_DBFS = -60.0
DEFAULT_FIRST_AUDIBLE_WINDOW_SECONDS = 1.0
DEFAULT_EXPORT_WINDOW_COUNT = 10
DEFAULT_EXPORT_PREVIEW_SECONDS = 5.0
DEFAULT_EXPORT_WAIT_TIMEOUT_SECONDS = 60.0
DEFAULT_EXPORT_WAIT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_EXPORT_WAIT_STABLE_POLLS = 2
DEFAULT_ARRANGEMENT_SUMMARY_TIMEOUT_SECONDS = 5.0
DEFAULT_DURATION_IMPLAUSIBLE_RATIO = 0.5
DEFAULT_EXPORT_SECTION_SECONDS = 30.0
DEFAULT_EXPORT_MAX_FIRST_AUDIBLE_SECONDS = None
DEFAULT_EXPORT_MAX_FIRST_AUDIBLE_DELTA_SECONDS = 5.0
DEFAULT_EXPORT_REFERENCE_DROP_THRESHOLD_DB = 8.0
DEFAULT_MASTERING_TARGET_LUFS_I = -14.0
DEFAULT_MASTERING_TRUE_PEAK_TARGET_DBTP = -1.0
DEFAULT_MASTERING_GAIN_TOLERANCE_DB = 0.75
DEFAULT_MASTERING_MAX_GAIN_ADJUST_DB = 3.0
DEFAULT_EXPORT_CONTENT_ACTIVE_THRESHOLD_DBFS = -55.0
EXPORT_CONTENT_BANDS = (
    ("sub", 20.0, 120.0),
    ("lowmid", 120.0, 500.0),
    ("mid", 500.0, 5000.0),
    ("high", 5000.0, 16000.0),
)

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


def _is_unknown_command_error(exc: Exception, command_name: str) -> bool:
    message = str(exc)
    return "Unknown command" in message and command_name in message


def _is_timeout_error(exc: Exception) -> bool:
    return "Timeout waiting for Ableton response" in str(exc)


def _local_remote_script_install_data() -> Dict[str, Any]:
    repo_script_path = install_remote_script.get_repo_remote_script_source_path()
    repo_sha256 = None
    if repo_script_path.is_file():
        repo_sha256 = install_remote_script.sha256_file(repo_script_path)

    running_live_version = install_remote_script.detect_running_live_version_macos()
    expected_install_path: Optional[Path] = None
    if running_live_version:
        expected_install_path = install_remote_script.expected_macos_remote_script_target(running_live_version)

    discovered_install_paths = [
        str(path)
        for path in install_remote_script.discover_macos_remote_script_targets()
    ]
    installed_sha256 = None
    if expected_install_path is not None and expected_install_path.is_file():
        installed_sha256 = install_remote_script.sha256_file(expected_install_path)

    matches_repo = None
    if repo_sha256 is not None and installed_sha256 is not None:
        matches_repo = repo_sha256 == installed_sha256

    return {
        "running_live_version": running_live_version,
        "repo_script_path": str(repo_script_path),
        "installed_script_path": str(expected_install_path) if expected_install_path is not None else None,
        "repo_sha256": repo_sha256,
        "installed_sha256": installed_sha256,
        "matches_repo": matches_repo,
        "discovered_install_paths": discovered_install_paths,
    }


def _remote_script_recommended_action(
    diagnostic: Dict[str, Any],
    missing_capabilities: Optional[List[str]] = None,
) -> str:
    installed_path = diagnostic.get("installed_script_path")
    matches_repo = diagnostic.get("matches_repo")
    missing = missing_capabilities or []
    missing_text = ""
    if missing:
        missing_text = " Missing capabilities: {0}.".format(", ".join(missing))
    if installed_path and matches_repo:
        return (
            "The installed AbletonMCP script at {0} already matches the repo. "
            "Remove and re-add the AbletonMCP control surface in Live or restart Ableton Live so the running socket reloads it.{1}"
        ).format(installed_path, missing_text)
    if installed_path:
        return (
            "Sync the repo Remote Script into {0} with `ableton-mcp-install-remote-script`, "
            "then remove and re-add the AbletonMCP control surface in Live or restart Ableton Live.{1}"
        ).format(installed_path, missing_text)
    return (
        "Run `ableton-mcp-install-remote-script` to sync every discovered AbletonMCP install, "
        "then remove and re-add the AbletonMCP control surface in Live or restart Ableton Live.{0}"
    ).format(missing_text)


def _diagnose_remote_script_install_data(
    ableton: Optional[AbletonConnection] = None,
    remote_script_info_override: Optional[Dict[str, Any]] = None,
    remote_script_info_error: Optional[str] = None,
) -> Dict[str, Any]:
    diagnostic = _local_remote_script_install_data()
    remote_script_info = remote_script_info_override
    error_message = remote_script_info_error

    if remote_script_info is None and error_message is None and ableton is not None:
        try:
            remote_script_info = ableton.send_command(REMOTE_SCRIPT_INFO_COMMAND)
        except Exception as exc:
            error_message = str(exc)

    if remote_script_info is not None:
        connection_state = "available"
    elif error_message and _is_unknown_command_error(Exception(error_message), REMOTE_SCRIPT_INFO_COMMAND):
        connection_state = "legacy_remote_script"
    elif ableton is None:
        connection_state = "not_probed"
    else:
        connection_state = "probe_failed"

    diagnostic.update({
        "remote_script_info": remote_script_info,
        "remote_script_connection_state": connection_state,
        "remote_script_info_error": error_message,
        "recommended_action": _remote_script_recommended_action(diagnostic),
    })
    return diagnostic


def _probe_remote_script_capabilities_data(
    ableton: AbletonConnection,
    required_capabilities: Optional[List[str]] = None,
    verify_master_scope: bool = False,
) -> Dict[str, Any]:
    required = sorted(set(required_capabilities or []))
    try:
        remote_script_info = ableton.send_command(REMOTE_SCRIPT_INFO_COMMAND)
        info_error = None
        legacy_remote_script = False
    except Exception as exc:
        remote_script_info = None
        info_error = str(exc)
        legacy_remote_script = _is_unknown_command_error(exc, REMOTE_SCRIPT_INFO_COMMAND)

    diagnostic = _diagnose_remote_script_install_data(
        ableton=None,
        remote_script_info_override=remote_script_info,
        remote_script_info_error=info_error,
    )

    behavior_checks: List[Dict[str, Any]] = []
    if remote_script_info is None:
        return {
            "ok": False,
            "failure_code": "stale_remote_script",
            "legacy_remote_script": legacy_remote_script,
            "required_capabilities": required,
            "missing_capabilities": required,
            "remote_script_info": None,
            "behavior_checks": behavior_checks,
            "diagnostic": diagnostic,
        }

    available_capabilities = sorted(set(remote_script_info.get("capabilities", []) or []))
    missing_capabilities = [name for name in required if name not in available_capabilities]

    if verify_master_scope:
        try:
            master_track = _get_track_devices_data(ableton, 0, track_scope="master")
            master_ok = master_track.get("track_scope") == "master"
            behavior_checks.append({
                "check": "master_track_scope_roundtrip",
                "ok": master_ok,
                "result_track_scope": master_track.get("track_scope"),
                "result_track_name": master_track.get("name"),
            })
            if not master_ok and "track_scope_master" not in missing_capabilities:
                missing_capabilities.append("track_scope_master")
        except Exception as exc:
            behavior_checks.append({
                "check": "master_track_scope_roundtrip",
                "ok": False,
                "error": str(exc),
            })
            if "track_scope_master" not in missing_capabilities:
                missing_capabilities.append("track_scope_master")

    diagnostic["remote_script_info"] = remote_script_info
    diagnostic["recommended_action"] = _remote_script_recommended_action(diagnostic, missing_capabilities)

    return {
        "ok": not missing_capabilities,
        "failure_code": None if not missing_capabilities else "stale_remote_script",
        "legacy_remote_script": legacy_remote_script,
        "required_capabilities": required,
        "missing_capabilities": sorted(set(missing_capabilities)),
        "remote_script_info": remote_script_info,
        "behavior_checks": behavior_checks,
        "diagnostic": diagnostic,
    }


def _current_routing_payload(routing: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    routing = routing or {}
    return {
        "current_input_routing_type": routing.get("current_input_routing_type"),
        "current_input_routing_channel": routing.get("current_input_routing_channel"),
        "current_output_routing_type": routing.get("current_output_routing_type"),
        "current_output_routing_channel": routing.get("current_output_routing_channel"),
    }


def _compact_routing_payload(track_routing: Dict[str, Any]) -> Dict[str, Any]:
    routing = track_routing.get("routing", {}) or {}
    return {
        "track_scope": track_routing.get("track_scope", "track"),
        "index": track_routing.get("index"),
        "name": track_routing.get("name"),
        "routing": {
            **_current_routing_payload(routing),
            "available_input_routing_type_count": len(routing.get("available_input_routing_types", []) or []),
            "available_input_routing_channel_count": len(routing.get("available_input_routing_channels", []) or []),
            "available_output_routing_type_count": len(routing.get("available_output_routing_types", []) or []),
            "available_output_routing_channel_count": len(routing.get("available_output_routing_channels", []) or []),
        },
    }


def _compact_track_summary(track: Dict[str, Any]) -> Dict[str, Any]:
    playback_state = track.get("playback_state", {}) or {}
    clip_slots = track.get("clip_slots", []) or []
    devices = track.get("devices", []) or []
    return {
        "track_scope": track.get("track_scope", "track"),
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
        "track_scope": result.get("track_scope", "track"),
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
    compact = {
        "state": result.get("state"),
        "failure_code": result.get("failure_code"),
        "track_scope": result.get("track_scope", "track"),
        "track_index": result.get("track_index"),
        "preset_name": result.get("preset_name"),
        "loaded_count": loaded_count,
        "appended_device_names": appended_device_names,
        "final_device_count": len(result.get("final_devices", []) or []),
    }
    if result.get("reason"):
        compact["reason"] = result.get("reason")
    if result.get("missing_capabilities"):
        compact["missing_capabilities"] = result.get("missing_capabilities")
    return compact


def _compact_validate_audio_export_result(result: Dict[str, Any]) -> Dict[str, Any]:
    export_validation = result.get("export_validation", {}) or {}
    content_presence = export_validation.get("content_presence", {}) or {}
    preview = result.get("preview", {}) or {}
    compact = {
        "state": result.get("state"),
        "requested_file_path": result.get("requested_file_path"),
        "resolved_file_path": result.get("resolved_file_path"),
        "path_normalized": result.get("path_normalized"),
        "failed_checks": export_validation.get("failed_checks", []),
        "duration_seconds": export_validation.get("duration_seconds"),
        "sample_peak_dbfs": export_validation.get("sample_peak_dbfs"),
        "true_peak_dbtp": export_validation.get("true_peak_dbtp"),
        "lufs_i": export_validation.get("lufs_i"),
        "window_peak_dbfs": export_validation.get("window_peak_dbfs", []),
        "first_audible_seconds": content_presence.get("first_audible_seconds"),
        "flagged_section_count": len(content_presence.get("flagged_sections", []) or []),
        "preview_status": preview.get("status"),
    }
    if result.get("reason"):
        compact["reason"] = result.get("reason")
    return compact


def _compact_resolve_mastering_source_result(result: Dict[str, Any]) -> Dict[str, Any]:
    transport_state = result.get("transport_state", {}) or {}
    compact = {
        "state": result.get("state"),
        "source_of_truth": result.get("source_of_truth"),
        "actual_source_used": result.get("actual_source_used"),
        "source_timestamp": result.get("source_timestamp"),
        "fallback_used": result.get("fallback_used"),
        "live_session_available": result.get("live_session_available"),
        "arrangement_export_ready": transport_state.get("arrangement_export_ready"),
    }
    if result.get("reason"):
        compact["reason"] = result.get("reason")
    return compact


def _compact_export_audio_macos_result(result: Dict[str, Any]) -> Dict[str, Any]:
    export_validation = result.get("export_validation", {}) or {}
    ui_automation = result.get("ui_automation", {}) or {}
    preflight = result.get("preflight", {}) or {}
    compact = {
        "state": result.get("state"),
        "requested_file_path": result.get("requested_file_path"),
        "resolved_file_path": result.get("resolved_file_path"),
        "failure_code": result.get("failure_code"),
        "preflight_ok": preflight.get("ok"),
        "preflight_failure_code": preflight.get("failure_code"),
        "ui_ok": ui_automation.get("ok"),
        "ui_failure_code": ui_automation.get("failure_code"),
        "failed_checks": export_validation.get("failed_checks", []),
    }
    if result.get("reason"):
        compact["reason"] = result.get("reason")
    return compact


def _compact_master_and_export_result(result: Dict[str, Any]) -> Dict[str, Any]:
    export_validation = result.get("export_validation", {}) or {}
    source_provenance = result.get("source_provenance", {}) or {}
    mastering = result.get("mastering", {}) or {}
    arrangement_summary = result.get("arrangement_summary", {}) or {}
    compact = {
        "state": result.get("state"),
        "actual_source_used": source_provenance.get("actual_source_used"),
        "preset_name": mastering.get("preset_name"),
        "requested_file_path": result.get("requested_file_path"),
        "resolved_file_path": result.get("resolved_file_path"),
        "failure_code": result.get("failure_code"),
        "measurement_mode": result.get("measurement_mode"),
        "detail_level": arrangement_summary.get("detail_level"),
        "failed_checks": export_validation.get("failed_checks", []),
        "lufs_i": export_validation.get("lufs_i"),
        "true_peak_dbtp": export_validation.get("true_peak_dbtp"),
    }
    if result.get("reason"):
        compact["reason"] = result.get("reason")
    if result.get("remote_script_probe", {}).get("missing_capabilities"):
        compact["missing_capabilities"] = result["remote_script_probe"]["missing_capabilities"]
    return compact


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
            "track_scope": track.get("track_scope", "track"),
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
    try:
        result = ableton.send_command("list_tracks_summary")
        return result or []
    except Exception as exc:
        logger.warning("Falling back from list_tracks_summary to per-track summaries: %s", exc)
        session = ableton.send_command("get_session_info")
        track_count = int(session.get("track_count", 0))
        return [
            ableton.send_command("get_track_summary", {"track_index": track_index})
            for track_index in range(track_count)
        ]


def _normalize_track_scope(track_scope: Optional[str]) -> str:
    normalized = (track_scope or "track").strip().lower().replace("_", "-")
    aliases = {
        "track": "track",
        "tracks": "track",
        "return": "return",
        "returns": "return",
        "return-track": "return",
        "master": "master",
        "master-track": "master",
    }
    if normalized not in aliases:
        raise ValueError("track_scope must be 'track', 'return', or 'master'")
    return aliases[normalized]


def _track_scope_params(track_index: int, track_scope: str = "track") -> Dict[str, Any]:
    return {
        "track_index": track_index,
        "track_scope": _normalize_track_scope(track_scope),
    }


def _get_track_devices_data(
    ableton: AbletonConnection,
    track_index: int,
    track_scope: str = "track",
) -> Dict[str, Any]:
    return ableton.send_command("get_track_devices", _track_scope_params(track_index, track_scope))


def _get_arrangement_summary_data(
    ableton: AbletonConnection,
    detail_level: str = "basic",
    timeout_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    normalized_detail_level = (detail_level or "basic").strip().lower()
    try:
        result = ableton.send_command(
            "get_arrangement_summary",
            {"detail_level": normalized_detail_level},
            timeout_seconds=timeout_seconds,
        )
        if "detail_level" not in result:
            result["detail_level"] = normalized_detail_level
        result["state"] = "ok"
        result["failure_code"] = None
        result["reason"] = None
        return result
    except Exception as exc:
        failure_code = "command_timeout" if _is_timeout_error(exc) else "arrangement_summary_failed"
        return {
            "state": "failed",
            "detail_level": normalized_detail_level,
            "failure_code": failure_code,
            "reason": str(exc),
            "tracks": [],
        }


def _get_track_data(
    ableton: AbletonConnection,
    track_index: int,
    summary: bool = False,
    track_scope: str = "track",
) -> Dict[str, Any]:
    normalized_scope = _normalize_track_scope(track_scope)
    command_type = "get_track_summary" if summary and normalized_scope == "track" else "get_track_info"
    params = {"track_index": track_index}
    if command_type == "get_track_info":
        params["track_scope"] = normalized_scope
    return ableton.send_command(command_type, params)


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


def _ensure_arrangement_export_ready_data(ableton: AbletonConnection) -> Dict[str, Any]:
    readiness = _verify_arrangement_export_ready_data(ableton)
    if readiness.get("ready"):
        readiness["restore_attempted"] = False
        readiness["restored"] = False
        return readiness

    restore_attempted = False
    restored = False
    if any(issue in readiness.get("issues", []) for issue in ("active_session_clips", "session_override_active")):
        restore_attempted = True
        ableton.send_command("back_to_arrangement")
        readiness = _verify_arrangement_export_ready_data(ableton)
        restored = bool(readiness.get("ready"))

    readiness["restore_attempted"] = restore_attempted
    readiness["restored"] = restored
    return readiness


def _normalize_mastering_source(requested_source: str) -> str:
    normalized = (requested_source or "opened-live-set").strip().lower().replace("_", "-")
    aliases = {
        "opened-live-set": "opened-live-set",
        "opened-set": "opened-live-set",
        "opened-track": "opened-live-set",
        "live": "opened-live-set",
        "file": "file",
        "explicit-file": "file",
    }
    if normalized not in aliases:
        raise ValueError("requested_source must be 'opened-live-set' or 'file'")
    return aliases[normalized]


def _format_timestamp(mtime: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime))


def _stat_audio_source(file_path: str) -> Dict[str, Any]:
    abs_path = os.path.abspath(os.path.expanduser(file_path))
    stat_result = os.stat(abs_path)
    return {
        "path": abs_path,
        "size_bytes": int(stat_result.st_size),
        "mtime": float(stat_result.st_mtime),
        "timestamp": _format_timestamp(stat_result.st_mtime),
    }


def _resolve_mastering_source_data(
    requested_source: str = "opened-live-set",
    file_path: Optional[str] = None,
    allow_file_fallback: bool = False,
) -> Dict[str, Any]:
    source_of_truth = _normalize_mastering_source(requested_source)
    result: Dict[str, Any] = {
        "state": "export-blocked",
        "source_of_truth": source_of_truth,
        "actual_source_used": None,
        "actual_source_type": None,
        "source_timestamp": None,
        "source_timestamp_available": False,
        "fallback_used": False,
        "live_session_available": False,
        "reason": None,
        "transport_state": None,
        "session_info": None,
    }

    file_candidate = None
    file_candidate_error = None
    if file_path:
        try:
            file_candidate = _stat_audio_source(file_path)
        except OSError as exc:
            file_candidate_error = str(exc)

    if source_of_truth == "file":
        if not file_path:
            result["reason"] = "File-based mastering requires an explicit file_path."
            return result
        if file_candidate is None:
            result["reason"] = "Explicit file source is unavailable: {0}".format(file_candidate_error or file_path)
            return result
        result.update({
            "state": "source-ready",
            "actual_source_used": file_candidate["path"],
            "actual_source_type": "file",
            "source_timestamp": file_candidate["timestamp"],
            "source_timestamp_available": True,
        })
        return result

    live_error = None
    try:
        ableton = get_ableton_connection()
        session_info = ableton.send_command("get_session_info")
        transport_state = _get_transport_state_data(ableton)
        result.update({
            "live_session_available": True,
            "session_info": session_info,
            "transport_state": transport_state,
            "state": "source-ready",
            "actual_source_used": "opened-live-set",
            "actual_source_type": "opened-live-set",
        })
        if file_candidate is not None:
            result["ignored_file_candidate_path"] = file_candidate["path"]
        return result
    except Exception as exc:
        live_error = str(exc)
        result["reason"] = "Opened Live set is unavailable: {0}".format(live_error)

    if file_candidate is not None and allow_file_fallback:
        result.update({
            "state": "source-ready",
            "actual_source_used": file_candidate["path"],
            "actual_source_type": "file",
            "source_timestamp": file_candidate["timestamp"],
            "source_timestamp_available": True,
            "fallback_used": True,
            "reason": None,
        })
        return result

    if file_candidate is not None:
        result["blocked_fallback_file_path"] = file_candidate["path"]
    if file_candidate is None and file_path:
        result["blocked_fallback_file_error"] = file_candidate_error
    return result


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
    item_uri: str,
    track_scope: str = "track",
) -> Dict[str, Any]:
    params = _track_scope_params(track_index, track_scope)
    before = _get_track_devices_data(ableton, track_index, track_scope=track_scope)
    before_devices = before.get("devices", []) or []
    before_names = [device.get("name", "") for device in before_devices]

    load_params = dict(params)
    load_params["item_uri"] = item_uri
    load_result = ableton.send_command("load_browser_item", load_params)

    after = _get_track_devices_data(ableton, track_index, track_scope=track_scope)
    after_devices = after.get("devices", []) or []
    after_names = [device.get("name", "") for device in after_devices]
    appended_devices = after_devices[len(before_devices):] if len(after_devices) >= len(before_devices) else []
    appended = [device.get("name", "") for device in appended_devices]

    return {
        "track_scope": params["track_scope"],
        "track_index": track_index,
        "item_uri": item_uri,
        "loaded": load_result.get("loaded", False),
        "item_name": load_result.get("item_name", ""),
        "devices_before": before_names,
        "devices_after": after_names,
        "appended_device_indexes": [device.get("index") for device in appended_devices],
        "appended_devices": appended,
    }


def _append_mastering_chain_data(
    ableton: AbletonConnection,
    track_index: int,
    preset_name: str,
    track_scope: str = "track",
) -> Dict[str, Any]:
    normalized_scope = _normalize_track_scope(track_scope)
    if normalized_scope == "master":
        probe = _probe_remote_script_capabilities_data(
            ableton,
            required_capabilities=list(REMOTE_SCRIPT_MASTERING_REQUIRED_CAPABILITIES),
            verify_master_scope=True,
        )
        if not probe.get("ok"):
            return {
                "state": "mastering-blocked",
                "failure_code": "stale_remote_script",
                "reason": probe["diagnostic"]["recommended_action"],
                "track_scope": normalized_scope,
                "track_index": track_index,
                "preset_name": preset_name.strip().upper(),
                "required_capabilities": probe.get("required_capabilities", []),
                "missing_capabilities": probe.get("missing_capabilities", []),
                "remote_script_probe": probe,
                "remote_script_diagnostic": probe.get("diagnostic"),
                "steps": [],
                "final_devices": [],
            }

    normalized_preset = preset_name.strip().upper()
    chain = MASTERING_PRESET_DEVICE_URIS.get(normalized_preset)
    if chain is None:
        available = ", ".join(sorted(MASTERING_PRESET_DEVICE_URIS.keys()))
        raise ValueError("Unknown preset '{0}'. Available presets: {1}".format(preset_name, available))

    appended = []
    for item_uri in chain:
        appended.append(
            _append_browser_device_data(ableton, track_index, item_uri, track_scope=track_scope)
        )

    final_track = _get_track_devices_data(ableton, track_index, track_scope=track_scope)
    return {
        "state": "mastering-ready",
        "failure_code": None,
        "reason": None,
        "track_scope": normalized_scope,
        "track_index": track_index,
        "preset_name": normalized_preset,
        "steps": appended,
        "final_devices": final_track.get("devices", []),
    }


def _find_parameter_index_by_name(parameters: List[Dict[str, Any]], candidate_names: List[str]) -> Optional[int]:
    wanted = [(name or "").strip().lower() for name in candidate_names if name]
    for parameter in parameters:
        candidate = (parameter.get("name", "") or "").strip().lower()
        if candidate in wanted:
            return parameter.get("index")
    for parameter in parameters:
        candidate = (parameter.get("name", "") or "").strip().lower()
        for wanted_name in wanted:
            if wanted_name and wanted_name in candidate:
                return parameter.get("index")
    return None


def _compute_mastering_gain_adjustment_db(
    analysis: Dict[str, Any],
    target_lufs_i: float = DEFAULT_MASTERING_TARGET_LUFS_I,
    true_peak_target_dbtp: float = DEFAULT_MASTERING_TRUE_PEAK_TARGET_DBTP,
    tolerance_db: float = DEFAULT_MASTERING_GAIN_TOLERANCE_DB,
    max_adjust_db: float = DEFAULT_MASTERING_MAX_GAIN_ADJUST_DB,
) -> float:
    lufs_i = analysis.get("lufs_i")
    true_peak_dbtp = analysis.get("true_peak_dbtp")
    desired_by_lufs = 0.0
    desired_by_peak = 0.0
    if isinstance(lufs_i, (int, float)) and math.isfinite(lufs_i):
        desired_by_lufs = float(target_lufs_i - lufs_i)
    if isinstance(true_peak_dbtp, (int, float)) and math.isfinite(true_peak_dbtp):
        desired_by_peak = float(true_peak_target_dbtp - true_peak_dbtp)

    adjustment = 0.0
    if isinstance(true_peak_dbtp, (int, float)) and math.isfinite(true_peak_dbtp) and true_peak_dbtp > true_peak_target_dbtp + 0.1:
        adjustment = desired_by_peak
    elif desired_by_lufs < -tolerance_db:
        adjustment = desired_by_lufs
    elif (
        desired_by_lufs > tolerance_db and
        isinstance(true_peak_dbtp, (int, float)) and
        math.isfinite(true_peak_dbtp) and
        true_peak_dbtp < true_peak_target_dbtp - 1.0
    ):
        adjustment = min(desired_by_lufs, desired_by_peak if desired_by_peak > 0.0 else desired_by_lufs)

    return max(-max_adjust_db, min(max_adjust_db, adjustment))


def _apply_mastering_gain_correction_data(
    ableton: AbletonConnection,
    mastering: Dict[str, Any],
    analysis: Dict[str, Any],
    track_scope: str = "master",
    track_index: int = 0,
) -> Dict[str, Any]:
    correction = {
        "attempted": False,
        "applied": False,
        "device_name": None,
        "device_index": None,
        "parameter_name": None,
        "parameter_index": None,
        "requested_delta_db": 0.0,
        "applied_value": None,
        "reason": None,
    }

    requested_delta_db = _compute_mastering_gain_adjustment_db(analysis)
    correction["requested_delta_db"] = requested_delta_db
    if abs(requested_delta_db) < 0.1:
        correction["reason"] = "No conservative correction was needed."
        return correction

    steps = mastering.get("steps", []) or []
    utility_step = None
    for step in steps:
        if "Utility" in (step.get("appended_devices", []) or []):
            utility_step = step
            break
    if utility_step is None:
        correction["reason"] = "Utility was not appended in the mastering chain."
        return correction

    device_indexes = [index for index in (utility_step.get("appended_device_indexes", []) or []) if index is not None]
    if not device_indexes:
        correction["reason"] = "Unable to resolve the appended Utility device index."
        return correction

    utility_index = int(device_indexes[0])
    parameters_payload = ableton.send_command(
        "get_device_parameters",
        {
            "track_index": track_index,
            "device_index": utility_index,
            "track_scope": _normalize_track_scope(track_scope),
        },
    )
    parameters = parameters_payload.get("parameters", []) or []
    parameter_index = _find_parameter_index_by_name(parameters, ["Gain"])
    if parameter_index is None:
        correction["reason"] = "Utility gain parameter was not found."
        return correction

    current_parameter = next(
        (parameter for parameter in parameters if parameter.get("index") == parameter_index),
        None,
    )
    if current_parameter is None:
        correction["reason"] = "Utility gain parameter payload was incomplete."
        return correction

    current_value = current_parameter.get("value")
    if not isinstance(current_value, (int, float)):
        correction["reason"] = "Utility gain parameter value was unavailable."
        return correction

    min_value = current_parameter.get("min")
    max_value = current_parameter.get("max")
    target_value = float(current_value) + requested_delta_db
    if isinstance(min_value, (int, float)):
        target_value = max(float(min_value), target_value)
    if isinstance(max_value, (int, float)):
        target_value = min(float(max_value), target_value)

    correction.update({
        "attempted": True,
        "device_name": parameters_payload.get("device_name", "Utility"),
        "device_index": utility_index,
        "parameter_name": current_parameter.get("name"),
        "parameter_index": parameter_index,
    })

    if abs(target_value - float(current_value)) < 0.05:
        correction["reason"] = "Requested correction was below the writable parameter threshold."
        return correction

    set_result = ableton.send_command(
        "set_device_parameter",
        {
            "track_index": track_index,
            "device_index": utility_index,
            "parameter_index": parameter_index,
            "value": target_value,
            "track_scope": _normalize_track_scope(track_scope),
        },
    )
    correction["applied"] = True
    correction["applied_value"] = set_result.get("value", target_value)
    correction["reason"] = None
    return correction


def _expected_duration_from_arrangement_summary(summary: Dict[str, Any]) -> Optional[float]:
    song_length = summary.get("song_length")
    if isinstance(song_length, (int, float)) and song_length > 0:
        return float(song_length)
    last_clip_end_time = summary.get("last_clip_end_time")
    if isinstance(last_clip_end_time, (int, float)) and last_clip_end_time > 0:
        return float(last_clip_end_time)
    return None


def _normalize_export_request_path(output_folder: str, file_name: str) -> str:
    normalized_name = macos_export.normalize_export_file_name(file_name)
    normalized_folder = os.path.abspath(os.path.expanduser(output_folder))
    return os.path.join(normalized_folder, normalized_name)


def _export_audio_macos_data(
    output_folder: str,
    file_name: str,
    render_source: str,
    sample_rate: int,
    bit_depth: int,
    normalize: bool,
    dither: str,
    expected_duration_seconds: Optional[float] = None,
    reference_file_path: Optional[str] = None,
    wait_timeout_seconds: float = DEFAULT_EXPORT_WAIT_TIMEOUT_SECONDS,
    wait_poll_interval_seconds: float = DEFAULT_EXPORT_WAIT_POLL_INTERVAL_SECONDS,
    stable_polls: int = DEFAULT_EXPORT_WAIT_STABLE_POLLS,
    play_preview: bool = True,
) -> Dict[str, Any]:
    os.makedirs(os.path.abspath(os.path.expanduser(output_folder)), exist_ok=True)
    result: Dict[str, Any] = {
        "state": "export-blocked",
        "requested_file_path": _normalize_export_request_path(output_folder, file_name),
        "resolved_file_path": None,
        "failure_code": None,
        "reason": None,
        "preflight": {},
        "ui_automation": {},
        "export_validation": {},
        "preview": {
            "attempted": False,
            "status": "skipped",
        },
    }

    try:
        ui_result = macos_export.run_export_audio_ui(
            output_folder=output_folder,
            file_name=file_name,
            render_source=render_source,
            sample_rate=sample_rate,
            bit_depth=bit_depth,
            normalize=normalize,
            dither=dither,
        )
    except ValueError as exc:
        result["failure_code"] = "export_dialog_unrecognized"
        result["reason"] = str(exc)
        return result

    result["requested_file_path"] = ui_result.get("requested_file_path", result["requested_file_path"])
    result["preflight"] = ui_result.get("preflight", {})
    result["ui_automation"] = ui_result.get("ui_automation", {})
    if ui_result.get("state") != "export-ready":
        result["state"] = "export-blocked"
        result["failure_code"] = (
            result["ui_automation"].get("failure_code")
            or result["preflight"].get("failure_code")
        )
        result["reason"] = ui_result.get("reason")
        return result

    validation = _validate_audio_export_data(
        result["requested_file_path"],
        expected_duration_seconds=expected_duration_seconds,
        reference_file_path=reference_file_path,
        wait_timeout_seconds=wait_timeout_seconds,
        wait_poll_interval_seconds=wait_poll_interval_seconds,
        stable_polls=stable_polls,
        play_preview=play_preview,
    )
    result["resolved_file_path"] = validation.get("resolved_file_path")
    result["export_validation"] = validation.get("export_validation", {})
    result["preview"] = validation.get("preview", result["preview"])

    if validation.get("state") == "export-validated":
        result["state"] = "export-validated"
        return result

    failed_checks = result["export_validation"].get("failed_checks", [])
    result["state"] = "export-failed"
    result["failure_code"] = (
        "render_file_timeout"
        if "file_missing" in failed_checks
        else "post_export_validation_failed"
    )
    result["reason"] = validation.get("reason")
    return result


def _resolve_main_routing_name(routing_options: List[Dict[str, Any]]) -> Optional[str]:
    for candidate in MAIN_ROUTING_CANDIDATES:
        for option in routing_options:
            if option.get("display_name", "") == candidate:
                return candidate
    return routing_options[0].get("display_name") if routing_options else None


def _premaster_routing_safety_data(
    premaster_name: str = "PREMASTER",
    ableton: Optional[AbletonConnection] = None,
) -> Dict[str, Any]:
    missing_tools = [
        tool_name for tool_name in PREMASTER_ROUTING_REQUIRED_TOOLS
        if tool_name not in TOOL_DESCRIPTIONS
    ]
    issues = []
    if any(tool_name in missing_tools for tool_name in ("get_track_input_routing", "set_track_input_routing")):
        issues.append("premaster_input_routing_unavailable")
    if any(tool_name in missing_tools for tool_name in ("get_track_monitor_state", "set_track_monitor_state")):
        issues.append("premaster_monitor_state_unavailable")

    probe_failures = []
    capability_probe = None
    if ableton is not None:
        capability_probe = _probe_remote_script_capabilities_data(
            ableton,
            required_capabilities=list(REMOTE_SCRIPT_PREMASTER_REQUIRED_CAPABILITIES),
        )
        if not capability_probe.get("ok"):
            issues.append("stale_remote_script")

    if ableton is not None and not issues:
        try:
            ableton.send_command("get_track_input_routing", {"track_index": 0})
        except Exception as exc:
            issues.append("premaster_input_routing_probe_failed")
            probe_failures.append("get_track_input_routing: {0}".format(exc))
        try:
            ableton.send_command("get_track_monitor_state", {"track_index": 0})
        except Exception as exc:
            issues.append("premaster_monitor_state_probe_failed")
            probe_failures.append("get_track_monitor_state: {0}".format(exc))

    safe = not issues
    if safe:
        recommended_action = (
            "PREMASTER routing can be verified on this surface. Confirm the bus is carrying signal before export."
        )
        manual_steps: List[str] = []
        state = "export-ready"
        failure_code = None
    else:
        if capability_probe is not None and not capability_probe.get("ok"):
            recommended_action = capability_probe["diagnostic"]["recommended_action"]
            manual_steps = [
                "Run `ableton-mcp-install-remote-script` to sync the installed AbletonMCP script.",
                "Reload the AbletonMCP control surface in Live or restart Ableton Live.",
                "Rerun the premaster routing command after the live socket reports the new capabilities.",
            ]
            state = "export-blocked"
            failure_code = "stale_remote_script"
        else:
            recommended_action = (
                "Do not automate PREMASTER export on this surface. In Ableton, set '{0}' to receive the routed mix, "
                "enable the correct monitoring/input state so the bus reaches Main, confirm '{0}' has audible meter movement "
                "during playback, then rerun export validation."
            ).format(premaster_name)
            manual_steps = [
                "Set PREMASTER to receive the routed mix in Ableton's Audio From/Input section.",
                "Set PREMASTER monitoring so routed audio is audible and reaches Main.",
                "Start playback and confirm PREMASTER shows audible meter movement.",
                "Only then export and run validate_audio_export on the rendered file.",
            ]
            state = "export-failed"
            failure_code = None

    return {
        "safe": safe,
        "state": state,
        "failure_code": failure_code,
        "issues": issues,
        "missing_capabilities": missing_tools,
        "probe_failures": probe_failures,
        "premaster_name": premaster_name,
        "recommended_action": recommended_action,
        "manual_steps": manual_steps,
        "remote_script_probe": capability_probe,
        "remote_script_diagnostic": None if capability_probe is None else capability_probe.get("diagnostic"),
    }


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


def _mono_audio(data):
    import numpy as np

    if data.ndim == 1:
        return data.astype(float, copy=False)
    return np.mean(data, axis=1)


def _first_audible_time_seconds(
    data,
    rate: int,
    threshold_dbfs: float = DEFAULT_FIRST_AUDIBLE_THRESHOLD_DBFS,
    window_seconds: float = DEFAULT_FIRST_AUDIBLE_WINDOW_SECONDS,
) -> Optional[float]:
    import numpy as np

    if rate <= 0:
        return None

    mono = _mono_audio(data)
    if mono.size == 0:
        return None

    window_samples = max(1, int(rate * max(0.1, window_seconds)))
    hop_samples = max(1, window_samples // 2)
    threshold_linear = 10.0 ** (threshold_dbfs / 20.0)

    for start in range(0, max(1, mono.size - window_samples + 1), hop_samples):
        window = mono[start:start + window_samples]
        rms_linear = float(np.sqrt(np.mean(np.square(window)))) if window.size else 0.0
        if rms_linear >= threshold_linear:
            return float(start) / float(rate)

    final_start = max(0, mono.size - window_samples)
    window = mono[final_start:final_start + window_samples]
    rms_linear = float(np.sqrt(np.mean(np.square(window)))) if window.size else 0.0
    if rms_linear >= threshold_linear:
        return float(final_start) / float(rate)
    return None


def _band_limited_rms_dbfs(section_mono, rate: int, low_hz: float, high_hz: float) -> float:
    import numpy as np
    from scipy.signal import butter, sosfilt, sosfiltfilt

    if rate <= 0 or section_mono.size == 0:
        return _linear_to_db(0.0)

    nyquist = float(rate) * 0.5
    low = max(1.0, float(low_hz))
    high = min(float(high_hz), nyquist * 0.999)
    if not high > low:
        return _linear_to_db(0.0)

    sos = butter(4, [low, high], btype="bandpass", fs=rate, output="sos")
    try:
        filtered = sosfiltfilt(sos, section_mono)
    except ValueError:
        filtered = sosfilt(sos, section_mono)
    rms_linear = float(np.sqrt(np.mean(np.square(filtered)))) if filtered.size else 0.0
    return _linear_to_db(rms_linear)


def _audio_section_metrics(
    data,
    rate: int,
    section_seconds: float = DEFAULT_EXPORT_SECTION_SECONDS,
) -> List[Dict[str, Any]]:
    import numpy as np

    if rate <= 0:
        return []
    if data.ndim == 1:
        data = data[:, np.newaxis]

    section_samples = max(1, int(rate * max(1.0, section_seconds)))
    mono = _mono_audio(data)
    sections = []

    for index, start in enumerate(range(0, data.shape[0], section_samples)):
        section = data[start:start + section_samples]
        section_mono = mono[start:start + section_samples]
        if section.size == 0:
            continue
        rms_linear = float(np.sqrt(np.mean(np.square(section)))) if section.size else 0.0
        peak_linear = float(np.max(np.abs(section))) if section.size else 0.0
        bands_dbfs = {
            name: _band_limited_rms_dbfs(section_mono, rate, low_hz, high_hz)
            for name, low_hz, high_hz in EXPORT_CONTENT_BANDS
        }
        sections.append({
            "index": index,
            "start_seconds": float(start) / float(rate),
            "duration_seconds": float(section.shape[0]) / float(rate),
            "rms_dbfs": _linear_to_db(rms_linear),
            "peak_dbfs": _linear_to_db(peak_linear),
            "bands_dbfs": bands_dbfs,
        })
    return sections


def _compare_audio_sections(
    output_sections: List[Dict[str, Any]],
    reference_sections: List[Dict[str, Any]],
    active_threshold_dbfs: float = DEFAULT_EXPORT_CONTENT_ACTIVE_THRESHOLD_DBFS,
    drop_threshold_db: float = DEFAULT_EXPORT_REFERENCE_DROP_THRESHOLD_DB,
) -> List[Dict[str, Any]]:
    flagged_sections = []
    common_count = min(len(output_sections), len(reference_sections))
    tracked_bands = ("mid", "high")

    for index in range(common_count):
        output_section = output_sections[index]
        reference_section = reference_sections[index]
        rms_delta_db = output_section["rms_dbfs"] - reference_section["rms_dbfs"]
        band_deltas_db = {}
        flagged_bands = []

        for band_name in tracked_bands:
            output_band = output_section["bands_dbfs"].get(band_name, _linear_to_db(0.0))
            reference_band = reference_section["bands_dbfs"].get(band_name, _linear_to_db(0.0))
            band_delta_db = output_band - reference_band
            band_deltas_db[band_name] = band_delta_db
            if reference_band > active_threshold_dbfs and band_delta_db <= -abs(drop_threshold_db):
                flagged_bands.append(band_name)

        rms_flagged = (
            reference_section["rms_dbfs"] > active_threshold_dbfs and
            rms_delta_db <= -abs(drop_threshold_db)
        )
        if rms_flagged or flagged_bands:
            flagged_sections.append({
                "index": output_section["index"],
                "start_seconds": output_section["start_seconds"],
                "output_rms_dbfs": output_section["rms_dbfs"],
                "reference_rms_dbfs": reference_section["rms_dbfs"],
                "rms_delta_db": rms_delta_db,
                "band_deltas_db": band_deltas_db,
                "flagged_bands": flagged_bands,
            })

    return flagged_sections


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


def _audio_window_peak_dbfs(data, window_count: int = DEFAULT_EXPORT_WINDOW_COUNT) -> List[float]:
    import numpy as np

    if data.ndim == 1:
        data = data[:, np.newaxis]

    total_samples = data.shape[0]
    if total_samples <= 0:
        return [_linear_to_db(0.0) for _ in range(window_count)]

    boundaries = np.linspace(0, total_samples, window_count + 1, dtype=int)
    peaks = []
    for index in range(window_count):
        window = data[boundaries[index]:boundaries[index + 1]]
        peak_linear = float(np.max(np.abs(window))) if window.size else 0.0
        peaks.append(_linear_to_db(peak_linear))
    return peaks


def _pick_loudest_preview_window(data, rate: int, preview_seconds: float = DEFAULT_EXPORT_PREVIEW_SECONDS):
    import numpy as np

    if data.ndim == 1:
        data = data[:, np.newaxis]

    total_samples = data.shape[0]
    if total_samples <= 0 or rate <= 0:
        return data[:0], 0.0, 0.0, _linear_to_db(0.0)

    window_samples = max(1, int(rate * max(0.1, preview_seconds)))
    if total_samples <= window_samples:
        excerpt = data
        peak_linear = float(np.max(np.abs(excerpt))) if excerpt.size else 0.0
        return excerpt, 0.0, float(total_samples) / float(rate), _linear_to_db(peak_linear)

    hop_samples = max(1, int(rate))
    best_start = 0
    best_peak = -1.0

    for start in range(0, total_samples - window_samples + 1, hop_samples):
        excerpt = data[start:start + window_samples]
        peak_linear = float(np.max(np.abs(excerpt))) if excerpt.size else 0.0
        if peak_linear > best_peak:
            best_peak = peak_linear
            best_start = start

    final_start = total_samples - window_samples
    final_excerpt = data[final_start:final_start + window_samples]
    final_peak = float(np.max(np.abs(final_excerpt))) if final_excerpt.size else 0.0
    if final_peak > best_peak:
        best_peak = final_peak
        best_start = final_start

    excerpt = data[best_start:best_start + window_samples]
    return (
        excerpt,
        float(best_start) / float(rate),
        float(excerpt.shape[0]) / float(rate),
        _linear_to_db(best_peak if best_peak >= 0.0 else 0.0),
    )


def _play_audio_preview(data, rate: int, preview_seconds: float = DEFAULT_EXPORT_PREVIEW_SECONDS) -> Dict[str, Any]:
    import soundfile as sf

    excerpt, start_seconds, duration_seconds, peak_dbfs = _pick_loudest_preview_window(
        data,
        rate,
        preview_seconds=preview_seconds,
    )
    preview = {
        "attempted": True,
        "status": "failed",
        "excerpt_start_seconds": start_seconds,
        "excerpt_duration_seconds": duration_seconds,
        "excerpt_peak_dbfs": peak_dbfs,
    }

    if duration_seconds <= 0.0 or excerpt.size == 0:
        preview["reason"] = "No audio samples available for preview."
        return preview

    afplay_path = shutil.which("afplay")
    if afplay_path is None:
        preview["reason"] = "afplay is not available on this system."
        return preview

    preview_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            preview_path = handle.name
        sf.write(preview_path, excerpt, rate)
        subprocess.run(
            [afplay_path, preview_path],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=max(duration_seconds + 5.0, 5.0),
        )
        preview["status"] = "played"
    except Exception as exc:
        preview["reason"] = str(exc)
    finally:
        if preview_path and os.path.exists(preview_path):
            try:
                os.unlink(preview_path)
            except OSError:
                pass

    return preview


def _candidate_export_paths(file_path: str) -> List[str]:
    abs_path = os.path.abspath(os.path.expanduser(file_path))
    base, ext = os.path.splitext(abs_path)
    candidates = [abs_path]
    if ext:
        candidates.append(abs_path + ext)
    else:
        for extension in EXPORT_AUDIO_EXTENSIONS:
            candidates.append(abs_path + extension)
    deduped = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _wait_for_stable_export_file(
    file_path: str,
    timeout_seconds: float = DEFAULT_EXPORT_WAIT_TIMEOUT_SECONDS,
    poll_interval_seconds: float = DEFAULT_EXPORT_WAIT_POLL_INTERVAL_SECONDS,
    stable_polls: int = DEFAULT_EXPORT_WAIT_STABLE_POLLS,
) -> Dict[str, Any]:
    requested_path = os.path.abspath(os.path.expanduser(file_path))
    candidate_paths = _candidate_export_paths(requested_path)
    deadline = time.time() + max(0.0, timeout_seconds)
    fresh_cutoff = time.time() - max(2.0, poll_interval_seconds * 2.0)
    last_signature = None
    stable_count = 0

    while True:
        existing_states = []
        for candidate in candidate_paths:
            try:
                stat_result = os.stat(candidate)
            except OSError:
                continue
            if stat_result.st_mtime < fresh_cutoff:
                continue
            existing_states.append({
                "path": candidate,
                "size_bytes": int(stat_result.st_size),
                "mtime": float(stat_result.st_mtime),
            })

        if existing_states:
            selected = max(existing_states, key=lambda item: (item["mtime"], item["size_bytes"], item["path"]))
            signature = (selected["path"], selected["size_bytes"], selected["mtime"])
            if signature == last_signature:
                stable_count += 1
            else:
                stable_count = 1
                last_signature = signature
            if stable_count >= max(1, stable_polls):
                return {
                    "requested_file_path": requested_path,
                    "resolved_file_path": selected["path"],
                    "path_normalized": selected["path"] != requested_path,
                    "resolved_size_bytes": selected["size_bytes"],
                    "resolved_mtime": selected["mtime"],
                    "candidate_paths": candidate_paths,
                }

        if time.time() >= deadline:
            break
        time.sleep(max(0.05, poll_interval_seconds))

    return {
        "requested_file_path": requested_path,
        "resolved_file_path": None,
        "path_normalized": False,
        "resolved_size_bytes": None,
        "resolved_mtime": None,
        "candidate_paths": candidate_paths,
    }


def _validate_audio_export_data(
    file_path: str,
    expected_duration_seconds: Optional[float] = None,
    silence_threshold_dbfs: float = DEFAULT_EXPORT_SILENCE_THRESHOLD_DBFS,
    max_first_audible_seconds: Optional[float] = DEFAULT_EXPORT_MAX_FIRST_AUDIBLE_SECONDS,
    first_audible_threshold_dbfs: float = DEFAULT_FIRST_AUDIBLE_THRESHOLD_DBFS,
    first_audible_window_seconds: float = DEFAULT_FIRST_AUDIBLE_WINDOW_SECONDS,
    reference_file_path: Optional[str] = None,
    max_first_audible_delta_seconds: float = DEFAULT_EXPORT_MAX_FIRST_AUDIBLE_DELTA_SECONDS,
    section_seconds: float = DEFAULT_EXPORT_SECTION_SECONDS,
    reference_drop_threshold_db: float = DEFAULT_EXPORT_REFERENCE_DROP_THRESHOLD_DB,
    window_count: int = DEFAULT_EXPORT_WINDOW_COUNT,
    preview_seconds: float = DEFAULT_EXPORT_PREVIEW_SECONDS,
    wait_timeout_seconds: float = DEFAULT_EXPORT_WAIT_TIMEOUT_SECONDS,
    wait_poll_interval_seconds: float = DEFAULT_EXPORT_WAIT_POLL_INTERVAL_SECONDS,
    stable_polls: int = DEFAULT_EXPORT_WAIT_STABLE_POLLS,
    play_preview: bool = True,
) -> Dict[str, Any]:
    import soundfile as sf

    export_result = _wait_for_stable_export_file(
        file_path,
        timeout_seconds=wait_timeout_seconds,
        poll_interval_seconds=wait_poll_interval_seconds,
        stable_polls=stable_polls,
    )

    result = {
        "state": "export-failed",
        "requested_file_path": export_result["requested_file_path"],
        "resolved_file_path": export_result.get("resolved_file_path"),
        "path_normalized": export_result.get("path_normalized", False),
        "reason": None,
        "export_validation": {
            "candidate_paths": export_result.get("candidate_paths", []),
            "expected_duration_seconds": expected_duration_seconds,
            "silence_threshold_dbfs": silence_threshold_dbfs,
            "window_count": window_count,
            "failed_checks": [],
            "content_presence": {
                "first_audible_threshold_dbfs": first_audible_threshold_dbfs,
                "first_audible_window_seconds": first_audible_window_seconds,
                "max_first_audible_seconds": max_first_audible_seconds,
                "reference_file_path": (
                    os.path.abspath(os.path.expanduser(reference_file_path))
                    if reference_file_path else None
                ),
                "max_first_audible_delta_seconds": max_first_audible_delta_seconds,
                "section_seconds": section_seconds,
                "reference_drop_threshold_db": reference_drop_threshold_db,
                "section_metrics": [],
                "flagged_sections": [],
            },
        },
        "preview": {
            "attempted": False,
            "status": "skipped",
        },
    }

    resolved_file_path = export_result.get("resolved_file_path")
    if not resolved_file_path:
        result["reason"] = "Timed out waiting for a fresh rendered audio file."
        result["export_validation"]["failed_checks"].append("file_missing")
        return result

    analysis = _analyze_audio_file_data(resolved_file_path)
    data, rate = sf.read(resolved_file_path, always_2d=True)
    window_peak_dbfs = _audio_window_peak_dbfs(data, window_count=window_count)
    content_presence = result["export_validation"]["content_presence"]
    output_first_audible_seconds = _first_audible_time_seconds(
        data,
        rate,
        threshold_dbfs=first_audible_threshold_dbfs,
        window_seconds=first_audible_window_seconds,
    )
    output_sections = _audio_section_metrics(data, rate, section_seconds=section_seconds)
    content_presence["first_audible_seconds"] = output_first_audible_seconds
    content_presence["section_metrics"] = output_sections

    failed_checks = result["export_validation"]["failed_checks"]
    if expected_duration_seconds is not None and expected_duration_seconds > 0.0:
        duration_ratio = analysis["duration_seconds"] / expected_duration_seconds
        result["export_validation"]["duration_ratio"] = duration_ratio
        if analysis["duration_seconds"] < expected_duration_seconds * DEFAULT_DURATION_IMPLAUSIBLE_RATIO:
            failed_checks.append("duration_implausibly_short")

    if not math.isfinite(analysis["lufs_i"]):
        failed_checks.append("non_finite_lufs")
    if analysis["sample_peak_dbfs"] < silence_threshold_dbfs:
        failed_checks.append("sample_peak_below_threshold")
    if all(peak < silence_threshold_dbfs for peak in window_peak_dbfs):
        failed_checks.append("all_window_peaks_below_threshold")
    if (
        max_first_audible_seconds is not None and
        output_first_audible_seconds is not None and
        output_first_audible_seconds > max_first_audible_seconds
    ):
        failed_checks.append("first_audible_exceeds_expected")

    result["export_validation"].update({
        "file_path": analysis["file_path"],
        "sample_rate": analysis["sample_rate"],
        "channels": analysis["channels"],
        "duration_seconds": analysis["duration_seconds"],
        "lufs_i": analysis["lufs_i"],
        "lufs_s_max": analysis["lufs_s_max"],
        "lra": analysis["lra"],
        "true_peak_dbtp": analysis["true_peak_dbtp"],
        "sample_peak_dbfs": analysis["sample_peak_dbfs"],
        "window_peak_dbfs": window_peak_dbfs,
    })

    if reference_file_path:
        reference_abs_path = os.path.abspath(os.path.expanduser(reference_file_path))
        content_presence["reference_file_path"] = reference_abs_path
        if not os.path.exists(reference_abs_path):
            failed_checks.append("reference_file_missing")
        else:
            reference_analysis = _analyze_audio_file_data(reference_abs_path)
            reference_data, reference_rate = sf.read(reference_abs_path, always_2d=True)
            if expected_duration_seconds is None and reference_analysis["duration_seconds"] > 0.0:
                result["export_validation"]["expected_duration_seconds"] = reference_analysis["duration_seconds"]
                duration_ratio = analysis["duration_seconds"] / reference_analysis["duration_seconds"]
                result["export_validation"]["duration_ratio"] = duration_ratio
                if analysis["duration_seconds"] < reference_analysis["duration_seconds"] * DEFAULT_DURATION_IMPLAUSIBLE_RATIO:
                    failed_checks.append("duration_implausibly_short")

            reference_first_audible_seconds = _first_audible_time_seconds(
                reference_data,
                reference_rate,
                threshold_dbfs=first_audible_threshold_dbfs,
                window_seconds=first_audible_window_seconds,
            )
            reference_sections = _audio_section_metrics(
                reference_data,
                reference_rate,
                section_seconds=section_seconds,
            )
            first_audible_delta_seconds = None
            if (
                output_first_audible_seconds is not None and
                reference_first_audible_seconds is not None
            ):
                first_audible_delta_seconds = output_first_audible_seconds - reference_first_audible_seconds
                if first_audible_delta_seconds > max_first_audible_delta_seconds:
                    failed_checks.append("first_audible_late_vs_reference")

            flagged_sections = _compare_audio_sections(
                output_sections,
                reference_sections,
                drop_threshold_db=reference_drop_threshold_db,
            )
            if flagged_sections:
                failed_checks.append("reference_content_drop_detected")

            content_presence.update({
                "reference_duration_seconds": reference_analysis["duration_seconds"],
                "reference_first_audible_seconds": reference_first_audible_seconds,
                "first_audible_delta_seconds": first_audible_delta_seconds,
                "reference_section_metrics": reference_sections,
                "flagged_sections": flagged_sections,
            })

    if play_preview:
        result["preview"] = _play_audio_preview(data, rate, preview_seconds=preview_seconds)

    if failed_checks:
        result["reason"] = "Export validation failed."
    else:
        result["state"] = "export-validated"

    return result


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
def get_track_info(ctx: Context, track_index: int, track_scope: str = "track") -> str:
    """Get detailed information about a track, return, or master bus."""
    try:
        ableton = get_ableton_connection()
        result = _get_track_data(
            ableton,
            track_index,
            summary=_compact_response_enabled(),
            track_scope=track_scope,
        )
        return _json_response(_track_payload_for_response(result))
    except Exception as e:
        logger.error(f"Error getting track info from Ableton: {str(e)}")
        return f"Error getting track info: {str(e)}"


@mcp.tool()
def get_track_devices(ctx: Context, track_index: int, track_scope: str = "track") -> str:
    """Get lightweight device metadata for a track, return, or master bus."""
    try:
        ableton = get_ableton_connection()
        result = _get_track_devices_data(ableton, track_index, track_scope=track_scope)
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error getting track devices from Ableton: {str(e)}")
        return f"Error getting track devices: {str(e)}"


@mcp.tool()
def get_track_routing(ctx: Context, track_index: int, track_scope: str = "track") -> str:
    """Get routing information for a track, return, or master bus."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_track_routing", _track_scope_params(track_index, track_scope))
        if _compact_response_enabled():
            return _json_response(_compact_routing_payload(result))
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error getting track routing from Ableton: {str(e)}")
        return f"Error getting track routing: {str(e)}"


@mcp.tool()
def get_track_input_routing(ctx: Context, track_index: int) -> str:
    """Get input routing information for a regular track."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_track_input_routing", {"track_index": track_index})
        if _compact_response_enabled():
            return _json_response(_compact_routing_payload(result))
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error getting track input routing from Ableton: {str(e)}")
        return f"Error getting track input routing: {str(e)}"


@mcp.tool()
def set_track_input_routing(
    ctx: Context,
    track_index: int,
    routing_type_name: str,
    routing_channel_name: Optional[str] = None,
) -> str:
    """Set the input routing type and optional channel for a track."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_input_routing", {
            "track_index": track_index,
            "routing_type_name": routing_type_name,
            "routing_channel_name": routing_channel_name,
        })
        if _compact_response_enabled():
            return _json_response(_compact_routing_payload(result))
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error setting track input routing: {str(e)}")
        return f"Error setting track input routing: {str(e)}"


@mcp.tool()
def get_track_monitor_state(ctx: Context, track_index: int) -> str:
    """Get the current monitoring state for a regular track."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_track_monitor_state", {"track_index": track_index})
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error getting track monitor state: {str(e)}")
        return f"Error getting track monitor state: {str(e)}"


@mcp.tool()
def set_track_monitor_state(
    ctx: Context,
    track_index: int,
    state_name: Optional[str] = None,
    state_value: Optional[int] = None,
) -> str:
    """Set the current monitoring state for a regular track."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_monitor_state", {
            "track_index": track_index,
            "state_name": state_name,
            "state_value": state_value,
        })
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error setting track monitor state: {str(e)}")
        return f"Error setting track monitor state: {str(e)}"


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
def get_track_meter(ctx: Context, track_index: int, track_scope: str = "track") -> str:
    """Get real-time output meter values for a track, return, or master bus."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_track_meter", _track_scope_params(track_index, track_scope))
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error getting track meter from Ableton: {str(e)}")
        return f"Error getting track meter: {str(e)}"


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
def sample_track_meter(
    ctx: Context,
    track_index: int,
    track_scope: str = "track",
    duration_seconds: float = 5.0,
    interval_ms: int = 250,
) -> str:
    """Sample a track, return, or master meter and report the maximum values."""
    try:
        ableton = get_ableton_connection()
        interval_seconds = max(0.05, float(interval_ms) / 1000.0)
        duration_seconds = max(interval_seconds, float(duration_seconds))
        sample_count = max(1, int(math.ceil(duration_seconds / interval_seconds)))
        command_params = _track_scope_params(track_index, track_scope)

        samples = []
        for _ in range(sample_count):
            samples.append(ableton.send_command("get_track_meter", command_params))
            time.sleep(interval_seconds)

        peak_linear = max(sample.get("peak_linear") or 0.0 for sample in samples)
        level_linear = max(sample.get("level_linear") or 0.0 for sample in samples)
        result = {
            "track_scope": command_params["track_scope"],
            "track_index": track_index,
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
                "track_scope": result["track_scope"],
                "track_index": result["track_index"],
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
        logger.error(f"Error sampling track meter: {str(e)}")
        return f"Error sampling track meter: {str(e)}"

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
        routing_safety = _premaster_routing_safety_data(premaster_name, ableton=ableton)
        if not routing_safety["safe"]:
            result = {
                "state": routing_safety["state"],
                "failure_code": routing_safety.get("failure_code"),
                "reason": routing_safety.get("recommended_action"),
                "blocked": True,
                "premaster_created": False,
                "premaster_track_index": None,
                "premaster_track_name": premaster_name,
                "routed_track_indices": [],
                "excluded_track_indices": sorted(exclude_track_indices or []),
                "auto_reference_track_indices": [],
                "premaster_output_target": None,
                "routing_safety": routing_safety,
            }
            return _json_response(result)

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

        input_routing = ableton.send_command("get_track_input_routing", {"track_index": premaster_index})
        monitor_state = ableton.send_command("get_track_monitor_state", {"track_index": premaster_index})
        if monitor_state.get("current_monitoring_state_name") != "in":
            monitor_state = ableton.send_command("set_track_monitor_state", {
                "track_index": premaster_index,
                "state_name": "in",
            })

        result = {
            "state": "export-ready",
            "blocked": False,
            "premaster_created": premaster_result["created"],
            "premaster_track_index": premaster_index,
            "premaster_track_name": premaster_track["name"],
            "routed_track_indices": routed_tracks,
            "excluded_track_indices": sorted(exclude_indices),
            "auto_reference_track_indices": sorted(auto_reference_indices),
            "premaster_output_target": main_output_name,
            "premaster_input_routing": input_routing,
            "premaster_monitor_state": monitor_state,
            "routing_safety": routing_safety,
        }
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error creating premaster routing: {str(e)}")
        return f"Error creating premaster routing: {str(e)}"

@mcp.tool()
def get_device_parameters(
    ctx: Context,
    track_index: int,
    device_index: int,
    track_scope: str = "track",
) -> str:
    """Get all parameters of a device on a track, return, or master bus."""
    try:
        ableton = get_ableton_connection()
        params = _track_scope_params(track_index, track_scope)
        params["device_index"] = device_index
        result = ableton.send_command("get_device_parameters", params)
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error getting device parameters: {str(e)}")
        return f"Error getting device parameters: {str(e)}"

@mcp.tool()
def set_device_parameter(
    ctx: Context,
    track_index: int,
    device_index: int,
    parameter_index: int,
    value: float,
    track_scope: str = "track",
) -> str:
    """Set a device parameter on a track, return, or master bus."""
    try:
        ableton = get_ableton_connection()
        params = _track_scope_params(track_index, track_scope)
        params.update({
            "device_index": device_index,
            "parameter_index": parameter_index,
            "value": value,
        })
        result = ableton.send_command("set_device_parameter", params)
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error setting device parameter: {str(e)}")
        return f"Error setting device parameter: {str(e)}"


@mcp.tool()
def find_device_by_name(
    ctx: Context,
    track_index: int,
    name: str,
    track_scope: str = "track",
    exact: bool = True,
) -> str:
    """Find devices on a track, return, or master bus by name."""
    try:
        ableton = get_ableton_connection()
        params = _track_scope_params(track_index, track_scope)
        params.update({"name": name, "exact": exact})
        result = ableton.send_command("find_device_by_name", params)
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error finding device by name: {str(e)}")
        return f"Error finding device by name: {str(e)}"


@mcp.tool()
def delete_device(ctx: Context, track_index: int, device_index: int, track_scope: str = "track") -> str:
    """Delete a device from a track, return, or master bus."""
    try:
        ableton = get_ableton_connection()
        params = _track_scope_params(track_index, track_scope)
        params["device_index"] = device_index
        result = ableton.send_command("delete_device", params)
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error deleting device: {str(e)}")
        return f"Error deleting device: {str(e)}"


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
def append_browser_device(ctx: Context, track_index: int, item_uri: str, track_scope: str = "track") -> str:
    """Append a browser item to the end of a track, return, or master chain."""
    try:
        ableton = get_ableton_connection()
        result = _append_browser_device_data(ableton, track_index, item_uri, track_scope=track_scope)
        if _compact_response_enabled():
            return _json_response(_compact_append_browser_device_result(result))
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error appending browser device: {str(e)}")
        return f"Error appending browser device: {str(e)}"


@mcp.tool()
def append_mastering_chain(
    ctx: Context,
    track_index: int,
    preset_name: str,
    track_scope: str = "track",
) -> str:
    """Append a stock mastering chain to a track, return, or master bus."""
    try:
        ableton = get_ableton_connection()
        result = _append_mastering_chain_data(
            ableton,
            track_index,
            preset_name,
            track_scope=track_scope,
        )
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
def load_instrument_or_effect(
    ctx: Context,
    track_index: int,
    uri: str,
    track_scope: str = "track",
) -> str:
    """Load an instrument or effect onto a track, return, or master bus by URI."""
    try:
        ableton = get_ableton_connection()
        params = _track_scope_params(track_index, track_scope)
        params["item_uri"] = uri
        result = ableton.send_command("load_browser_item", params)
        
        # Check if the instrument was loaded successfully
        if result.get("loaded", False):
            new_devices = result.get("new_devices", [])
            if new_devices:
                return (
                    f"Loaded instrument with URI '{uri}' on {track_scope} {track_index}. "
                    f"New devices: {', '.join(new_devices)}"
                )
            else:
                devices = result.get("devices_after", [])
                return (
                    f"Loaded instrument with URI '{uri}' on {track_scope} {track_index}. "
                    f"Devices on bus: {', '.join(devices)}"
                )
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
def get_arrangement_summary(
    ctx: Context,
    detail_level: str = "basic",
    timeout_seconds: float = DEFAULT_ARRANGEMENT_SUMMARY_TIMEOUT_SECONDS,
) -> str:
    """Summarize the opened arrangement with configurable detail."""
    try:
        ableton = get_ableton_connection()
        result = _get_arrangement_summary_data(
            ableton,
            detail_level=detail_level,
            timeout_seconds=timeout_seconds,
        )
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error getting arrangement summary: {str(e)}")
        return f"Error getting arrangement summary: {str(e)}"


@mcp.tool()
def diagnose_remote_script_install(ctx: Context) -> str:
    """Compare the repo Remote Script, the installed Ableton script, and the live socket capabilities."""
    try:
        ableton = get_ableton_connection()
    except Exception:
        ableton = None
    result = _diagnose_remote_script_install_data(ableton=ableton)
    return _json_response(result)


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
def resolve_mastering_source(
    ctx: Context,
    requested_source: str = "opened-live-set",
    file_path: Optional[str] = None,
    allow_file_fallback: bool = False,
) -> str:
    """
    Resolve the permitted mastering source and report provenance.

    Parameters:
    - requested_source: 'opened-live-set' for the current Ableton set or 'file' for an explicit file source
    - file_path: Optional explicit file source or authorized fallback file
    - allow_file_fallback: Whether an opened-live-set request may explicitly fall back to file_path
    """
    try:
        result = _resolve_mastering_source_data(
            requested_source=requested_source,
            file_path=file_path,
            allow_file_fallback=allow_file_fallback,
        )
        if _compact_response_enabled():
            return _json_response(_compact_resolve_mastering_source_result(result))
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error resolving mastering source: {str(e)}")
        return f"Error resolving mastering source: {str(e)}"


@mcp.tool()
def export_audio_macos(
    ctx: Context,
    output_folder: str,
    file_name: str,
    render_source: str = "Main",
    sample_rate: int = 44100,
    bit_depth: int = 24,
    normalize: bool = False,
    dither: str = "Triangular",
    expected_duration_seconds: Optional[float] = None,
    reference_file_path: Optional[str] = None,
) -> str:
    """Render the opened Ableton set through the macOS export dialog and validate the file."""
    try:
        result = _export_audio_macos_data(
            output_folder=output_folder,
            file_name=file_name,
            render_source=render_source,
            sample_rate=sample_rate,
            bit_depth=bit_depth,
            normalize=normalize,
            dither=dither,
            expected_duration_seconds=expected_duration_seconds,
            reference_file_path=reference_file_path,
        )
        if _compact_response_enabled():
            return _json_response(_compact_export_audio_macos_result(result))
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error exporting audio on macOS: {str(e)}")
        return f"Error exporting audio on macOS: {str(e)}"


@mcp.tool()
def master_and_export_opened_set(
    ctx: Context,
    output_folder: str,
    file_name: str,
    preset_name: str = "MINIMAL_TOUCH",
    render_source: str = "Main",
    sample_rate: int = 44100,
    bit_depth: int = 24,
    normalize: bool = False,
    dither: str = "Triangular",
    reference_file_path: Optional[str] = None,
) -> str:
    """Apply a stock mastering chain to the opened set, export it on macOS, and validate the result."""
    try:
        source_provenance = _resolve_mastering_source_data(
            requested_source="opened-live-set",
            allow_file_fallback=False,
        )
        normalized_file_name = macos_export.normalize_export_file_name(file_name)
        result: Dict[str, Any] = {
            "state": "export-blocked",
            "failure_code": None,
            "reason": None,
            "measurement_mode": "offline_render",
            "source_provenance": source_provenance,
            "remote_script_probe": None,
            "remote_script_diagnostic": None,
            "arrangement_readiness": None,
            "arrangement_summary": None,
            "mastering": None,
            "analysis_render": None,
            "mastering_adjustment": None,
            "requested_file_path": _normalize_export_request_path(output_folder, file_name),
            "resolved_file_path": None,
            "preflight": {},
            "ui_automation": {},
            "export_validation": {},
            "preview": {
                "attempted": False,
                "status": "skipped",
            },
        }

        if source_provenance.get("state") != "source-ready":
            result["reason"] = source_provenance.get("reason")
            result["failure_code"] = "export-blocked"
            if _compact_response_enabled():
                return _json_response(_compact_master_and_export_result(result))
            return _json_response(result)

        ableton = get_ableton_connection()
        remote_script_probe = _probe_remote_script_capabilities_data(
            ableton,
            required_capabilities=list(REMOTE_SCRIPT_MASTERING_REQUIRED_CAPABILITIES),
            verify_master_scope=True,
        )
        result["remote_script_probe"] = remote_script_probe
        result["remote_script_diagnostic"] = remote_script_probe.get("diagnostic")
        if not remote_script_probe.get("ok"):
            result["failure_code"] = "stale_remote_script"
            result["reason"] = remote_script_probe["diagnostic"]["recommended_action"]
            if _compact_response_enabled():
                return _json_response(_compact_master_and_export_result(result))
            return _json_response(result)

        readiness = _ensure_arrangement_export_ready_data(ableton)
        result["arrangement_readiness"] = readiness
        if not readiness.get("ready"):
            result["reason"] = readiness.get("recommended_action")
            result["failure_code"] = "export-blocked"
            if _compact_response_enabled():
                return _json_response(_compact_master_and_export_result(result))
            return _json_response(result)

        arrangement_summary = _get_arrangement_summary_data(
            ableton,
            detail_level="basic",
            timeout_seconds=DEFAULT_ARRANGEMENT_SUMMARY_TIMEOUT_SECONDS,
        )
        result["arrangement_summary"] = arrangement_summary
        if arrangement_summary.get("state") != "ok":
            result["failure_code"] = arrangement_summary.get("failure_code", "arrangement_summary_failed")
            result["reason"] = arrangement_summary.get("reason")
            if _compact_response_enabled():
                return _json_response(_compact_master_and_export_result(result))
            return _json_response(result)

        mastering = _append_mastering_chain_data(
            ableton,
            track_index=0,
            preset_name=preset_name,
            track_scope="master",
        )
        result["mastering"] = mastering
        if mastering.get("state") == "mastering-blocked":
            result["failure_code"] = mastering.get("failure_code")
            result["reason"] = mastering.get("reason")
            if mastering.get("remote_script_probe"):
                result["remote_script_probe"] = mastering["remote_script_probe"]
                result["remote_script_diagnostic"] = mastering.get("remote_script_diagnostic")
            if _compact_response_enabled():
                return _json_response(_compact_master_and_export_result(result))
            return _json_response(result)

        analysis_folder = tempfile.mkdtemp(prefix="ableton-mcp-analysis-")
        analysis_file_name = os.path.splitext(normalized_file_name)[0] + ".__analysis__.wav"
        analysis_render = _export_audio_macos_data(
            output_folder=analysis_folder,
            file_name=analysis_file_name,
            render_source=render_source,
            sample_rate=sample_rate,
            bit_depth=bit_depth,
            normalize=normalize,
            dither=dither,
            expected_duration_seconds=_expected_duration_from_arrangement_summary(arrangement_summary),
            play_preview=False,
        )
        result["analysis_render"] = analysis_render
        if analysis_render.get("state") != "export-validated":
            result.update({
                "state": analysis_render.get("state", "export-failed"),
                "failure_code": analysis_render.get("failure_code"),
                "reason": analysis_render.get("reason"),
                "preflight": analysis_render.get("preflight", {}),
                "ui_automation": analysis_render.get("ui_automation", {}),
                "export_validation": analysis_render.get("export_validation", {}),
                "preview": analysis_render.get("preview", result["preview"]),
                "resolved_file_path": analysis_render.get("resolved_file_path"),
            })
            if _compact_response_enabled():
                return _json_response(_compact_master_and_export_result(result))
            return _json_response(result)

        try:
            mastering_adjustment = _apply_mastering_gain_correction_data(
                ableton,
                mastering,
                analysis_render.get("export_validation", {}),
                track_scope="master",
                track_index=0,
            )
        except Exception as exc:
            mastering_adjustment = {
                "attempted": False,
                "applied": False,
                "reason": str(exc),
            }
        result["mastering_adjustment"] = mastering_adjustment

        validation_reference_file_path = analysis_render.get("resolved_file_path") or reference_file_path
        export_result = _export_audio_macos_data(
            output_folder=output_folder,
            file_name=normalized_file_name,
            render_source=render_source,
            sample_rate=sample_rate,
            bit_depth=bit_depth,
            normalize=normalize,
            dither=dither,
            expected_duration_seconds=_expected_duration_from_arrangement_summary(arrangement_summary),
            reference_file_path=validation_reference_file_path,
        )
        result.update({
            "state": export_result.get("state"),
            "failure_code": export_result.get("failure_code"),
            "reason": export_result.get("reason"),
            "requested_file_path": export_result.get("requested_file_path"),
            "resolved_file_path": export_result.get("resolved_file_path"),
            "preflight": export_result.get("preflight", {}),
            "ui_automation": export_result.get("ui_automation", {}),
            "export_validation": export_result.get("export_validation", {}),
            "preview": export_result.get("preview", result["preview"]),
        })
        if _compact_response_enabled():
            return _json_response(_compact_master_and_export_result(result))
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error mastering and exporting opened set: {str(e)}")
        return f"Error mastering and exporting opened set: {str(e)}"


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


@mcp.tool()
def validate_audio_export(
    ctx: Context,
    file_path: str,
    expected_duration_seconds: Optional[float] = None,
    silence_threshold_dbfs: float = DEFAULT_EXPORT_SILENCE_THRESHOLD_DBFS,
    max_first_audible_seconds: Optional[float] = DEFAULT_EXPORT_MAX_FIRST_AUDIBLE_SECONDS,
    first_audible_threshold_dbfs: float = DEFAULT_FIRST_AUDIBLE_THRESHOLD_DBFS,
    first_audible_window_seconds: float = DEFAULT_FIRST_AUDIBLE_WINDOW_SECONDS,
    reference_file_path: Optional[str] = None,
    max_first_audible_delta_seconds: float = DEFAULT_EXPORT_MAX_FIRST_AUDIBLE_DELTA_SECONDS,
    section_seconds: float = DEFAULT_EXPORT_SECTION_SECONDS,
    reference_drop_threshold_db: float = DEFAULT_EXPORT_REFERENCE_DROP_THRESHOLD_DB,
    play_preview: bool = True,
    preview_seconds: float = DEFAULT_EXPORT_PREVIEW_SECONDS,
    wait_timeout_seconds: float = DEFAULT_EXPORT_WAIT_TIMEOUT_SECONDS,
    wait_poll_interval_seconds: float = DEFAULT_EXPORT_WAIT_POLL_INTERVAL_SECONDS,
) -> str:
    """
    Wait for a rendered audio file, validate that it contains audible program material,
    and preview the loudest section.

    Parameters:
    - file_path: Intended output path for the rendered audio file
    - expected_duration_seconds: Optional expected duration to detect implausibly short renders
    - silence_threshold_dbfs: Threshold below which a render is treated as effectively silent
    - max_first_audible_seconds: Optional maximum allowed start time for the first audible content
    - first_audible_threshold_dbfs: RMS threshold used to detect the first audible content
    - first_audible_window_seconds: Window size used for first-audible detection
    - reference_file_path: Optional authoritative render to compare against for content-presence checks
    - max_first_audible_delta_seconds: Maximum allowed first-audible delay versus the reference file
    - section_seconds: Section size for RMS and band-energy checkpoint comparisons
    - reference_drop_threshold_db: Maximum allowed RMS or mid/high-band drop versus the reference
    - play_preview: Whether to preview the loudest excerpt with afplay
    - preview_seconds: Length of the preview excerpt in seconds
    - wait_timeout_seconds: How long to wait for the rendered file to appear and stop growing
    - wait_poll_interval_seconds: Poll interval while waiting for the file to stabilize
    """
    try:
        result = _validate_audio_export_data(
            file_path=file_path,
            expected_duration_seconds=expected_duration_seconds,
            silence_threshold_dbfs=silence_threshold_dbfs,
            max_first_audible_seconds=max_first_audible_seconds,
            first_audible_threshold_dbfs=first_audible_threshold_dbfs,
            first_audible_window_seconds=first_audible_window_seconds,
            reference_file_path=reference_file_path,
            max_first_audible_delta_seconds=max_first_audible_delta_seconds,
            section_seconds=section_seconds,
            reference_drop_threshold_db=reference_drop_threshold_db,
            preview_seconds=preview_seconds,
            wait_timeout_seconds=wait_timeout_seconds,
            wait_poll_interval_seconds=wait_poll_interval_seconds,
            play_preview=play_preview,
        )
        if _compact_response_enabled():
            return _json_response(_compact_validate_audio_export_result(result))
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error validating audio export: {str(e)}")
        return f"Error validating audio export: {str(e)}"

# Main execution
def main():
    """Run the MCP server"""
    mcp.run()

if __name__ == "__main__":
    main()

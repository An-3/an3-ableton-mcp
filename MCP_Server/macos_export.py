import os
import platform
import shutil
import subprocess
import time
import re
from typing import Any, Dict, Optional


ABLETON_PROCESS_PREFIX = "Ableton Live"
DEFAULT_AUDIO_EXTENSION = ".wav"
DEFAULT_OSASCRIPT_TIMEOUT_SECONDS = 15.0
DEFAULT_EXPORT_DIALOG_TIMEOUT_SECONDS = 10.0
DEFAULT_SAVE_PANEL_TIMEOUT_SECONDS = 10.0
DEFAULT_OVERWRITE_TIMEOUT_SECONDS = 2.0
EXPORT_SHORTCUT_KEY = "r"
EXPORT_SHORTCUT_MODIFIERS = "{command down, shift down}"
VALID_DITHER_OPTIONS = {
    "none": "None",
    "rectangular": "Rectangular",
    "triangular": "Triangular",
    "pow-r 1": "Pow-r 1",
    "pow-r 2": "Pow-r 2",
    "pow-r 3": "Pow-r 3",
}


def _quote_applescript_string(value: str) -> str:
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return '"' + escaped + '"'


def normalize_export_file_name(file_name: str) -> str:
    normalized = os.path.basename((file_name or "").strip())
    if not normalized:
        raise ValueError("file_name must not be empty")
    root, ext = os.path.splitext(normalized)
    if ext:
        return normalized
    return root + DEFAULT_AUDIO_EXTENSION


def normalize_export_settings(
    render_source: str,
    sample_rate: int,
    bit_depth: int,
    normalize: bool,
    dither: str,
) -> Dict[str, Any]:
    normalized_render_source = (render_source or "").strip()
    if not normalized_render_source:
        raise ValueError("render_source must not be empty")

    normalized_sample_rate = str(int(sample_rate))
    normalized_bit_depth = str(int(bit_depth))
    if normalized_bit_depth not in {"16", "24", "32"}:
        raise ValueError("bit_depth must be 16, 24, or 32")

    normalized_dither_key = (dither or "").strip().lower()
    if normalized_dither_key not in VALID_DITHER_OPTIONS:
        allowed = ", ".join(sorted(VALID_DITHER_OPTIONS.values()))
        raise ValueError("dither must be one of: {0}".format(allowed))

    return {
        "render_source": normalized_render_source,
        "sample_rate": normalized_sample_rate,
        "bit_depth": normalized_bit_depth,
        "normalize": bool(normalize),
        "dither": VALID_DITHER_OPTIONS[normalized_dither_key],
    }


def _common_ui_handlers() -> str:
    return """
on waitForPrimarySheet(processName, timeoutSeconds)
    tell application "System Events"
        repeat with iteration from 1 to (timeoutSeconds * 5)
            tell application process processName
                if (count of windows) > 0 then
                    try
                        if exists sheet 1 of window 1 then return sheet 1 of window 1
                    end try
                end if
            end tell
            delay 0.2
        end repeat
    end tell
    error "export_dialog_not_found::Timed out waiting for the export dialog sheet."
end waitForPrimarySheet

on waitForNestedSheet(processName, timeoutSeconds)
    tell application "System Events"
        repeat with iteration from 1 to (timeoutSeconds * 5)
            tell application process processName
                if (count of windows) > 0 then
                    try
                        if exists sheet 1 of sheet 1 of window 1 then return sheet 1 of sheet 1 of window 1
                    end try
                end if
            end tell
            delay 0.2
        end repeat
    end tell
    error "save_panel_not_found::Timed out waiting for the nested sheet."
end waitForNestedSheet

on firstGroupContainingLabel(containerRef, labelText)
    tell application "System Events"
        repeat with groupRef in (every group of containerRef)
            try
                repeat with textRef in (every static text of groupRef)
                    if (value of textRef as text) is labelText then return groupRef
                end repeat
            end try
            set nestedGroup to my firstGroupContainingLabel(groupRef, labelText)
            if nestedGroup is not missing value then return nestedGroup
        end repeat
    end tell
    return missing value
end firstGroupContainingLabel

on firstCheckboxNamed(containerRef, checkboxName)
    tell application "System Events"
        repeat with checkboxRef in (every checkbox of containerRef)
            try
                if (name of checkboxRef as text) is checkboxName then return checkboxRef
            end try
        end repeat
        repeat with groupRef in (every group of containerRef)
            set nestedCheckbox to my firstCheckboxNamed(groupRef, checkboxName)
            if nestedCheckbox is not missing value then return nestedCheckbox
        end repeat
    end tell
    return missing value
end firstCheckboxNamed

on firstButtonNamed(containerRef, buttonName)
    tell application "System Events"
        repeat with buttonRef in (every button of containerRef)
            try
                if (name of buttonRef as text) is buttonName then return buttonRef
            end try
        end repeat
        repeat with groupRef in (every group of containerRef)
            set nestedButton to my firstButtonNamed(groupRef, buttonName)
            if nestedButton is not missing value then return nestedButton
        end repeat
    end tell
    return missing value
end firstButtonNamed

on firstTextEntry(containerRef)
    tell application "System Events"
        try
            return text field 1 of containerRef
        end try
        try
            return combo box 1 of containerRef
        end try
        repeat with groupRef in (every group of containerRef)
            set nestedField to my firstTextEntry(groupRef)
            if nestedField is not missing value then return nestedField
        end repeat
    end tell
    return missing value
end firstTextEntry

on setPopUpByLabel(containerRef, labelText, itemText)
    tell application "System Events"
        set targetGroup to my firstGroupContainingLabel(containerRef, labelText)
        if targetGroup is missing value then error "export_dialog_unrecognized::Missing control for " & labelText
        try
            set popupControl to pop up button 1 of targetGroup
            click popupControl
            delay 0.1
            try
                click menu item itemText of menu 1 of popupControl
            on error
                error "export_dialog_unrecognized::Unable to choose " & itemText & " for " & labelText
            end try
            return
        end try
        try
            set comboControl to combo box 1 of targetGroup
            click comboControl
            keystroke "a" using {command down}
            keystroke itemText
            key code 36
            return
        end try
    end tell
    error "export_dialog_unrecognized::Unable to set " & labelText
end setPopUpByLabel

on setCheckboxByName(containerRef, checkboxName, wantedValue)
    tell application "System Events"
        set checkboxRef to my firstCheckboxNamed(containerRef, checkboxName)
        if checkboxRef is missing value then error "export_dialog_unrecognized::Missing checkbox " & checkboxName
        set currentValue to 0
        try
            set currentValue to (value of checkboxRef as integer)
        end try
        set targetValue to 0
        if wantedValue then set targetValue to 1
        if currentValue is not targetValue then click checkboxRef
    end tell
end setCheckboxByName

on maybeSetCheckboxByName(containerRef, checkboxName, wantedValue)
    try
        my setCheckboxByName(containerRef, checkboxName, wantedValue)
    end try
end maybeSetCheckboxByName
"""


def build_accessibility_check_script() -> str:
    return """
tell application "System Events"
    if UI elements enabled then return "enabled"
end tell
error "accessibility_unavailable::UI scripting is disabled for System Events."
"""


def build_detect_ableton_process_script(process_prefix: str = ABLETON_PROCESS_PREFIX) -> str:
    prefix_literal = _quote_applescript_string(process_prefix)
    return """
set processPrefix to {prefix}
tell application "System Events"
    set matchingProcesses to name of every application process whose background only is false and name begins with processPrefix
    if (count of matchingProcesses) is 0 then error "ableton_not_running::No running Ableton Live process was found."
    return item 1 of matchingProcesses
end tell
""".format(prefix=prefix_literal)


def build_activate_ableton_script(process_name: str) -> str:
    process_literal = _quote_applescript_string(process_name)
    return """
set processName to {process_name}
tell application processName to activate
delay 0.2
tell application "System Events"
    tell application process processName
        set frontmost to true
        if frontmost is false then error "unable_to_activate_ableton::Ableton Live did not become frontmost."
    end tell
end tell
return processName
""".format(process_name=process_literal)


def build_modal_dialog_probe_script(process_name: str) -> str:
    process_literal = _quote_applescript_string(process_name)
    return """
set processName to {process_name}
tell application "System Events"
    tell application process processName
        if (count of windows) is 0 then error "unable_to_activate_ableton::Ableton Live does not have a visible window."
        try
            if exists sheet 1 of window 1 then error "modal_dialog_open::Another modal dialog is already open in Ableton Live."
        end try
    end tell
end tell
return "clear"
""".format(process_name=process_literal)


def build_open_export_dialog_menu_script(
    process_name: str,
    timeout_seconds: float = DEFAULT_EXPORT_DIALOG_TIMEOUT_SECONDS,
) -> str:
    process_literal = _quote_applescript_string(process_name)
    return """
{handlers}
set processName to {process_name}
tell application "System Events"
    tell application process processName
        set frontmost to true
        click menu bar item "File" of menu bar 1
        delay 0.1
        click menu item "Export Audio/Video..." of menu 1 of menu bar item "File" of menu bar 1
    end tell
end tell
my waitForPrimarySheet(processName, {timeout_seconds})
return "menu"
""".format(
        handlers=_common_ui_handlers(),
        process_name=process_literal,
        timeout_seconds=max(1, int(round(timeout_seconds))),
    )


def build_open_export_dialog_shortcut_script(
    process_name: str,
    timeout_seconds: float = DEFAULT_EXPORT_DIALOG_TIMEOUT_SECONDS,
) -> str:
    process_literal = _quote_applescript_string(process_name)
    return """
{handlers}
set processName to {process_name}
tell application "System Events"
    tell application process processName
        set frontmost to true
        keystroke "{key}" using {modifiers}
    end tell
end tell
my waitForPrimarySheet(processName, {timeout_seconds})
return "shortcut"
""".format(
        handlers=_common_ui_handlers(),
        process_name=process_literal,
        key=EXPORT_SHORTCUT_KEY,
        modifiers=EXPORT_SHORTCUT_MODIFIERS,
        timeout_seconds=max(1, int(round(timeout_seconds))),
    )


def build_set_export_dialog_fields_script(
    process_name: str,
    render_source: str,
    sample_rate: str,
    bit_depth: str,
    normalize: bool,
    dither: str,
    timeout_seconds: float = DEFAULT_EXPORT_DIALOG_TIMEOUT_SECONDS,
) -> str:
    process_literal = _quote_applescript_string(process_name)
    render_source_literal = _quote_applescript_string(render_source)
    sample_rate_literal = _quote_applescript_string(sample_rate)
    bit_depth_literal = _quote_applescript_string(bit_depth)
    dither_literal = _quote_applescript_string(dither)
    normalize_literal = "true" if normalize else "false"
    return """
{handlers}
set processName to {process_name}
set exportSheet to my waitForPrimarySheet(processName, {timeout_seconds})
my setPopUpByLabel(exportSheet, "Rendered Track", {render_source})
my setPopUpByLabel(exportSheet, "Sample Rate", {sample_rate})
my setPopUpByLabel(exportSheet, "Bit Depth", {bit_depth})
my setCheckboxByName(exportSheet, "Normalize", {normalize})
my setPopUpByLabel(exportSheet, "Dither Options", {dither})
my maybeSetCheckboxByName(exportSheet, "Encode PCM", true)
tell application "System Events"
    set exportButton to my firstButtonNamed(exportSheet, "Export")
    if exportButton is missing value then error "export_dialog_unrecognized::Export button not found."
    click exportButton
end tell
return "export"
""".format(
        handlers=_common_ui_handlers(),
        process_name=process_literal,
        timeout_seconds=max(1, int(round(timeout_seconds))),
        render_source=render_source_literal,
        sample_rate=sample_rate_literal,
        bit_depth=bit_depth_literal,
        normalize=normalize_literal,
        dither=dither_literal,
    )


def build_save_panel_script(
    process_name: str,
    output_folder: str,
    file_name: str,
    timeout_seconds: float = DEFAULT_SAVE_PANEL_TIMEOUT_SECONDS,
) -> str:
    process_literal = _quote_applescript_string(process_name)
    output_folder_literal = _quote_applescript_string(output_folder)
    file_name_literal = _quote_applescript_string(file_name)
    return """
{handlers}
set processName to {process_name}
set outputFolder to {output_folder}
set exportFileName to {file_name}
set saveSheet to my waitForPrimarySheet(processName, {timeout_seconds})
tell application "System Events"
    tell application process processName
        set frontmost to true
        keystroke "G" using {{command down, shift down}}
    end tell
end tell
set goToFolderSheet to my waitForNestedSheet(processName, 5)
tell application "System Events"
    set folderField to my firstTextEntry(goToFolderSheet)
    if folderField is missing value then error "save_panel_not_found::Go to Folder text field not found."
    click folderField
    keystroke "a" using {{command down}}
    keystroke outputFolder
    key code 36
end tell
delay 0.2
set saveSheet to my waitForPrimarySheet(processName, {timeout_seconds})
tell application "System Events"
    set nameField to my firstTextEntry(saveSheet)
    if nameField is missing value then error "save_panel_not_found::Save name field not found."
    click nameField
    keystroke "a" using {{command down}}
    keystroke exportFileName
    set saveButton to my firstButtonNamed(saveSheet, "Save")
    if saveButton is missing value then error "save_panel_not_found::Save button not found."
    click saveButton
end tell
return "save"
""".format(
        handlers=_common_ui_handlers(),
        process_name=process_literal,
        output_folder=output_folder_literal,
        file_name=file_name_literal,
        timeout_seconds=max(1, int(round(timeout_seconds))),
    )


def build_overwrite_confirmation_script(
    process_name: str,
    timeout_seconds: float = DEFAULT_OVERWRITE_TIMEOUT_SECONDS,
) -> str:
    process_literal = _quote_applescript_string(process_name)
    return """
{handlers}
set processName to {process_name}
tell application "System Events"
    repeat with iteration from 1 to ({timeout_seconds} * 5)
        tell application process processName
            try
                set replaceButton to my firstButtonNamed(window 1, "Replace")
                if replaceButton is not missing value then
                    click replaceButton
                    return "replaced"
                end if
            end try
        end tell
        delay 0.2
    end repeat
end tell
return "not-needed"
""".format(
        handlers=_common_ui_handlers(),
        process_name=process_literal,
        timeout_seconds=max(1, int(round(timeout_seconds))),
    )


def _parse_script_failure(stderr: str, default_code: str) -> Dict[str, Optional[str]]:
    message = (stderr or "").strip()
    match = re.search(r"([a-z_]+)::(.+)", message)
    if match:
        return {
            "failure_code": match.group(1),
            "reason": match.group(2).strip(),
        }
    return {
        "failure_code": default_code,
        "reason": message or default_code,
    }


def run_applescript(script: str, timeout_seconds: float = DEFAULT_OSASCRIPT_TIMEOUT_SECONDS) -> Dict[str, Any]:
    try:
        completed = subprocess.run(
            ["osascript", "-"],
            input=script,
            text=True,
            capture_output=True,
            timeout=max(1.0, float(timeout_seconds)),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "stdout": (exc.stdout or "").strip() if exc.stdout else "",
            "stderr": (exc.stderr or "").strip() if exc.stderr else "",
            "returncode": None,
            "failure_code": "script_timeout",
            "reason": "AppleScript execution timed out.",
        }

    result = {
        "ok": completed.returncode == 0,
        "stdout": (completed.stdout or "").strip(),
        "stderr": (completed.stderr or "").strip(),
        "returncode": completed.returncode,
    }
    if not result["ok"]:
        result.update(_parse_script_failure(result["stderr"], default_code="applescript_failed"))
    return result


def _stage_result(name: str, started_at: float, status: str, **extra: Any) -> Dict[str, Any]:
    payload = {
        "name": name,
        "status": status,
        "duration_seconds": max(0.0, time.monotonic() - started_at),
    }
    payload.update(extra)
    return payload


def check_export_preflight(process_prefix: str = ABLETON_PROCESS_PREFIX) -> Dict[str, Any]:
    preflight: Dict[str, Any] = {
        "ok": False,
        "failure_code": None,
        "reason": None,
        "platform": platform.system(),
        "osascript_path": shutil.which("osascript"),
        "ui_scripting_enabled": False,
        "process_name": None,
        "frontmost": False,
        "modal_dialog_open": False,
    }

    if preflight["platform"] != "Darwin":
        preflight["failure_code"] = "not_macos"
        preflight["reason"] = "macOS export automation requires macOS."
        return preflight

    if not preflight["osascript_path"]:
        preflight["failure_code"] = "osascript_unavailable"
        preflight["reason"] = "osascript is not available on this system."
        return preflight

    accessibility_result = run_applescript(build_accessibility_check_script())
    if not accessibility_result["ok"]:
        preflight["failure_code"] = accessibility_result.get("failure_code", "accessibility_unavailable")
        preflight["reason"] = accessibility_result.get("reason")
        return preflight
    preflight["ui_scripting_enabled"] = True

    process_result = run_applescript(build_detect_ableton_process_script(process_prefix))
    if not process_result["ok"]:
        preflight["failure_code"] = process_result.get("failure_code", "ableton_not_running")
        preflight["reason"] = process_result.get("reason")
        return preflight
    preflight["process_name"] = process_result["stdout"]

    activation_result = run_applescript(build_activate_ableton_script(preflight["process_name"]))
    if not activation_result["ok"]:
        preflight["failure_code"] = activation_result.get("failure_code", "unable_to_activate_ableton")
        preflight["reason"] = activation_result.get("reason")
        return preflight
    preflight["frontmost"] = True

    modal_result = run_applescript(build_modal_dialog_probe_script(preflight["process_name"]))
    if not modal_result["ok"]:
        preflight["failure_code"] = modal_result.get("failure_code", "modal_dialog_open")
        preflight["reason"] = modal_result.get("reason")
        preflight["modal_dialog_open"] = preflight["failure_code"] == "modal_dialog_open"
        return preflight

    preflight["ok"] = True
    return preflight


def run_export_audio_ui(
    output_folder: str,
    file_name: str,
    render_source: str,
    sample_rate: int,
    bit_depth: int,
    normalize: bool,
    dither: str,
    process_prefix: str = ABLETON_PROCESS_PREFIX,
) -> Dict[str, Any]:
    normalized_settings = normalize_export_settings(
        render_source=render_source,
        sample_rate=sample_rate,
        bit_depth=bit_depth,
        normalize=normalize,
        dither=dither,
    )
    normalized_file_name = normalize_export_file_name(file_name)
    requested_file_path = os.path.join(os.path.abspath(os.path.expanduser(output_folder)), normalized_file_name)

    result: Dict[str, Any] = {
        "state": "export-blocked",
        "requested_file_path": requested_file_path,
        "preflight": {},
        "ui_automation": {
            "ok": False,
            "failure_code": None,
            "reason": None,
            "stages": [],
            "process_name": None,
        },
        "reason": None,
    }

    preflight = check_export_preflight(process_prefix=process_prefix)
    result["preflight"] = preflight
    result["ui_automation"]["process_name"] = preflight.get("process_name")
    if not preflight["ok"]:
        result["reason"] = preflight.get("reason")
        result["ui_automation"]["failure_code"] = preflight.get("failure_code")
        result["ui_automation"]["reason"] = preflight.get("reason")
        return result

    process_name = preflight["process_name"]

    menu_started = time.monotonic()
    menu_result = run_applescript(build_open_export_dialog_menu_script(process_name))
    if menu_result["ok"]:
        result["ui_automation"]["stages"].append(
            _stage_result("open_export_dialog", menu_started, "succeeded", method="menu")
        )
    else:
        result["ui_automation"]["stages"].append(
            _stage_result(
                "open_export_dialog",
                menu_started,
                "failed",
                method="menu",
                failure_code=menu_result.get("failure_code"),
                reason=menu_result.get("reason"),
            )
        )
        shortcut_started = time.monotonic()
        shortcut_result = run_applescript(build_open_export_dialog_shortcut_script(process_name))
        if not shortcut_result["ok"]:
            result["ui_automation"]["stages"].append(
                _stage_result(
                    "open_export_dialog",
                    shortcut_started,
                    "failed",
                    method="shortcut",
                    failure_code=shortcut_result.get("failure_code"),
                    reason=shortcut_result.get("reason"),
                )
            )
            result["reason"] = shortcut_result.get("reason")
            result["ui_automation"]["failure_code"] = shortcut_result.get("failure_code")
            result["ui_automation"]["reason"] = shortcut_result.get("reason")
            return result
        result["ui_automation"]["stages"].append(
            _stage_result("open_export_dialog", shortcut_started, "succeeded", method="shortcut")
        )

    fields_started = time.monotonic()
    fields_result = run_applescript(
        build_set_export_dialog_fields_script(
            process_name=process_name,
            render_source=normalized_settings["render_source"],
            sample_rate=normalized_settings["sample_rate"],
            bit_depth=normalized_settings["bit_depth"],
            normalize=normalized_settings["normalize"],
            dither=normalized_settings["dither"],
        ),
        timeout_seconds=DEFAULT_EXPORT_DIALOG_TIMEOUT_SECONDS,
    )
    if not fields_result["ok"]:
        result["ui_automation"]["stages"].append(
            _stage_result(
                "set_export_fields",
                fields_started,
                "failed",
                failure_code=fields_result.get("failure_code"),
                reason=fields_result.get("reason"),
            )
        )
        result["reason"] = fields_result.get("reason")
        result["ui_automation"]["failure_code"] = fields_result.get("failure_code")
        result["ui_automation"]["reason"] = fields_result.get("reason")
        return result
    result["ui_automation"]["stages"].append(
        _stage_result("set_export_fields", fields_started, "succeeded")
    )

    save_started = time.monotonic()
    save_result = run_applescript(
        build_save_panel_script(
            process_name=process_name,
            output_folder=os.path.abspath(os.path.expanduser(output_folder)),
            file_name=normalized_file_name,
        ),
        timeout_seconds=DEFAULT_SAVE_PANEL_TIMEOUT_SECONDS,
    )
    if not save_result["ok"]:
        result["ui_automation"]["stages"].append(
            _stage_result(
                "save_panel",
                save_started,
                "failed",
                failure_code=save_result.get("failure_code"),
                reason=save_result.get("reason"),
            )
        )
        result["reason"] = save_result.get("reason")
        result["ui_automation"]["failure_code"] = save_result.get("failure_code")
        result["ui_automation"]["reason"] = save_result.get("reason")
        return result
    result["ui_automation"]["stages"].append(
        _stage_result("save_panel", save_started, "succeeded")
    )

    overwrite_started = time.monotonic()
    overwrite_result = run_applescript(
        build_overwrite_confirmation_script(process_name),
        timeout_seconds=DEFAULT_OVERWRITE_TIMEOUT_SECONDS,
    )
    if not overwrite_result["ok"]:
        result["ui_automation"]["stages"].append(
            _stage_result(
                "overwrite_confirmation",
                overwrite_started,
                "failed",
                failure_code=overwrite_result.get("failure_code", "overwrite_confirmation_failed"),
                reason=overwrite_result.get("reason"),
            )
        )
        result["reason"] = overwrite_result.get("reason")
        result["ui_automation"]["failure_code"] = overwrite_result.get(
            "failure_code", "overwrite_confirmation_failed"
        )
        result["ui_automation"]["reason"] = overwrite_result.get("reason")
        return result
    result["ui_automation"]["stages"].append(
        _stage_result(
            "overwrite_confirmation",
            overwrite_started,
            "succeeded",
            action=overwrite_result.get("stdout", "not-needed") or "not-needed",
        )
    )

    result["state"] = "export-ready"
    result["ui_automation"]["ok"] = True
    return result

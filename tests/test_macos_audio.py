"""Tests for resolving the macOS user-selected audio output.

Fixture payloads exercise the structured System Profiler parser without
depending on macOS audio hardware during the test suite.
"""

from scripts.resolve_macos_audio import selected_output_name


def test_selected_output_name_returns_default_output_device():
    profile = {
        "SPAudioDataType": [
            {
                "_items": [
                    {"_name": "Headphones", "coreaudio_device_output": 2},
                    {
                        "_name": "DELL S2725QC",
                        "coreaudio_default_audio_output_device": "spaudio_yes",
                    },
                ]
            }
        ]
    }

    assert selected_output_name(profile) == "DELL S2725QC"


def test_selected_output_name_returns_none_without_default():
    assert selected_output_name({"SPAudioDataType": [{"_items": []}]}) is None

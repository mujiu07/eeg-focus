"""v1.7 开发者监测链路自检：真实窗口、时间序号、中间特征与序列化。"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import features, monitor as monitor_data, sources
from app.focus_engine import FocusEngine
from app.xmuse_osc import XmuseOSCSource


def check(name, fn):
    try:
        fn()
        print("PASS " + name)
        return 1
    except Exception as exc:  # noqa: BLE001
        print("FAIL " + name + " — " + str(exc))
        raise


def test_feature_details_match():
    rng = np.random.default_rng(7)
    seg = rng.normal(0, 8, (4, int(256 * 2)))
    feats = features.window_to_features(seg, 256)
    again, details = features.window_to_feature_details(seg, 256)
    assert np.array_equal(feats, again)
    assert set(details["relative"]) == set(features.BAND_NAMES)
    assert details["powers"]["alpha"].shape == (4,)
    # 相对功率分母就是同一窗口 total_power
    rel = details["powers"]["alpha"] / (details["total_power"] + 1e-12)
    assert np.allclose(rel, details["relative"]["alpha"])


def test_engine_debug_is_actual_input():
    rng = np.random.default_rng(11)
    seg = rng.normal(0, 12, (4, int(256 * 2)))
    eng = FocusEngine()
    eng.reset()
    raw, smooth = eng.update(seg, 256)
    dbg = eng.last_debug
    assert dbg and dbg["mode"] == "band"
    assert np.allclose(dbg["processed"], features.prepare_signal(seg, 256))
    powers, total = features.band_power(dbg["processed"], 256)
    assert np.allclose(dbg["powers"]["beta"], powers["beta"])
    assert np.allclose(dbg["total_power"], total)
    assert abs(dbg["raw_focus"] - raw) < 1e-12
    assert abs(dbg["smooth_focus"] - smooth) < 1e-12
    assert 0 < raw < 1
    rows = monitor_data.band_rows(dbg)
    assert len(rows) == 5 and all(r["available"] for r in rows)


def test_batch_serialization_and_units():
    rng = np.random.default_rng(13)
    raw = rng.normal(0, 10, (4, 32))
    proc = raw * 0.5
    meta = {"seq0": 100, "seq1": 131, "t0": 10.0, "t1": 10.12, "n": 32,
            "fs": 256, "time_basis": "device_packet_arrival"}
    b = monitor_data.build_batch(
        seq=3, session_id="abc", source_name="hardware",
        source_desc={"name": "hardware"}, raw=raw, processed=proc,
        sample_meta=meta, artifact={"unit": "uV", "channel_mask": [True, True, False, True]},
        debug={"mode": "band", "powers": {"alpha": np.array([1.0, 2.0])},
               "relative": {"alpha": np.array([0.2, 0.3])}, "ratio": 0.7,
               "raw_focus": 0.4, "smooth_focus": 0.45, "sigmoid": 0.4,
               "band_focus": {"center": 0.7, "slope": 2.5}},
        score=50.0, fused=0.45, baseline=0.55,
        score_range={"low": 0.35, "high": 0.75}, fs=256,
        ch_names=["TP9", "AF7", "AF8", "TP10"], t_offset=10.0,
    )
    assert b["seq"] == 3
    assert b["t0"] == 0.0 and b["t1"] == 0.12
    assert b["unit"] == "µV（幅值推断）" and b["unit_confidence"] == "inferred"
    assert b["channels"][2]["ok"] is False
    assert len(b["raw"]) == 4 and len(b["raw"][0]) == 32
    assert len(b["processed"]) == 4
    assert b["bands"][0]["name"] == "delta"
    assert b["algorithm"]["game_score"] == 50.0
    json.dumps(b, ensure_ascii=False)


def test_no_wave_is_not_fabricated():
    b = monitor_data.build_batch(
        seq=1, session_id="abc", source_name="manual",
        source_desc={"name": "manual"}, raw=None, processed=None,
        sample_meta={}, artifact=None, debug=None, score=None, fused=None,
        baseline=None, score_range={"low": 0.35, "high": 0.75},
        fs=None, ch_names=[], t_offset=0,
    )
    assert b["raw"] is None and b["processed"] is None
    assert b["algorithm"]["available"] is False
    assert all(not x["available"] for x in b["bands"])


def test_osc_sample_metadata_is_recorded_at_emit():
    src = XmuseOSCSource(fs=256, channels=4)
    src._win = 512
    src._step = 128
    src._last_emit = 0.0
    base = 1000.0
    values = []
    for i in range(512):
        values.extend([float(i), 2.0, 3.0, 4.0])
    with src._cond:
        src._push_values(values, base)
    assert len(src._ready_meta) == 1
    m = src._ready_meta[0]
    assert m["n"] == 512
    assert m["seq1"] - m["seq0"] + 1 == 512
    assert m["t0"] <= m["t1"]
    assert abs((m["t1"] - m["t0"]) - 511 / 256) < 1e-6
    assert m["time_basis"] == "device_packet_arrival"


def test_edf_replay_raw_is_source_window():
    src = sources.create_source({"mode": "replay"})
    src.start()
    try:
        seg, meta = src.next_window()
        mon = src.take_monitor_window()
        assert mon is not None
        assert np.array_equal(mon["raw"], seg)
        assert mon["meta"]["n"] == seg.shape[1]
        assert mon["meta"]["time_basis"] == "edf_file"
        assert mon["meta"]["seq1"] - mon["meta"]["seq0"] + 1 == seg.shape[1]
        assert meta["progress"] >= 0
    finally:
        src.stop()


def test_relative_denominator_is_fs_nyquist():
    b = monitor_data.build_batch(
        seq=1, session_id="abc", source_name="hardware",
        source_desc={"name": "hardware"}, raw=np.zeros((4, 8)), processed=None,
        sample_meta={"n": 8, "fs": 256, "t0": 0, "t1": 0.03}, artifact=None,
        debug=None, score=None, fused=None, baseline=None,
        score_range={"low": 0.35, "high": 0.75}, fs=256,
        ch_names=["TP9", "AF7", "AF8", "TP10"], t_offset=0,
    )
    assert b["relative_power"]["denominator"] == "welch_total_power"
    assert b["relative_power"]["range_hz"] == [0.0, 128.0]


def test_nonfinite_samples_are_null_not_zero():
    arr = np.array([[1.0, np.nan, np.inf, -2.0]])
    out = monitor_data.serialise_window(arr)
    assert out[0][0] == 1.0 and out[0][-1] == -2.0
    assert out[0][1] is None and out[0][2] is None


def test_units_are_not_overclaimed():
    assert monitor_data.unit_label("hardware", {"unit": "uV"})[0].startswith("µV")
    assert monitor_data.unit_label("hardware", {"unit": "auto"}) == ("设备原始单位", "unknown")
    assert monitor_data.unit_label("manual", None) == ("未确认", "unknown")
    assert monitor_data.unit_label("replay", None) == ("EDF 物理量", "file")


def main():
    tests = [
        test_feature_details_match,
        test_engine_debug_is_actual_input,
        test_batch_serialization_and_units,
        test_no_wave_is_not_fabricated,
        test_osc_sample_metadata_is_recorded_at_emit,
        test_edf_replay_raw_is_source_window,
        test_relative_denominator_is_fs_nyquist,
        test_nonfinite_samples_are_null_not_zero,
        test_units_are_not_overclaimed,
    ]
    n = 0
    for t in tests:
        n += check(t.__name__, t)
    print(f"\nall {n} monitor checks passed")


if __name__ == "__main__":
    main()

"""CL-E overwrite-slot path: serial run -> read -> archive per member (mocked)."""
import json

import numpy as np
import pytest

from cmp_ensemble.closed_loop import production as prod


def _make_slot(tmp_path):
    slot = tmp_path / "Models" / "51" / "134"
    run = slot / "RESULTS" / "0_1-centroid"
    run.mkdir(parents=True)
    (run / "result.SMSPEC").write_bytes(b"stub-smspec")
    (run / "result.UNSMRY").write_bytes(b"stub-unsmry")
    (run / "model_file_list.txt").write_text("a_SWL.inc\n", encoding="utf-8")
    return slot, run / "result.SMSPEC"


def test_slot_smspec_finds_result(tmp_path):
    slot, smspec = _make_slot(tmp_path)
    assert prod.slot_smspec(slot) == smspec
    with pytest.raises(FileNotFoundError):
        prod.slot_smspec(tmp_path / "Models" / "51" / "999")


def test_archive_member_snapshots_theta_and_result(tmp_path):
    slot, smspec = _make_slot(tmp_path)
    adir = tmp_path / "arch" / "member_0"
    prod.archive_member(adir, 0, {"THICK": 10.0}, {"THICK": 10.0, "PERMX": 6.3},
                        smspec, np.array([1.0, 2.0, 3.0]), iteration=0)
    assert (adir / "theta.json").exists()
    assert (adir / "wf_variables.json").exists()
    assert (adir / "result.SMSPEC").exists()         # copied for reproducibility
    assert (adir / "result.UNSMRY").exists()
    assert (adir / "model_file_list.txt").exists()   # WF include manifest copied
    assert (adir / "d_sim.npy").exists()
    assert json.loads((adir / "theta.json").read_text(encoding="utf-8"))["THICK"] == 10.0
    np.testing.assert_array_equal(np.load(adir / "d_sim.npy"), [1.0, 2.0, 3.0])


def test_overwrite_forward_serial_run_read_archive(tmp_path, monkeypatch):
    slot, smspec = _make_slot(tmp_path)
    # mock the simulator run (no tNavigator) and the summary read
    import tnav_autorun
    runs = []
    monkeypatch.setattr(tnav_autorun, "run_member",
                        lambda project, wf, mid, theta, save=True: runs.append(dict(theta)))
    monkeypatch.setattr(prod, "read_cumulative_dsim",
                        lambda sm, idx, missing="raise": np.array([float(len(runs))] * 2))

    names = ["THICK", "MAJ_R"]
    fwd = prod.build_overwrite_forward(
        project=None, workflow="clust_0_4", theta_names=names,
        snf_root=tmp_path, cum_index=[("m", "w", 0), ("m", "w", 1)],
        slot_rel="Models/51/134", archive_root=tmp_path / "out", archive=True)

    Theta = np.array([[10.0, 3000.0], [12.0, 3200.0], [11.0, 3100.0]])
    D = fwd(Theta)
    assert D.shape == (3, 2)
    assert len(runs) == 3                                # one sim run per member
    assert runs[0]["THICK"] == 10.0
    # per-member archives under iter_0
    for m in range(3):
        adir = tmp_path / "out" / "iter_0" / f"member_{m}"
        assert (adir / "theta.json").exists()
        assert (adir / "result.SMSPEC").exists()
    # second call -> iter_1
    fwd(Theta[:1])
    assert (tmp_path / "out" / "iter_1" / "member_0" / "theta.json").exists()


def test_overwrite_forward_rejects_wrong_width(tmp_path):
    _make_slot(tmp_path)
    fwd = prod.build_overwrite_forward(
        project=None, workflow="w", theta_names=["a", "b"], snf_root=tmp_path,
        cum_index=[("m", "w", 0)], archive_root=None, archive=False)
    with pytest.raises(ValueError):
        fwd(np.zeros((2, 5)))

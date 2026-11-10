import pytest

from streamplify import usbreset


def make_dev(root, name, vid, pid, bus, num):
    d = root / name
    d.mkdir()
    for f, v in (("idVendor", vid), ("idProduct", pid), ("busnum", bus), ("devnum", num)):
        (d / f).write_text(f"{v}\n")


def test_find_device_nodes(tmp_path):
    make_dev(tmp_path, "1-1", "0100", "1000", 1, 2)
    make_dev(tmp_path, "2-1", "0627", "0001", 2, 2)      # some other device
    make_dev(tmp_path, "3-4", "0100", "1000", 3, 17)
    (tmp_path / "1-1:1.0").mkdir()                       # interface dir without ids
    nodes = usbreset.find_device_nodes(sysfs=tmp_path)
    assert [str(n) for n in nodes] == ["/dev/bus/usb/001/002", "/dev/bus/usb/003/017"]


def test_find_device_nodes_missing_sysfs(tmp_path):
    assert usbreset.find_device_nodes(sysfs=tmp_path / "nope") == []


def test_reset_without_permission_gives_helpful_error(tmp_path, monkeypatch):
    def deny(*a, **k):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(usbreset.os, "open", deny)
    with pytest.raises(usbreset.ResetError, match="udev"):
        usbreset.reset(tmp_path / "x")


def test_reset_all_reports_count(monkeypatch, tmp_path):
    monkeypatch.setattr(usbreset, "find_device_nodes", lambda: [tmp_path / "a", tmp_path / "b"])
    calls = []
    monkeypatch.setattr(usbreset, "reset", lambda n: calls.append(n))
    assert usbreset.reset_all(settle_s=0) == 2
    assert len(calls) == 2


def test_reset_all_survives_errors(monkeypatch, tmp_path):
    monkeypatch.setattr(usbreset, "find_device_nodes", lambda: [tmp_path / "a"])
    def boom(n):
        raise usbreset.ResetError("no permission")
    monkeypatch.setattr(usbreset, "reset", boom)
    assert usbreset.reset_all(settle_s=0) == 0

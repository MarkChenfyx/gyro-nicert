from backend.core.paths import PROJECT_ROOT
from data_manager.rqdata_client import _candidate_setting_paths


def test_rqdata_setting_paths_do_not_depend_on_legacy_projects():
    paths = _candidate_setting_paths()

    assert paths
    assert PROJECT_ROOT / ".vntrader" / "vt_setting.json" in paths
    assert all("test1" not in str(path).lower() for path in paths)

"""Tests: the plugin update-check cadence — clock-gated, receipt-surfaced,
apply-explicit. All seams injected; hermetic."""

from __future__ import annotations

import time

import pytest

import hermes_cli.plugins_cadence as cad


@pytest.fixture
def homed(tmp_path, monkeypatch):
    """Cadence state (markers) inside a temp hermes home."""
    import hermes_constants

    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)
    return tmp_path


class _Result:
    def __init__(self, name, klass="git", update_available=None, needs_fixing=None):
        self.name = name
        self.klass = klass
        self.update_available = update_available
        self.needs_fixing = needs_fixing

    def to_json(self):
        return {"name": self.name, "class": self.klass}





def test_clock_gate_due_when_never_run(homed):
    assert cad.check_due(now=1000.0, interval_hours=24) is True


def test_clock_gate_not_due_within_interval(homed, monkeypatch):
    marker = homed / "plugin-update-checks"
    marker.mkdir()
    (marker / "last-run").write_text("x", encoding="utf-8")
    # fresh mtime
    recent = time.time() - 100
    import os

    os.utime(marker / "last-run", (recent, recent))
    assert cad.check_due(now=time.time(), interval_hours=24) is False


def test_zero_interval_disables(homed):
    assert cad.check_due(now=time.time(), interval_hours=0) is False


def test_interval_reads_config(homed):
    assert cad.check_interval_hours(lambda s, k: None) == 24
    assert cad.check_interval_hours(lambda s, k: 6) == 6.0
    assert cad.check_interval_hours(lambda s, k: 0) == 0.0
    assert cad.check_interval_hours(lambda s, k: "garbage") == 24


def test_run_writes_receipt_and_marker(homed):
    import pm.receipt as receipts
    calls = []
    def checks(directory):
        calls.append(directory)
        return [_Result("plug", update_available=True)]
    result = cad.run_scheduled_check(run_checks_fn=checks, plugins_dir=homed / "plugins")
    assert result[0].name == "plug"
    assert receipts.latest()["outcome"] == "updates-available"
    assert cad.run_scheduled_check(run_checks_fn=checks, plugins_dir=homed / "plugins") is None
    assert len(calls) == 1


@pytest.mark.parametrize('enabled', [False, True])
def test_auto_apply_selects_only_updateable_git_and_persists_receipt(homed, enabled, caplog):
    from pm import receipt
    applied = []
    rows = [_Result('gitplug', update_available=True),
            _Result('pipplug', klass='pip', update_available=True),
            _Result('broken', needs_fixing='mismatch')]
    cad.run_scheduled_check(run_checks_fn=lambda _: rows, plugins_dir=homed / 'plugins',
                            apply_updates_fn=applied.append,
                            config_get=lambda section, key: enabled if key == 'auto_apply' else 24)
    assert applied == (['gitplug'] if enabled else [])
    assert receipt.latest()['outcome'] == 'updates-available'
    assert 'broken' in caplog.text and 'trust-update-url' in caplog.text


@pytest.mark.parametrize('failed', [False, True])
def test_housekeeping_runs_real_cadence_and_backs_off(homed, monkeypatch, caplog, failed):
    import gateway.run as gateway
    from hermes_cli import plugins_updates, plugins_cmd
    from pm import receipt

    calls, applied = [], []
    def checks(directory):
        calls.append(directory)
        if failed:
            raise OSError('offline')
        return [_Result('plug', update_available=True)]
    monkeypatch.setattr(plugins_updates, 'run_checks', checks)
    monkeypatch.setattr(plugins_cmd, '_plugins_dir', lambda: homed / 'plugins')
    monkeypatch.setattr(plugins_cmd, 'cmd_update', lambda name, **kwargs: applied.append((name, kwargs)))
    monkeypatch.setattr(cad, 'auto_apply_enabled', lambda *_: True)
    for _ in range(2):
        gateway._housekeeping_chore('Plugin update check', gateway._housekeeping_plugin_update_check)
    assert calls == [homed / 'plugins']
    assert applied == ([] if failed else [('plug', {'interactive': False})])
    saved = receipt.latest()
    assert saved['outcome'] == ('failed' if failed else 'updates-available')
    assert saved['exit_code'] == int(failed)
    assert (homed / 'plugin-update-checks/last-run').is_file()
    if failed:
        assert saved['warnings'][0]['message'] in caplog.text


@pytest.mark.parametrize('value,expected', [
    (None, False), (False, False), (True, True),
    ('false', False), ('no', False), ('off', False),
    ('true', False), (1, False), (0, False), ('', False),
    ([], False), ({}, False),
])
def test_automatic_plugin_updates_require_literal_boolean_consent(value, expected):
    """Regression: quoted YAML false must never opt into unattended code updates."""
    assert cad.auto_apply_enabled(
        lambda section, key: value if (section, key) == ('plugins', 'auto_apply') else None
    ) is expected


@pytest.mark.parametrize('yaml_scalar,expected', [
    ('true', True), ('false', False), ('"false"', False),
    ('"no"', False), ('"true"', False), ('1', False),
])
def test_auto_apply_yaml_type_confusion_fails_closed(yaml_scalar, expected):
    """Actual YAML parser + cfg_get path must preserve boolean-only consent."""
    import hermes_yaml as yaml
    from hermes_cli.config import cfg_get

    parsed = yaml.safe_load('plugins:\n  auto_apply: ' + yaml_scalar + '\n')
    assert cad.auto_apply_enabled(lambda section, key: cfg_get(parsed, section, key)) is expected


def test_auto_apply_quoted_false_preserves_update_notice_without_applying(homed):
    """A due check can show pending updates; quoted false cannot execute them."""
    from pm import receipt

    applied = []
    rows = [_Result('synthetic-git', update_available=True)]
    result = cad.run_scheduled_check(
        run_checks_fn=lambda _: rows,
        plugins_dir=homed / 'plugins',
        apply_updates_fn=applied.append,
        config_get=lambda section, key: 'false' if (section,key) == ('plugins','auto_apply') else 24,
    )
    assert result == rows
    assert applied == []
    assert receipt.latest()['outcome'] == 'updates-available'


@pytest.mark.parametrize('yaml_scalar,expected', [
    ('True', True), ('TRUE', True), ('yes', True), ('on', True),
    ('"True"', False), ('[true]', False), ('{enabled: true}', False),
])
def test_auto_apply_parser_aliases_require_parsed_boolean(yaml_scalar, expected):
    """YAML aliases map to bool, but string/numeric/container values do not opt in."""
    import hermes_yaml as yaml
    from hermes_cli.config import cfg_get

    config = yaml.safe_load('plugins:\n  auto_apply: ' + yaml_scalar + '\n')
    assert cad.auto_apply_enabled(lambda section, key: cfg_get(config, section, key)) is expected


def test_profile_scoped_auto_apply_with_real_config_and_concurrency(tmp_path):
    """Two profiles must not share consent or synthetic apply callbacks."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from hermes_constants import set_hermes_home_override, reset_hermes_home_override

    profiles = []
    for suffix, scalar, expected in (
        ('allow', 'true', True),
        ('deny', '"false"', False),
    ):
        home = tmp_path / suffix
        home.mkdir()
        (home / 'config.yaml').write_text(
            f'plugins:\n  auto_apply: {scalar}\n', encoding='utf-8',
        )
        profiles.append((home, expected))

    # Exercise real config, receipt and cadence boundaries with an in-memory
    # apply recorder; there are no network requests or plugin installations.
    for home, expected in profiles:
        token = set_hermes_home_override(home)
        try:
            applied = []
            rows = [_Result('synthetic-git', update_available=True)]
            got = cad.run_scheduled_check(
                run_checks_fn=lambda _: rows,
                plugins_dir=home / 'plugins',
                apply_updates_fn=applied.append,
            )
            assert got == rows
            assert applied == (['synthetic-git'] if expected else [])
            assert (home / 'plugin-update-checks' / 'last-run').is_file()
        finally:
            reset_hermes_home_override(token)

    # Overlap context-scoped profile reads to catch accidental global-home use.
    for iteration in range(40):
        barrier = Barrier(2)

        def check_profile(home, expected):
            token = set_hermes_home_override(home)
            try:
                barrier.wait(timeout=5)
                return cad.auto_apply_enabled() is expected
            finally:
                reset_hermes_home_override(token)

        with ThreadPoolExecutor(max_workers=2) as pool:
            checks = [pool.submit(check_profile, home, expected)
                      for home, expected in profiles]
            assert all(f.result(timeout=8) for f in checks), iteration

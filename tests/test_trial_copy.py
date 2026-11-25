from core import config, dispatch_sync, mailer


def test_trial_copy_blocks_mail_and_sync(monkeypatch):
    monkeypatch.setattr(config, "_secrets", lambda: {"trial_copy": True})
    assert config.trial_copy()
    sent, why = mailer.deliver(None)
    assert not sent and "trial" in why
    assert dispatch_sync.sync() == "skipped: trial copy"


def test_live_by_default(monkeypatch):
    monkeypatch.setattr(config, "_secrets", lambda: {})
    assert not config.trial_copy()

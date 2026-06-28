from agent2chat.slack_setup import build_manifest


def test_manifest_includes_name():
    m = build_manifest("My Bot")
    assert 'name: "My Bot"' in m
    assert 'display_name: "My Bot"' in m


def test_manifest_has_required_socket_mode_bits():
    m = build_manifest("X")
    assert "socket_mode_enabled: true" in m
    for scope in ("chat:write", "app_mentions:read", "im:history"):
        assert scope in m
    for event in ("app_mention", "message.im"):
        assert event in m


def test_manifest_escapes_quotes_in_name():
    m = build_manifest('Weird "quoted" name')
    assert 'name: "Weird \\"quoted\\" name"' in m

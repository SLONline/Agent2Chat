import sys

from agent2chat import service


def test_systemd_unit_has_exec_and_restart():
    unit = service._systemd_unit()
    assert "ExecStart=" in unit
    assert "-m agent2chat run" in unit
    assert "Restart=always" in unit
    assert "WantedBy=default.target" in unit


def test_launchd_plist_well_formed():
    plist = service._launchd_plist()
    assert "com.slonline.agent2chat" in plist
    assert "<key>KeepAlive</key>" in plist
    assert "agent2chat" in plist


def test_print_instructions_emits_unit_to_stdout(capsys):
    rc = service.print_instructions()
    assert rc == 0
    out, err = capsys.readouterr()
    # The unit/plist goes to stdout (redirectable to a file); guidance to stderr.
    if sys.platform == "darwin":
        assert "<plist" in out
    else:
        assert "[Service]" in out
    assert "#" in err            # instructions are commented and on stderr

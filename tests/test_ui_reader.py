"""The tray's lightweight state-file polling."""

from types import SimpleNamespace

from poketokenbar.ui.reader import StateReader


class ChangingFile:
    def __init__(self, raw: str) -> None:
        self.raw = raw
        self.version = 1
        self.reads = 0

    def stat(self):
        return SimpleNamespace(
            st_mtime_ns=self.version,
            st_size=len(self.raw),
            st_ino=self.version,
        )

    def read_text(self, encoding="utf-8") -> str:
        self.reads += 1
        return self.raw


def test_unchanged_state_is_not_read_and_parsed_again():
    source = ChangingFile('{"updated_at": 1}')
    reader = StateReader(path=source)

    assert reader.read() == {"updated_at": 1}
    assert reader.read() == {"updated_at": 1}
    assert source.reads == 1

    source.raw = '{"updated_at": 2}'
    source.version += 1
    assert reader.read() == {"updated_at": 2}
    assert source.reads == 2


def test_broken_state_is_retried_until_the_error_can_be_reported():
    source = ChangingFile("{")
    reader = StateReader(path=source)

    reader.read()
    reader.read()
    reader.read()

    assert source.reads == 3
    assert reader.error == "state.json is not valid JSON"

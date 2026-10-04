from types import SimpleNamespace
from poketokenbar import l10n
from poketokenbar.notify import Notifier


def test_korean_runtime_names_choose_particles():
    assert l10n.format_text("%1이(가) %2(으)로 진화했어요", "피카츄", "알") == "피카츄가 알로 진화했어요"
    assert l10n.format_text("%1을(를)", "잠만보") == "잠만보를"
    assert l10n.format_text("%1이(가)", "안농 [A]") == "안농 [A]이(가)"


def test_shiny_notification_uses_actual_charm_odds():
    sent = []
    notifier = Notifier(send_fn=lambda *args, **kwargs: sent.append(args))
    events = SimpleNamespace(hatched=1, evolved_to=None, graduated=None, ditto_revealed=False)
    notifier.companion(events, "Pikachu", "en", shiny=True, shiny_denominator=16)
    assert "16" in sent[0][1]
    assert "64" not in sent[0][1]

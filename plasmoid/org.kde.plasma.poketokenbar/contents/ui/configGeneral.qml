import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM
import org.kde.plasma.plasma5support as Plasma5Support

// SimpleKCM, not a bare FormLayout: Plasma's config dialog does not scroll a
// plain layout, so everything past the fold (pet size, backup) was unreachable.
KCM.SimpleKCM {
    id: page

    // Plasma injects a cfg_<key>Default for every cfg_<key> alias, plus a
    // `title`. Without them the whole page fails to construct and the settings
    // dialog comes up empty — which is exactly what happened.
    property alias cfg_showTokens: showTokens.checked
    property bool cfg_showTokensDefault: false
    property alias cfg_showCost: showCost.checked
    property bool cfg_showCostDefault: false
    property string title: ""

    property var settings: ({})

    function push(key, value) {
        var text = (typeof value === "boolean") ? (value ? "true" : "false") : String(value);
        runner.run("poketokenctl set " + key + " " + text);
    }

    // Read current values so the controls open showing reality rather than
    // Plasma's separate copy of the defaults.
    function reload() {
        runner.read("cat $HOME/.config/poketokenbar/config.json");
    }

    Component.onCompleted: reload()

    Plasma5Support.DataSource {
        id: runner
        engine: "executable"
        connectedSources: []

        property string pending: ""

        onNewData: function(sourceName, data) {
            disconnectSource(sourceName);
            if (sourceName === pending && data["exit code"] === 0) {
                try {
                    page.settings = JSON.parse(data["stdout"]);
                    page.applySettings();
                } catch (e) {
                    // No config yet: the daemon writes one on first change.
                }
            }
        }

        function run(cmd) { connectSource(cmd); }
        function read(cmd) { pending = cmd; connectSource(cmd); }
    }

    function applySettings() {
        var s = page.settings;
        if (s.refresh_interval !== undefined)
            refreshInterval.value = s.refresh_interval;
        if (s.warn_threshold !== undefined)
            warnThreshold.value = s.warn_threshold;
        if (s.crit_threshold !== undefined)
            critThreshold.value = s.crit_threshold;
        if (s.show_tokens_in_menu !== undefined)
            showTokens.checked = s.show_tokens_in_menu;
        if (s.show_cost_in_menu !== undefined)
            showCost.checked = s.show_cost_in_menu;
        if (s.show_limit_in_menu !== undefined)
            showLimit.checked = s.show_limit_in_menu;
        if (s.limit_display_mode !== undefined)
            limitMode.currentIndex = limitMode.keys.indexOf(s.limit_display_mode);
        if (s.limit_notifications !== undefined)
            limitAlerts.checked = s.limit_notifications;
        if (s.companion_notifications !== undefined)
            companionAlerts.checked = s.companion_notifications;
        if (s.status_checks_enabled !== undefined)
            statusChecks.checked = s.status_checks_enabled;
        if (s.floating_pet_enabled !== undefined)
            floatingPet.checked = s.floating_pet_enabled;
        if (s.floating_pet_size !== undefined)
            petSize.value = s.floating_pet_size;
        if (s.growth_difficulty !== undefined)
            growthDifficulty.value = Math.round(s.growth_difficulty * 100);
        if (s.shop_difficulty !== undefined)
            shopDifficulty.value = Math.round(s.shop_difficulty * 100);
        if (s.floating_pet_bubble_alerts !== undefined)
            petBubbles.checked = s.floating_pet_bubble_alerts;
        if (s.language !== undefined)
            language.currentIndex = language.keys.indexOf(s.language);
    }

    Kirigami.FormLayout {

    // ---------------- General ----------------

    Item { Kirigami.FormData.isSection: true; Kirigami.FormData.label: i18n("General") }

    QQC2.ComboBox {
        id: language
        Kirigami.FormData.label: i18n("Language:")
        readonly property var keys: ["en", "ko", "ja", "es"]
        model: ["English", "한국어", "日本語", "Español"]
        onActivated: page.push("language", keys[currentIndex])
    }

    QQC2.SpinBox {
        id: refreshInterval
        Kirigami.FormData.label: i18n("Refresh interval (s):")
        from: 30
        to: 3600
        stepSize: 30
        value: 120
        onValueModified: page.push("refresh_interval", value)
    }

    QQC2.ComboBox {
        id: limitMode
        Kirigami.FormData.label: i18n("Limit display:")
        readonly property var keys: ["both", "session", "weekly"]
        model: [i18n("Both"), i18n("5-hour only"), i18n("Weekly only")]
        onActivated: page.push("limit_display_mode", keys[currentIndex])
    }

    // ---------------- Difficulty ----------------

    Item { Kirigami.FormData.isSection: true; Kirigami.FormData.label: i18n("Difficulty") }

    RowLayout {
        Kirigami.FormData.label: i18n("Growth:")
        QQC2.Slider {
            id: growthDifficulty
            from: 10; to: 200; stepSize: 10; value: 100
            Layout.preferredWidth: Kirigami.Units.gridUnit * 10
            onMoved: page.push("growth_difficulty", value / 100)
        }
        QQC2.Label { text: Math.round(growthDifficulty.value) + "%" }
    }

    RowLayout {
        Kirigami.FormData.label: i18n("Shop prices:")
        QQC2.Slider {
            id: shopDifficulty
            from: 10; to: 200; stepSize: 10; value: 100
            Layout.preferredWidth: Kirigami.Units.gridUnit * 10
            onMoved: page.push("shop_difficulty", value / 100)
        }
        QQC2.Label { text: Math.round(shopDifficulty.value) + "%" }
    }

    // ---------------- Panel ----------------

    Item { Kirigami.FormData.isSection: true; Kirigami.FormData.label: i18n("Show in panel") }

    QQC2.CheckBox {
        id: showTokens
        Kirigami.FormData.label: i18n("Today's tokens:")
        onToggled: page.push("show_tokens_in_menu", checked)
    }

    QQC2.CheckBox {
        id: showCost
        Kirigami.FormData.label: i18n("Today's cost:")
        onToggled: page.push("show_cost_in_menu", checked)
    }

    QQC2.CheckBox {
        id: showLimit
        Kirigami.FormData.label: i18n("Limit %:")
        onToggled: page.push("show_limit_in_menu", checked)
    }

    QQC2.Label {
        text: i18n("All off shows only the character")
        opacity: 0.7
    }

    // ---------------- Notifications ----------------

    Item { Kirigami.FormData.isSection: true; Kirigami.FormData.label: i18n("Notifications") }

    QQC2.CheckBox {
        id: limitAlerts
        Kirigami.FormData.label: i18n("Limit alerts:")
        onToggled: page.push("limit_notifications", checked)
    }

    RowLayout {
        Kirigami.FormData.label: i18n("Warning:")
        QQC2.Slider {
            id: warnThreshold
            from: 50; to: 99; stepSize: 1; value: 80
            Layout.preferredWidth: Kirigami.Units.gridUnit * 10
            onMoved: page.push("warn_threshold", Math.round(value))
        }
        QQC2.Label { text: Math.round(warnThreshold.value) + "%" }
    }

    RowLayout {
        Kirigami.FormData.label: i18n("Critical:")
        QQC2.Slider {
            id: critThreshold
            from: 60; to: 100; stepSize: 1; value: 95
            Layout.preferredWidth: Kirigami.Units.gridUnit * 10
            onMoved: page.push("crit_threshold", Math.round(value))
        }
        QQC2.Label { text: Math.round(critThreshold.value) + "%" }
    }

    QQC2.CheckBox {
        id: companionAlerts
        Kirigami.FormData.label: i18n("Companion events:")
        text: i18n("hatch / evolve / graduate")
        onToggled: page.push("companion_notifications", checked)
    }

    QQC2.CheckBox {
        id: statusChecks
        Kirigami.FormData.label: i18n("Provider status:")
        text: i18n("show Claude / OpenAI incidents")
        onToggled: page.push("status_checks_enabled", checked)
    }

    // ---------------- Floating pet ----------------

    Item { Kirigami.FormData.isSection: true; Kirigami.FormData.label: i18n("Floating pet") }

    QQC2.CheckBox {
        id: floatingPet
        Kirigami.FormData.label: i18n("Show floating pet:")
        text: i18n("add the desktop widget separately")
        onToggled: page.push("floating_pet_enabled", checked)
    }

    RowLayout {
        Kirigami.FormData.label: i18n("Size:")
        QQC2.Slider {
            id: petSize
            from: 48; to: 192; stepSize: 8; value: 96
            Layout.preferredWidth: Kirigami.Units.gridUnit * 10
            onMoved: page.push("floating_pet_size", Math.round(value))
        }
        QQC2.Label { text: Math.round(petSize.value) + "px" }
    }

    QQC2.CheckBox {
        id: petBubbles
        Kirigami.FormData.label: i18n("Speech bubbles:")
        onToggled: page.push("floating_pet_bubble_alerts", checked)
    }

    // ---------------- Backup ----------------

    Item { Kirigami.FormData.isSection: true; Kirigami.FormData.label: i18n("Backup & transfer") }

    RowLayout {
        Kirigami.FormData.label: i18n("Save file:")

        QQC2.Button {
            text: i18n("Export…")
            onClicked: page.push_export()
        }

        QQC2.Button {
            text: i18n("Import…")
            onClicked: page.push_import()
        }
    }

    QQC2.Label {
        text: i18n("Exports to ~/poketokenbar-save.json — Pokédex, tokens, bag, and companion")
        opacity: 0.7
        wrapMode: Text.Wrap
    }

    }

    function push_export() {
        runner.run("poketokenctl export $HOME/poketokenbar-save.json");
    }

    function push_import() {
        runner.run("poketokenctl import $HOME/poketokenbar-save.json");
    }
}

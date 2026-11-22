import QtQuick

// A spring-centred two-axis stick. Deflection comes from dragging the knob
// and/or from the keyboard (keyX / keyY, set by the parent).
Item {
    id: root

    property string title
    property string upLabel
    property string downLabel
    property string leftLabel
    property string rightLabel

    property real keyX: 0
    property real keyY: 0
    property real dragX: 0
    property real dragY: 0

    readonly property real xValue: Math.max(-1, Math.min(1, dragX + keyX))
    readonly property real yValue: Math.max(-1, Math.min(1, dragY + keyY))

    readonly property color muted: "#8b93a1"

    implicitWidth: 300
    implicitHeight: 340

    Text {
        id: titleText
        anchors.horizontalCenter: parent.horizontalCenter
        text: root.title
        color: "#e6e9ef"
        font.pixelSize: 15
        font.weight: Font.DemiBold
    }

    Text {
        anchors.horizontalCenter: pad.horizontalCenter
        anchors.bottom: pad.top
        anchors.bottomMargin: 4
        text: root.upLabel
        color: root.muted
        font.pixelSize: 12
    }
    Text {
        anchors.horizontalCenter: pad.horizontalCenter
        anchors.top: pad.bottom
        anchors.topMargin: 4
        text: root.downLabel
        color: root.muted
        font.pixelSize: 12
    }
    Text {
        anchors.verticalCenter: pad.verticalCenter
        anchors.right: pad.left
        anchors.rightMargin: 6
        text: root.leftLabel
        color: root.muted
        font.pixelSize: 12
    }
    Text {
        anchors.verticalCenter: pad.verticalCenter
        anchors.left: pad.right
        anchors.leftMargin: 6
        text: root.rightLabel
        color: root.muted
        font.pixelSize: 12
    }

    Rectangle {
        id: pad

        readonly property real travel: (width - knob.width) / 2

        width: Math.min(root.width - 110, root.height - 80)
        height: width
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: titleText.bottom
        anchors.topMargin: 26
        radius: 18
        color: "#1b2028"
        border.color: "#2c3440"
        border.width: 1

        Rectangle {
            anchors.centerIn: parent
            width: parent.width - 24
            height: 1
            color: "#2c3440"
        }
        Rectangle {
            anchors.centerIn: parent
            width: 1
            height: parent.height - 24
            color: "#2c3440"
        }

        Rectangle {
            id: knob
            width: 56
            height: 56
            radius: 28
            x: pad.width / 2 - width / 2 + root.xValue * pad.travel
            y: pad.height / 2 - height / 2 - root.yValue * pad.travel
            color: area.pressed ? "#4cc2ff" : "#2f8fd0"
            border.color: "#9bdcff"
            border.width: 1
        }

        MouseArea {
            id: area
            anchors.fill: parent

            function track(mouse) {
                root.dragX = Math.max(-1, Math.min(1, (mouse.x - pad.width / 2) / pad.travel));
                root.dragY = Math.max(-1, Math.min(1, (pad.height / 2 - mouse.y) / pad.travel));
            }

            onPressed: mouse => track(mouse)
            onPositionChanged: mouse => track(mouse)
            onReleased: {
                root.dragX = 0;
                root.dragY = 0;
            }
            onCanceled: {
                root.dragX = 0;
                root.dragY = 0;
            }
        }
    }
}

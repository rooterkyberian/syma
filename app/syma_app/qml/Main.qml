import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import SymaApp

ApplicationWindow {
    id: window

    width: 1200
    height: 680
    minimumWidth: 1040
    minimumHeight: 620
    visible: true
    title: "Syma X22W"

    palette {
        window: "#12151a"
        windowText: "#e6e9ef"
        base: "#1b2028"
        alternateBase: "#232a34"
        text: "#e6e9ef"
        placeholderText: "#8b93a1"
        button: "#2a323e"
        buttonText: "#e6e9ef"
        highlight: "#2f8fd0"
        highlightedText: "#ffffff"
        light: "#3a4350"
        mid: "#3a4350"
        dark: "#0c0e12"
        disabled {
            text: "#6b7380"
            buttonText: "#6b7380"
            windowText: "#6b7380"
        }
    }

    readonly property color muted: "#8b93a1"
    property var heldKeys: ({})

    function held(key) {
        return heldKeys[key] === true ? 1 : 0;
    }

    function updateKeyAxes() {
        const rate = keyRate.value;
        leftStick.keyY = rate * (held(Qt.Key_W) - held(Qt.Key_S));
        leftStick.keyX = rate * (held(Qt.Key_D) - held(Qt.Key_A));
        rightStick.keyY = rate * (held(Qt.Key_Up) - held(Qt.Key_Down));
        rightStick.keyX = rate * (held(Qt.Key_Right) - held(Qt.Key_Left));
    }

    function pushSticks() {
        drone.setSticks(leftStick.yValue, leftStick.xValue, rightStick.yValue, rightStick.xValue);
    }

    function releaseKeys() {
        heldKeys = ({});
        updateKeyAxes();
    }

    // Sticks must not stay deflected when the window stops receiving key releases.
    onActiveChanged: if (!active) releaseKeys()

    Connections {
        target: drone
        function onInterfacesChanged() {
            interfaceBox.currentIndex = drone.preferredIndex;
        }
    }

    Item {
        id: keys
        anchors.fill: parent
        focus: true

        Keys.onPressed: event => {
            if (event.isAutoRepeat)
                return;
            switch (event.key) {
            case Qt.Key_Space:
            case Qt.Key_Escape:
                drone.emergencyStop();
                break;
            case Qt.Key_T:
                drone.takeoff();
                break;
            case Qt.Key_L:
                drone.land();
                break;
            case Qt.Key_C:
                drone.calibrate();
                break;
            default:
                window.heldKeys[event.key] = true;
                window.updateKeyAxes();
            }
        }
        Keys.onReleased: event => {
            if (event.isAutoRepeat)
                return;
            delete window.heldKeys[event.key];
            window.updateKeyAxes();
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 20
            spacing: 16

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                Label {
                    text: "Interface"
                    color: window.muted
                }
                ComboBox {
                    id: interfaceBox
                    Layout.fillWidth: true
                    Layout.maximumWidth: 420
                    focusPolicy: Qt.NoFocus
                    enabled: !drone.connected && !drone.busy
                    model: drone.interfaces
                    textRole: "label"
                    valueRole: "name"
                }
                Button {
                    text: "Refresh"
                    Layout.minimumWidth: implicitWidth
                    horizontalPadding: 14
                    focusPolicy: Qt.NoFocus
                    enabled: !drone.busy
                    onClicked: drone.refreshInterfaces()
                }
                Item {
                    Layout.fillWidth: true
                }
                Button {
                    text: drone.connected ? "Disconnect" : drone.busy ? "Cancel" : "Connect"
                    Layout.minimumWidth: implicitWidth
                    horizontalPadding: 14
                    focusPolicy: Qt.NoFocus
                    highlighted: !drone.connected && !drone.busy
                    enabled: interfaceBox.currentIndex >= 0
                    onClicked: drone.connected || drone.busy ? drone.disconnectDrone()
                                                             : drone.connectDrone(interfaceBox.currentValue)
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Rectangle {
                    width: 10
                    height: 10
                    radius: 5
                    color: drone.connected ? "#3dd68c" : "#6b7380"
                }
                Label {
                    Layout.fillWidth: true
                    text: drone.status
                    elide: Text.ElideRight
                }
                Rectangle {
                    visible: drone.connected
                    width: 10
                    height: 10
                    radius: 5
                    color: drone.reachable ? "#3dd68c" : "#e5484d"
                }
                Label {
                    visible: drone.connected
                    text: drone.reachable ? "drone is on the network"
                                          : "drone is not answering on this interface"
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 12

                Stick {
                    id: leftStick
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    title: "Throttle / Rudder  (W A S D)"
                    upLabel: "up"
                    downLabel: "down"
                    leftLabel: "turn left"
                    rightLabel: "turn right"
                    onXValueChanged: window.pushSticks()
                    onYValueChanged: window.pushSticks()
                }

                ColumnLayout {
                    Layout.fillHeight: true
                    Layout.preferredWidth: 420
                    Layout.maximumWidth: 420
                    spacing: 10

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.minimumHeight: 200
                        radius: 8
                        color: "#0c0e12"
                        border.color: "#2c3440"
                        border.width: 1
                        clip: true

                        VideoView {
                            id: video
                            anchors.fill: parent
                            anchors.margins: 1
                            source: drone
                        }
                        Label {
                            anchors.centerIn: parent
                            visible: !video.hasFrame
                            text: drone.connected ? "Waiting for video…" : "Camera offline"
                            color: window.muted
                        }
                        Rectangle {
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            anchors.margins: 8
                            visible: video.hasFrame
                            width: fpsLabel.implicitWidth + 12
                            height: fpsLabel.implicitHeight + 6
                            radius: 4
                            color: "#c00c0e12"

                            Label {
                                id: fpsLabel
                                anchors.centerIn: parent
                                text: drone.videoFps > 0 ? drone.videoFps + " fps" : "video stalled"
                                color: drone.videoFps > 0 ? "#e6e9ef" : "#ff6b70"
                                font.pixelSize: 12
                            }
                        }
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: 2
                        columnSpacing: 10
                        rowSpacing: 10
                        uniformCellWidths: true

                        Button {
                            Layout.fillWidth: true
                            text: "Take off  (T)"
                            focusPolicy: Qt.NoFocus
                            enabled: drone.connected
                            onClicked: drone.takeoff()
                        }
                        Button {
                            Layout.fillWidth: true
                            text: "Land  (L)"
                            focusPolicy: Qt.NoFocus
                            enabled: drone.connected
                            onClicked: drone.land()
                        }
                        Button {
                            Layout.fillWidth: true
                            Layout.columnSpan: 2
                            text: "Calibrate  (C)"
                            focusPolicy: Qt.NoFocus
                            enabled: drone.connected
                            onClicked: drone.calibrate()
                        }
                    }

                    Button {
                        id: stopButton
                        Layout.fillWidth: true
                        Layout.preferredHeight: 56
                        focusPolicy: Qt.NoFocus
                        enabled: drone.connected
                        onClicked: drone.emergencyStop()

                        contentItem: Text {
                            text: "STOP  (Space / Esc)"
                            color: stopButton.enabled ? "#ffffff" : "#8b93a1"
                            font.weight: Font.Bold
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        background: Rectangle {
                            radius: 8
                            color: !stopButton.enabled ? "#3a2a2c" : stopButton.down ? "#b3363a" : "#e5484d"
                        }
                    }
                }

                Stick {
                    id: rightStick
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    title: "Elevator / Aileron  (arrow keys)"
                    upLabel: "forward"
                    downLabel: "back"
                    leftLabel: "left"
                    rightLabel: "right"
                    onXValueChanged: window.pushSticks()
                    onYValueChanged: window.pushSticks()
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                Label {
                    text: "Keyboard deflection"
                    color: window.muted
                }
                Slider {
                    id: keyRate
                    Layout.preferredWidth: 180
                    focusPolicy: Qt.NoFocus
                    from: 0.1
                    to: 1.0
                    value: 0.5
                    onValueChanged: window.updateKeyAxes()
                }
                Label {
                    text: Math.round(keyRate.value * 100) + "%"
                    Layout.preferredWidth: 40
                }
                Item {
                    Layout.fillWidth: true
                }
                Label {
                    text: "payload"
                    color: window.muted
                }
                Label {
                    text: drone.packet
                    font.family: "monospace"
                }
            }
        }
    }
}

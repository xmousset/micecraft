import sys
import traceback

from PyQt6.QtWidgets import QApplication

from micecraft.devices.gate.Gate import Gate, GateOrder
from micecraft.devices.waterpump.WaterPump import WaterPump
from micecraft.devices.touchscreen.TouchScreen import TouchScreen

from micecraft.soft.camera_recorder.CameraRecorder import CameraRecorder
from micecraft.devices.roomSensor.RoomSensorDigest import RoomSensorDigest
from micecraft.examples.experiments.visualdiscrimination.experiment import (
    Criteria,
    Phase,
    Room,
    TSImage,
    VisualDiscriminationExperiment,
)
from micecraft.examples.experiments.visualdiscrimination.interface import (
    excepthook,
    VisualDiscriminationInterface,
)


# ================ EXPERIMENT PARAMETERS ================
def get_experiment_parameters():

    # Images
    # ----------------
    images_to_attribute = [TSImage.PLANE, TSImage.FLOWER]

    # Phases creation
    # ----------------
    Phase(
        "BLACK_WHITE",
        1,
        Criteria(min_rewards=10, min_trials=50),
        force_correct_image=TSImage.LIGHT,
    )
    Phase("FLOWER_PLANE", 2, Criteria(accuracy=(0.8, 50)))
    Phase("REVERSAL", 3, Criteria(accuracy=(0.8, 50)), use_opposite=True)
    Phase("END", 4, Criteria(), force_correct_image=TSImage.DARK)

    # Room creation
    # ----------------
    wp_alpha = WaterPump(comPort="COM22")
    ts_alpha = TouchScreen(comPort="COM20")
    gate_alpha = Gate(
        COM_Servo="COM36",
        COM_Arduino="COM30",
        COM_RFID="COM27",
        weightFactor=0.6,
        mouseAverageWeight=25,
    )
    gate_alpha.setOrder(
        GateOrder.ONLY_ONE_ANIMAL_IN_B,
        options=["no rfid check on return"],
    )

    Room(
        name="rA",
        gate=gate_alpha,
        touchscreen=ts_alpha,
        waterpump=wp_alpha,
    )

    # Global recording
    # ----------------
    cam_recorder = CameraRecorder(
        deviceNumber=0, bufferDurationS=50, showStream=True
    )  # for saving videos

    sensors = RoomSensorDigest(
        comPort="COM25", delayS=5 * 60
    )  # get environment data every 5 minutes

    # RETURN
    # ----------------
    return images_to_attribute, sensors, cam_recorder


if __name__ == "__main__":
    print("*** Start of program ***")
    experiment_parameters = get_experiment_parameters()

    sys.excepthook = excepthook
    app = QApplication([])

    visualExperiment = VisualDiscriminationInterface()
    app.aboutToQuit.connect(visualExperiment.shutdown)

    experiment = VisualDiscriminationExperiment(*experiment_parameters)

    visualExperiment.start(experiment)  # may need modifications
    visualExperiment.show()

    sys.exit(app.exec())

    print("*** End of program ***")
